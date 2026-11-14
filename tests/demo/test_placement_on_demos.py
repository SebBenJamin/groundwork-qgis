"""0.9 placement checked against the real demo data: sparse known points, map coordinates,
the electrode guess, and the 0.8 demo projects. Every store is copied to tmp_path first: the
committed demo folders hold the user's own drawings and are never opened in place."""
import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent.parent
DEMOS = {"Erfurt": (REPO / "demo_erfurt", "erfurt_workbench.gpkg"),
         "Gülpe": (REPO / "demo_guelpe", "guelpe_workbench.gpkg")}
SMALL_DEMO = REPO / "demo" / "data"
#: metres of chainage the thinned placement may differ from the fully surveyed one
TOLERANCE = 0.5


def _copy(tmp_path, name) -> Path:
    folder, gpkg = DEMOS[name]
    copy = tmp_path / folder.name
    shutil.copytree(folder, copy, ignore=shutil.ignore_patterns("*-wal", "*-shm"))
    return copy / gpkg


def _open(tmp_path, name):
    from geophysics_workbench.store.gpkg_store import ProjectStore
    return ProjectStore.open(_copy(tmp_path, name))


def _model(st, profile):
    return next((d for d in st.datasets(profile.id) if d.kind == "ert_model"), None)


def _profile_cases():
    """(demo, profile name) of every profile that has a model, read from the committed
    stores without opening them: sqlite read-only on a copy would still be an open, so the
    names are fixed here and checked when the copy is opened."""
    erfurt = ["ERT02", "ERT03", "ERT04", "ERT06", "ERT07", "ERT11", "ERT12"]
    return ([("Erfurt", n) for n in erfurt]
            + [("Gülpe", f"Transect {i}") for i in range(1, 5)])


@pytest.mark.parametrize("demo,profile_name", _profile_cases())
def test_sparse_known_points_land_like_the_full_survey(qgis_app, tmp_path, demo, profile_name,
                                                       capsys):
    """Every 5th electrode (and the last), a typed spacing: the model lands within 0.5 m of
    where all electrodes put it."""
    from geophysics_workbench.section.data import SectionDataProvider

    st = _open(tmp_path, demo)
    profile = next((p for p in st.profiles() if p.name == profile_name), None)
    assert profile is not None, f"{demo} has no profile {profile_name}"
    model = _model(st, profile)
    assert model is not None
    for d in st.datasets(profile.id):          # the readings file would outrank the spacing
        if d.id != model.id:
            st.delete_dataset(d.id)
    [full] = st.station_sets(profile.id)
    order = np.argsort(full.numbers)
    spacing = float(np.median(np.diff(np.asarray(full.chainage, float)[order])))
    profile.metadata["electrode_spacing"] = spacing
    st.save_profile(profile)

    def placed_x():
        provider = SectionDataProvider(st)
        [layer] = provider.layers(profile.id)
        assert layer.error is None
        resolution = provider.fit(profile.id, model.id)
        return layer.mesh.vertices[:, 0].copy(), resolution

    surveyed, fit_full = placed_x()
    keep = np.unique(np.r_[order[::5], order[-1]])
    st.save_station_set(replace(
        full, numbers=full.numbers[keep], xyz=full.xyz[keep], chainage=full.chainage[keep],
        offset=full.offset[keep], inline=np.full(len(keep), np.nan)))
    sparse, fit_sparse = placed_x()
    assert fit_full is not None and fit_sparse is not None, "the spacing must pin the model"
    worst = float(np.abs(sparse - surveyed).max())
    with capsys.disabled():
        print(f"\n[sparse] {demo} {profile_name}: {len(full.numbers)} electrodes -> "
              f"{len(keep)}, spacing {spacing:.3f} m, largest difference {worst:.3f} m")
    assert worst <= TOLERANCE


