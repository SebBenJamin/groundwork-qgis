import os
import shutil

import numpy as np
import pytest

from geophysics_workbench.core.colors import ColorScale
from geophysics_workbench.core.model import Dataset, file_fingerprint, profile_from_stations
from geophysics_workbench.section.data import (LayerStyle, SectionDataProvider,
                                                cell_path_groups)
from geophysics_workbench.store.gpkg_store import ProjectStore

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "ert")


def test_profile_for_curve_either_direction(store_with_model):
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    assert prov.profile_for_curve(p.xy).id == p.id
    assert prov.profile_for_curve(p.xy[::-1]).id == p.id
    assert prov.profile_for_curve(p.xy + 50) is None


def test_layers_and_identify(store_with_model):
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    [layer] = prov.layers(p.id)
    assert layer.error is None and layer.style.scale is not None
    xmin, xmax, zmin, zmax = layer.mesh.bounds()
    hit = prov.identify(p.id, (xmin + xmax) / 2, (zmin + zmax) / 2)
    assert hit[0]["name"] == "P1 model" and hit[0]["unit"] == "ohm.m"


def test_missing_source_reports_error_not_raise(store_with_model):
    st, p, src = store_with_model
    src.unlink()
    [layer] = SectionDataProvider(st).layers(p.id)
    assert layer.mesh is None and layer.error.startswith("source missing")


# -- additional behaviour -------------------------------------------------------------------

def _add_dataset(st, p, path, reader, options, did="d2", name="second"):
    s = st.station_sets(p.id)[0]
    mt, sha = file_fingerprint(path)
    d = Dataset(did, p.id, s.id, "ert_model", str(path), mt, sha, reader, options, {}, name=name)
    st.save_dataset(d)
    return d


def test_profile_for_curve_densified_and_tolerance(store_with_model):
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    dense = np.column_stack([np.linspace(0, 50, 11), np.zeros(11)])
    assert prov.profile_for_curve(dense).id == p.id
    assert prov.profile_for_curve(p.xy + [0.5, 0]).id == p.id      # within 1 m
    assert prov.profile_for_curve(p.xy + [0.5, 0], tol=0.1) is None
    shorter = np.array([[0, 0], [25, 0.0]])
    assert prov.profile_for_curve(shorter) is None


def test_layer_mesh_in_chainage_and_identify_values(store_with_model, tmp_path):
    st, p, _ = store_with_model
    s = st.station_sets(p.id)[0]
    prov = SectionDataProvider(st)
    [layer] = prov.layers(p.id)
    xmin, xmax, zmin, zmax = layer.mesh.bounds()
    # f001_res.dat has cell centres x 1..9, z -5..-0.5: its rebuilt cells span x 0..10,
    # z -6..0 (0.1.1); metre0 is 0 for station 1 at chainage 0
    assert (xmin, xmax, zmin, zmax) == pytest.approx((0 + s.metre0, 10 + s.metre0, -6, 0))
    hit = prov.identify(p.id, 5.0, -2.0)
    assert hit[0]["value"] == pytest.approx(layer.mesh.value_at(5.0, -2.0))
    assert hit[0]["version"] == 1
    assert prov.identify(p.id, 30.0, -2.0) == []                     # outside the mesh