def test_map_coordinate_copy_lands_on_the_same_cells(qgis_app, tmp_path):
    """Gülpe Transect 3's model rewritten as easting, northing, elevation, rho (cell
    centres along the real line) and imported through text_columns on the same profile."""
    from geophysics_workbench.core.model import Dataset, file_fingerprint
    from geophysics_workbench.core.roles import ModelColumns
    from geophysics_workbench.section.data import SectionDataProvider

    st = _open(tmp_path, "Gülpe")
    profile = next((p for p in st.profiles() if p.name == "Transect 3"), None)
    assert profile is not None, "Gülpe has no profile Transect 3"
    provider = SectionDataProvider(st)
    [layer] = provider.layers(profile.id)
    mesh = layer.mesh
    centres, values = _centres(mesh), mesh.values      # triangles carry -1 padding
    # every cell, also those of the model's padding past the line's ends: their map
    # positions lie on the first/last segment extended, and the import puts them back there
    outer = (centres[:, 0] < 0) | (centres[:, 0] > profile.chainage.length)
    assert outer.sum() >= 40, outer.sum()     # 47 when measured in Task 16; the demo may change
    xy = profile.chainage.to_xy(centres[:, 0])
    table = tmp_path / "t3_map.csv"
    rows = np.column_stack([xy[:, 0], xy[:, 1], centres[:, 1], values])
    np.savetxt(table, rows, delimiter=",", header="easting,northing,elevation,rho",
               comments="", fmt="%.6f")
    mtime, sha = file_fingerprint(table)
    options = {"table": {"delimiter": "comma", "header": True},
               "columns": ModelColumns(position="map", easting=0, northing=1, vertical=2,
                                       vertical_kind="elevation", value=3).to_dict(),
               "z_kind": "elevation"}
    [station_set] = st.station_sets(profile.id)
    st.save_dataset(Dataset("d_map", profile.id, station_set.id, "ert_model", str(table),
                            mtime, sha, "text_columns", options, {}, name="T3 map"))
    layers = {la.dataset.id: la for la in SectionDataProvider(st).layers(profile.id)}
    imported = layers["d_map"]
    assert imported.error is None, imported.error
    # T3's model is triangulated, so its cell centres are not a grid: the import triangulates
    # them again (reconstruction "delaunay") and its mesh vertices are the original centres.
    # Match every imported vertex to its original centre, one to one.
    from scipy.spatial import cKDTree
    got = imported.mesh.vertices
    assert len(got) == len(centres), (len(got), len(centres))
    gap, match = cKDTree(centres).query(got)
    assert len(np.unique(match)) == len(centres), "two imported points share one centre"
    # The map coordinates are written with 6 decimals and projected back onto the line:
    # the data gives about 1e-5 m, so 1 cm is a real check, far below the 0.5 m that a
    # misplaced import (a shifted or stretched line) would show.
    assert np.abs(got[:, 0] - centres[match, 0]).max() <= 0.01, "chainage differs"
    beyond = outer[match]
    assert beyond.sum() == outer.sum()                 # the outer cells came back too
    assert np.abs(got[beyond, 0] - centres[match][beyond, 0]).max() <= 0.01
    assert np.abs(got[:, 1] - centres[match, 1]).max() <= 0.01, "elevation differs"
    assert gap.max() <= 0.01
    # each triangle takes the log-mean of its three points' values: the original ones
    cells = imported.mesh.cells[:, :3]
    expected = np.exp(np.log(values[match][cells]).mean(axis=1))
    np.testing.assert_allclose(imported.mesh.values, expected, rtol=1e-5)


def _centres(mesh) -> np.ndarray:
    corners = np.where((mesh.cells >= 0)[..., None], mesh.vertices[np.maximum(mesh.cells, 0)], 0)
    return corners.sum(1) / (mesh.cells >= 0).sum(1)[:, None]


def _real_spacing(csv: Path) -> tuple[int, float]:
    pts = np.loadtxt(csv, delimiter=",", skiprows=1)
    step = np.hypot(*np.diff(pts[:, 1:3], axis=0).T)
    return len(pts), float(np.median(step))


def test_guess_against_the_real_electrodes(tmp_path, capsys):
    """The demo's row models against their surveyed electrodes: the guess finds the cell
    edges, half the real spacing. The figures go into the 0.9.0 release notes."""
    from geophysics_workbench import readers
    from geophysics_workbench.core.layout import guess_electrodes

    lines = []
    for name, model, electrodes in (
            ("P1", SMALL_DEMO / "ert/P1/f001_res.dat", SMALL_DEMO / "stations/P1_electrodes.csv"),
            ("P2", SMALL_DEMO / "ert/P2/P2_model.dat", SMALL_DEMO / "stations/P2_electrodes.csv")):
        result = readers.read(model)
        guess = guess_electrodes(result.mesh, result.z_kind)
        n_real, spacing_real = _real_spacing(electrodes)
        assert guess.size >= 2, f"{name}: no guess from a row model"
        spacing_guess = float(np.median(np.diff(guess)))
        lines.append(f"[guess] {name}: guessed {guess.size} electrodes, median spacing "
                     f"{spacing_guess:.3f} m; real {n_real} electrodes, median spacing "
                     f"{spacing_real:.3f} m")
        # the cells of these models are half an electrode spacing wide, so the top edge has a
        # vertex every half spacing: half the real spacing, about twice the electrodes
        assert spacing_guess == pytest.approx(spacing_real / 2, rel=0.05), name
        assert abs(guess.size - (2 * n_real - 1)) <= 2, name
    with capsys.disabled():
        print("\n" + "\n".join(lines))


@pytest.mark.parametrize("demo", ["Erfurt", "Gülpe"])
def test_no_guess_from_the_demo_vtk_models(qgis_app, tmp_path, demo):
    """Triangulated pyGIMLi results give no electrode guess."""
    from geophysics_workbench import readers
    from geophysics_workbench.core.layout import guess_electrodes

    folder = _copy(tmp_path, demo).parent
    files = sorted(folder.glob("data/ert/*/dcinv.result.vtk"))
    assert files
    for path in files:
        result = readers.read(path)
        assert guess_electrodes(result.mesh, result.z_kind).size == 0, path.name


@pytest.mark.parametrize("demo", ["Erfurt", "Gülpe"])
def test_0_8_demo_projects_open_and_are_pinned(qgis_app, tmp_path, capsys, demo):
    """The committed (0.8) stores open on a copy and move to schema 3 with no layer error, no
    new profile and no new metadata key; a profile with a readings file is pinned by it. The
    largest shift against 0.8's rule goes into the release notes."""
    from geophysics_workbench.core.model import data_to_chainage
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.section.placement_resolve import resolve
    from geophysics_workbench.store.gpkg_store import ProjectStore

    folder, gpkg = DEMOS[demo]
    original = hashlib.sha1((folder / gpkg).read_bytes()).hexdigest()
    path = _copy(tmp_path, demo)
    st = ProjectStore.open(path)
    before = {p.name: dict(p.metadata) for p in st.profiles()}
    provider = SectionDataProvider(st)
    lines = []
    for p in st.profiles():
        sets = st.station_sets(p.id)
        datasets = st.datasets(p.id)
        layers = provider.layers(p.id)
        assert all(la.error is None for la in layers), (p.name, [la.error for la in layers])
        if any(d.kind == "ert_measured" for d in datasets):
            assert provider.layout(p.id).readings_x is not None, p.name
            model = _model(st, p)
            assert model is not None, f"{demo} {p.name} has no model"
            assert provider.fit(p.id, model.id) is not None, p.name
            placed = resolve(p, sets, model, provider.layout(p.id))
            assert placed.source == "readings", (p.name, placed.source)
        shifts = []
        for d in datasets:
            if d.kind != "ert_model" or not sets:
                continue
            station_set = next((s for s in sets if s.id == d.station_set_id), sets[0])
            file_x = provider._read(d).mesh.vertices[:, 0]
            layer = next((la for la in layers if la.dataset.id == d.id), None)
            assert layer is not None, f"{demo} {p.name}: no layer for {d.id}"
            shifts.append(np.abs(layer.mesh.vertices[:, 0]
                                 - data_to_chainage(file_x, station_set, d)).max())
        if shifts:
            lines.append(f"[shift] {demo} {p.name}: largest shift against 0.8 "
                         f"{max(shifts):.3f} m")
    after = {p.name: dict(p.metadata) for p in ProjectStore.open(path).profiles()}
    assert after == before                        # no profile or key added by opening
    assert hashlib.sha1((folder / gpkg).read_bytes()).hexdigest() == original
    with capsys.disabled():
        print("\n" + "\n".join(lines))