def test_chainage_offset_and_depth_conversion_use_chainage(store_with_model, tmp_path):
    st, p, _ = store_with_model
    src = tmp_path / "zond_model_depth.dat"
    shutil.copy(os.path.join(FIXTURES, "zond_model_depth.dat"), src)
    _add_dataset(st, p, src, "zondres_xyz", {"z_kind": "depth", "chainage_offset": 10.0})
    layer = SectionDataProvider(st).layers(p.id)[1]
    assert layer.error is None
    v = layer.mesh.vertices
    # cell centres x 1..9 (+10): the rebuilt cells span 10..20
    assert v[:, 0].min() == pytest.approx(10.0) and v[:, 0].max() == pytest.approx(20.0)
    # topography: stations (s=0, z=100) and (s=50, z=102); the top row's cells start at
    # depth 0, on the surface (centres 0.5 m deep)
    top = v[np.isclose(v[:, 1], np.interp(v[:, 0], [0, 50], [100, 102]))]
    assert len(top) == 10                                            # 5 cells x 2 corners
    assert v[:, 1].max() == pytest.approx(np.interp(20.0, [0, 50], [100, 102]))
    # deepest centres at 5 m, the gap above is 2 m: the bottom edge is 6 m deep
    assert v[:, 1].min() == pytest.approx(np.interp(10.0, [0, 50], [100, 102]) - 6.0)


def test_depth_model_without_topography_is_an_error(tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p, s = profile_from_stations("P2", "EPSG:25832", np.array([[0, 0], [50, 0.0]]))   # z = nan
    st.save_profile(p); st.save_station_set(s)
    src = tmp_path / "zond_model_depth.dat"
    shutil.copy(os.path.join(FIXTURES, "zond_model_depth.dat"), src)
    _add_dataset(st, p, src, "zondres_xyz", {"z_kind": "depth"})
    prov = SectionDataProvider(st)
    assert prov.topography(p.id) is None
    [layer] = prov.layers(p.id)
    assert layer.mesh is None
    assert layer.error == "depth model needs station elevations or a DEM"


def test_reader_value_error_becomes_layer_error(store_with_model, tmp_path):
    st, p, _ = store_with_model
    bad = tmp_path / "f002_res.dat"
    bad.write_text("1 2 3\n4 5 6\n")
    _add_dataset(st, p, bad, "r2_res_dat", {})
    layers = SectionDataProvider(st).layers(p.id)
    assert [la.dataset.id for la in layers] == ["d1", "d2"]          # store order
    assert layers[1].mesh is None and "expected 4 columns" in layers[1].error


def test_mesh_cache_reloads_when_file_changes(store_with_model):
    st, p, src = store_with_model
    prov = SectionDataProvider(st)
    m1 = prov.layers(p.id)[0].mesh
    m2 = prov.layers(p.id)[0].mesh
    assert m2.vertices is m1.vertices or np.shares_memory(m1.cells, m2.cells)   # cached read
    st_ = os.stat(src)
    os.utime(src, (st_.st_atime, st_.st_mtime + 10))
    m3 = prov.layers(p.id)[0].mesh
    assert not np.shares_memory(m1.cells, m3.cells)                 # re-read
    assert m3.bounds() == pytest.approx(m1.bounds())


def test_style_auto_scale_kept_and_on_change(store_with_model):
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    calls = []
    prov.on_change.append(lambda: calls.append(1))
    assert prov.style("d1").scale is None
    scale = prov.layers(p.id)[0].style.scale
    assert scale.log is True and prov.style("d1").scale is scale
    custom = LayerStyle(visible=True, opacity=0.5, scale=ColorScale("turbo", 10, 500, True))
    prov.set_style("d1", custom)
    assert calls == [1]
    assert prov.layers(p.id)[0].style.scale.cmap == "turbo"


def test_identify_skips_hidden_and_error_layers(store_with_model):
    st, p, src = store_with_model
    prov = SectionDataProvider(st)
    prov.set_style("d1", LayerStyle(visible=False))
    assert prov.identify(p.id, 5.0, -2.0) == []


def test_topography_snapshot_and_stations(store_with_model):
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    s_topo, z_topo = prov.topography(p.id)
    assert s_topo == pytest.approx([0, 50]) and z_topo == pytest.approx([100, 102])
    snap = prov.snapshot(p.id)
    assert snap.profile_id == p.id
    assert snap.topo[1] == pytest.approx([100, 102])
    assert [s for s, _ in snap.stations] == pytest.approx([0, 50])
    assert snap.stations[0][1] == "1"                     # first station labelled
    # the snapshot is detached from the provider's live style objects
    snap.layers[0].style.opacity = 0.1
    assert prov.style("d1").opacity == 1.0


def test_match_curve_and_reversed_snapshot(store_with_model):
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    assert prov.match_curve(p.xy)[1] is False
    prof, rev = prov.match_curve(p.xy[::-1])
    assert prof.id == p.id and rev is True
    snap = prov.snapshot(p.id, reverse=True)
    xmin, xmax, _, _ = snap.layers[0].mesh.bounds()
    assert (xmin, xmax) == pytest.approx((50 - 10, 50 - 0))
    assert snap.topo[0] == pytest.approx([0, 50]) and snap.topo[1] == pytest.approx([102, 100])
    assert [s for s, _ in snap.stations] == pytest.approx([50, 0])


def test_station_labels_every_tenth(tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    xyz = np.column_stack([np.arange(25) * 2.0, np.zeros(25), np.full(25, 50.0)])
    p, s = profile_from_stations("P3", "EPSG:25832", xyz)
    st.save_profile(p); st.save_station_set(s)
    labels = [lab for _, lab in SectionDataProvider(st).snapshot(p.id).stations]
    assert len(labels) == 25
    assert [lab for lab in labels if lab] == ["1", "10", "20"]


def test_cell_path_groups_vectorised():
    from geophysics_workbench.core.section_mesh import SectionMesh
    verts = np.array([[0, 0], [1, 0], [1, 1], [0, 1], [2, 0]], dtype=float)
    cells = np.array([[0, 1, 2, 3], [1, 4, 2, -1], [0, 1, 2, -1]])
    mesh = SectionMesh(verts, cells, np.array([10.0, 1000.0, np.nan]))
    groups = cell_path_groups(mesh, ColorScale("gray", 10, 1000, True))
    assert len(groups) == 2                                # nan cell dropped
    (rgba0, elems0), (rgba1, elems1) = sorted(groups, key=lambda g: tuple(g[0]))
    assert tuple(rgba0) == (0, 0, 0, 255) and tuple(rgba1) == (255, 255, 255, 255)
    # each cell = moveTo + 4 lineTo (closed; triangles repeat the first vertex)
    assert elems0["t"].tolist() == [0, 1, 1, 1, 1]
    assert elems1["x"].tolist() == [1, 2, 1, 1, 1] and elems1["y"].tolist() == [0, 0, 1, 0, 0]


def test_reader_options_change_invalidates_cache(store_with_model):
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    m1 = prov.layers(p.id)[0].mesh
    d = st.datasets(p.id)[0]
    d.reader_options = {"z_kind": "elevation", "chainage_offset": 5.0}
    st.save_dataset(d)
    m2 = prov.layers(p.id)[0].mesh
    assert not np.shares_memory(m1.cells, m2.cells)                 # re-read
    assert m2.bounds()[:2] == pytest.approx((m1.bounds()[0] + 5, m1.bounds()[1] + 5))


def test_user_style_survives_file_reload(store_with_model):
    st, p, src = store_with_model
    prov = SectionDataProvider(st)
    custom = LayerStyle(visible=True, opacity=0.7, scale=ColorScale("viridis", 50, 400, True))
    prov.set_style("d1", custom)
    m1 = prov.layers(p.id)[0].mesh
    st_ = os.stat(src)
    os.utime(src, (st_.st_atime, st_.st_mtime + 10))
    [layer] = prov.layers(p.id)
    assert not np.shares_memory(m1.cells, layer.mesh.cells)         # reloaded ...
    assert layer.style is custom and layer.style.scale.to_dict() == {   # ... style kept
        "cmap": "viridis", "vmin": 50.0, "vmax": 400.0, "log": True}


def test_identify_skips_error_layers_and_nan_cells(store_with_model, tmp_path):
    from geophysics_workbench.core.section_mesh import SectionMesh
    from geophysics_workbench.section.data import SectionLayer, identify_layers

    st, p, _ = store_with_model
    s = st.station_sets(p.id)[0]
    st.save_dataset(Dataset("d2", p.id, s.id, "ert_model", str(tmp_path / "f009_res.dat"), 0.0,
                            "", "r2_res_dat", {}, {}, name="top"))   # drawn on top, missing
    prov = SectionDataProvider(st)
    layers = prov.layers(p.id)
    assert layers[1].error.startswith("source missing")
    assert [h["name"] for h in prov.identify(p.id, 5.0, -2.0)] == ["P1 model"]

    verts = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=float)
    nan_mesh = SectionMesh(verts, np.array([[0, 1, 2, -1], [0, 2, 3, -1]]),
                           np.array([np.nan, 42.0]))
    nan_layer = SectionLayer(layers[0].dataset, nan_mesh, LayerStyle(), None)
    assert identify_layers([nan_layer], 0.8, 0.2) == []             # nan cell omitted
    assert identify_layers([nan_layer], 0.2, 0.8)[0]["value"] == 42.0


def test_relative_source_path_resolves_against_store_folder(store_with_model, tmp_path):
    st, p, src = store_with_model
    [d] = st.datasets(p.id)
    d.source_path = os.path.join("models", "f001_res.dat").replace(os.sep, "/")
    st.save_dataset(d)
    prov = SectionDataProvider(st)
    [layer] = prov.layers(p.id)
    assert layer.error.startswith("source missing") and "models" in layer.error
    (tmp_path / "models").mkdir()
    shutil.move(src, tmp_path / "models" / "f001_res.dat")
    [layer] = prov.layers(p.id)
    assert layer.error is None and layer.mesh is not None
    assert prov.source_path(d) == str(tmp_path / "models" / "f001_res.dat")


def test_model_on_stations_numbered_against_profile(tmp_path):
    """Station 1 at the far end: data metres run against chainage (mesh mirrored)."""
    from geophysics_workbench import readers
    from geophysics_workbench.core.model import attach_station_set, profile_from_line

    src = tmp_path / "f001_res.dat"
    shutil.copy(os.path.join(FIXTURES, "f001_res.dat"), src)
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p, _ = profile_from_line("P", "EPSG:25832", np.array([[0, 0], [50, 0.0]]), spacing=5)
    xyz = np.column_stack([np.arange(11) * 5.0, np.zeros(11), np.full(11, 100.0)])
    s = attach_station_set(p, "e", "ert", xyz, numbers=np.arange(11, 0, -1))
    st.save_profile(p); st.save_station_set(s)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("d", p.id, s.id, "ert_model", str(src), mt, sha, "r2_res_dat",
                            {"z_kind": "elevation"}, {}))
    raw = readers.read(src).mesh.bounds()
    [layer] = SectionDataProvider(st).layers(p.id)
    s0, s1 = layer.mesh.bounds()[:2]
    assert (s0, s1) == pytest.approx((50 - raw[1], 50 - raw[0]))


def test_active_profile_wins_on_identical_geometry(store_with_model):
    """Two profiles on the same line: the curve resolves to the profile the dock opened."""
    from geophysics_workbench.core.model import Profile

    st, p, _ = store_with_model
    twin = Profile("twin", "A twin", p.xy.copy(), p.crs_authid)         # sorts before P1
    st.save_profile(twin)
    prov = SectionDataProvider(st)
    for active in (p.id, twin.id):
        prov.active_profile_id = active
        assert prov.match_curve(p.xy)[0].id == active
        assert prov.match_curve(p.xy[::-1])[0].id == active
    prov.active_profile_id = None
    assert prov.match_curve(p.xy)[0].id in (p.id, twin.id)
    prov.active_profile_id = "elsewhere"                     # active but not on this curve
    assert prov.match_curve(p.xy)[0].id in (p.id, twin.id)
