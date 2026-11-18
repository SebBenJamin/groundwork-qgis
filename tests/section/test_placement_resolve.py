"""Placement at build time: each dataset is put on its profile by the known points, its own
placement or 0.8's station-set rule, and map-coordinate files are projected onto the line."""
import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from groundwork_geophysics.core.model import (Dataset, attach_station_set, file_fingerprint,
                                             profile_from_line, profile_from_polyline)
from groundwork_geophysics.core.roles import ModelColumns
from groundwork_geophysics.section.data import SectionDataProvider
from groundwork_geophysics.section.placement_resolve import invented, resolve_map
from groundwork_geophysics.store.gpkg_store import ProjectStore

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CRS = "EPSG:25832"
GUESS_NOTE = ("Known points not used: the station spacing guessed from the model does not "
              "fit them; type the station spacing in Profile Properties")
NO_ELECTRODES = "No electrode positions: import them or type the spacing in Profile Properties"


def _bert(path, xs) -> Path:
    """A BERT readings file with six electrodes at ``xs`` (z 0) and five readings."""
    assert len(xs) == 6
    rows = ["1 4 2 3", "2 5 3 4", "3 6 4 5", "1 6 2 5", "1 2 3 4"]
    path.write_text("6\n# x z\n" + "".join(f"{x} 0\n" for x in xs)
                    + "5\n# a b m n rhoa\n" + "".join(f"{r} 100.0\n" for r in rows) + "0\n")
    return path


def _text_model(path, x_max=100.0, step=2.5) -> Path:
    """A free-text model of two cell rows, cells ``step`` wide from file distance 0."""
    xs = np.arange(step / 2, x_max, step)
    path.write_text("".join(f"{x:.3f} {z} 100\n" for z in (99.5, 98.5) for x in xs))
    return path


TEXT_OPTIONS = {"table": {"header": False},
                "columns": ModelColumns(distance=0, vertical=1, vertical_kind="elevation",
                                        value=2).to_dict(), "z_kind": "elevation"}


def _add(st, p, path, reader, options, did, set_id="", kind="ert_model"):
    mt, sha = file_fingerprint(path)
    d = Dataset(did, p.id, set_id, kind, str(path), mt, sha, reader, options, {}, name=did)
    st.save_dataset(d)
    return d


def _f001(tmp_path, name="f001_res.dat") -> Path:
    src = tmp_path / name
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    return src


def _mesh(provider, pid, did):
    return next(la for la in provider.layers(pid) if la.dataset.id == did).mesh


def _source(provider, pid, did):
    st = provider.store
    d = next(d for d in st.datasets(pid) if d.id == did)
    return resolve_map(st.profile(pid), st.station_sets(pid), d, provider.layout(pid))[1]


def _drawn(tmp_path, length=60.0):
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("D", CRS, np.array([[0.0, 0.0], [length, 0.0]]))
    st.save_profile(p)
    return st, p


# -- known points -------------------------------------------------------------------------

def test_an_old_profile_with_a_readings_file_is_pinned(store_with_model, tmp_path):
    st, p, _ = store_with_model
    [s] = st.station_sets(p.id)
    # stations 1 and 2 surveyed at chainage 0 and 50; the readings file has them at x 5, 55
    readings = _bert(tmp_path / "line.data", [5, 55, 105, 155, 205, 255])
    _add(st, p, readings, "bert_data", {}, "r", s.id, "ert_measured")
    provider = SectionDataProvider(st)
    assert _source(provider, p.id, "d1") == "readings"
    assert _mesh(provider, p.id, "d1").bounds()[:2] == pytest.approx((-5.0, 5.0))
    assert provider.fit(p.id, "d1").max_shift == pytest.approx(0.0)
    assert provider.placement_note(p.id) == ""


def test_a_guess_that_does_not_fit_is_not_used(store_with_model):
    st, p, _ = store_with_model
    [s] = st.station_sets(p.id)
    xyz = np.column_stack([np.arange(11) * 4.0, np.zeros(11), np.full(11, 100.0)])
    st.save_station_set(replace(attach_station_set(p, s.name, "ert", xyz), id=s.id))
    # stations every 4 m, the model's top cells 2 m wide: the guess would squeeze it
    provider = SectionDataProvider(st)
    assert _source(provider, p.id, "d1") == "guess_rejected"
    assert _mesh(provider, p.id, "d1").bounds()[:2] == pytest.approx((0.0, 10.0))
    assert provider.fit(p.id, "d1") is None
    assert provider.placement_note(p.id) == GUESS_NOTE


def test_a_guess_that_fits_pins_and_is_marked(tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("G", CRS, np.array([[0.0, 0.0], [30.0, 0.0]]))
    s_true = np.array([0.0, 2.1, 3.9, 6.2, 8.0, 10.1])         # surveyed, about 2 m apart
    s = attach_station_set(p, "G", "ert", np.column_stack([s_true, np.full(6, 0.3),
                                                           np.full(6, 100.0)]))
    st.save_profile(p); st.save_station_set(s)
    _add(st, p, _f001(tmp_path), "r2_res_dat", {"z_kind": "elevation"}, "d", s.id)
    provider = SectionDataProvider(st)
    assert _source(provider, p.id, "d") == "guessed"
    xs = np.unique(np.round(_mesh(provider, p.id, "d").vertices[:, 0], 6))
    assert xs == pytest.approx(s_true)                           # cell edges on the stations
    fit = provider.fit(p.id, "d")
    assert fit.n == 6 and not fit.warn and fit.at == "4"
    assert "(pinned with a guessed spacing)" in fit.text(guessed=True)
    assert provider.placement_note(p.id) == ""


def test_stations_invented_by_0_8_do_not_pin(tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p, s = profile_from_line("L", CRS, np.array([[0.0, 0.0], [50.0, 0.0]]), spacing=5.0)
    st.save_profile(p); st.save_station_set(s)
    _add(st, p, _f001(tmp_path), "r2_res_dat", {"z_kind": "elevation"}, "d", s.id)
    _add(st, p, _bert(tmp_path / "line.data", np.arange(6) * 2.0), "bert_data", {}, "r",
         s.id, "ert_measured")
    provider = SectionDataProvider(st)
    assert invented(st.station_sets(p.id)[0])
    assert _source(provider, p.id, "d") == "rigid"
    assert _mesh(provider, p.id, "d").bounds()[:2] == pytest.approx((0.0, 10.0))
    assert provider.electrodes(p.id).kind == "imported"


def test_invented_needs_three_uniform_unsurveyed_stations():
    p = profile_from_polyline("U", CRS, np.array([[437702.17, 5850701.25],
                                                  [437784.44, 5850748.75]]))
    _, made = profile_from_line("U", CRS, p.xy, spacing=5.0)
    assert invented(made)                       # offsets ~1e-10 off a diagonal UTM line
    two = attach_station_set(p, "U", "ert", np.array([[437702.17, 5850701.25, np.nan],
                                                      [437706.50, 5850703.75, np.nan]]))
    assert not invented(two)
    surveyed = replace(made, xyz=np.column_stack([made.xyz[:, :2],
                                                  np.full(len(made.xyz), 57.0)]))
    assert not invented(surveyed)
    off_line = replace(made, offset=np.r_[0.2, np.zeros(len(made.offset) - 1)])
    assert not invented(off_line)
    uneven = replace(made, chainage=np.r_[made.chainage[:-1], made.chainage[-1] + 0.01])
    assert not invented(uneven)
    with_distances = replace(made, inline=np.arange(len(made.numbers)) * 5.0)
    assert not invented(with_distances)         # 0.8 stored no in-line distances


def test_uniform_stations_with_stored_distances_are_pinned(tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("I", CRS, np.array([[0.0, 0.0], [95.0, 0.0]]))
    s_ = np.arange(20) * 5.0
    s = attach_station_set(p, "I", "ert", np.column_stack([s_, np.zeros(20), np.full(20, np.nan)]),
                           inline=100.0 + s_)
    st.save_profile(p); st.save_station_set(s)
    model = tmp_path / "model.txt"
    xs = np.arange(101.25, 195.0, 2.5)                          # cells over file 100 .. 195
    model.write_text("".join(f"{x:.3f} {z} 100\n" for z in (99.5, 98.5) for x in xs))
    _add(st, p, model, "text_columns", TEXT_OPTIONS, "t", s.id)
    provider = SectionDataProvider(st)
    assert _source(provider, p.id, "t") == "distances"
    lo, hi = _mesh(provider, p.id, "t").bounds()[:2]
    assert lo == pytest.approx(0.0, abs=2.5) and hi == pytest.approx(95.0, abs=2.5)


def _known_points(tmp_path, inline, spacing=None):
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("K", CRS, np.array([[0.0, 0.0], [73.4, 0.0], [124.5, 0.0]]))
    if spacing is not None:
        p.metadata["electrode_spacing"] = spacing
    xyz = np.array([[0.0, 0.0, 100.0], [50.0, 0.0, 100.0], [73.4, 0.0, 100.0]])
    s = attach_station_set(p, "K", "ert", xyz, numbers=np.array([1, 11, 16]), inline=inline)
    st.save_profile(p); st.save_station_set(s)
    _add(st, p, _text_model(tmp_path / "model.txt"), "text_columns", TEXT_OPTIONS, "t", s.id)
    return st, p


def _assert_follows_known_points(st, p):
    provider = SectionDataProvider(st)
    xs = provider.layers(p.id)[0].mesh.vertices[:, 0]
    assert np.isclose(xs, 73.4).any()                    # the edge at file distance 75
    assert not np.isclose(xs, 75.0).any()
    assert xs.max() == pytest.approx(73.4 + 25.0)        # one metre per metre beyond
    assert np.isclose(xs, 50.0 + 12.5 * 23.4 / 25.0).any()   # file 62.5: stretched between


def test_pinned_profile_follows_known_points(tmp_path):
    st, p = _known_points(tmp_path, inline=np.array([0.0, 50.0, 75.0]))
    _assert_follows_known_points(st, p)
    assert _source(SectionDataProvider(st), p.id, "t") == "distances"


def test_number_only_stations_use_the_stated_spacing(tmp_path):
    st, p = _known_points(tmp_path, inline=None, spacing=5.0)
    _assert_follows_known_points(st, p)
    assert _source(SectionDataProvider(st), p.id, "t") == "spacing"


def test_stations_out_of_order_fall_back_with_a_note(tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("O", CRS, np.array([[0.0, 0.0], [40.0, 0.0]]))
    xyz = np.array([[0.0, 0.0, 100.0], [10.0, 0.0, 100.0], [20.0, 0.0, 100.0]])
    s = attach_station_set(p, "O", "ert", xyz, inline=np.array([0.0, 20.0, 10.0]))
    st.save_profile(p); st.save_station_set(s)
    _add(st, p, _f001(tmp_path), "r2_res_dat", {"z_kind": "elevation"}, "d", s.id)
    provider = SectionDataProvider(st)
    assert _source(provider, p.id, "d") == "rigid"
    assert _mesh(provider, p.id, "d").bounds()[:2] == pytest.approx((0.0, 10.0))
    assert provider.placement_note(p.id) == ("Known points not used: station 2 is out of "
                                             "order along the line")


# -- no station set ------------------------------------------------------------------------

def test_dataset_without_a_station_set_uses_its_placement(tmp_path):
    st, p = _drawn(tmp_path, 150.0)
    _add(st, p, _f001(tmp_path), "r2_res_dat",
         {"z_kind": "elevation", "placement": {"zero": 120.0, "direction": -1}}, "d")
    provider = SectionDataProvider(st)
    assert _source(provider, p.id, "d") == "rigid"
    assert _mesh(provider, p.id, "d").bounds()[:2] == pytest.approx((110.0, 120.0))


def test_layout_falls_back_when_readings_are_removed(tmp_path):
    # the map falls back on a profile with stations, the electrodes on a drawn line: a
    # profile with a station set always shows its own stations ("imported")
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("S", CRS, np.array([[0.0, 0.0], [30.0, 0.0]]))
    s = attach_station_set(p, "S", "ert", np.column_stack([np.arange(6) * 2.0, np.zeros(6),
                                                           np.full(6, 100.0)]))
    st.save_profile(p); st.save_station_set(s)
    q = profile_from_polyline("Q", CRS, np.array([[0.0, 100.0], [30.0, 100.0]]))
    st.save_profile(q)
    model = _f001(tmp_path)                     # 2 m cells: the guess fits the stations
    readings = _bert(tmp_path / "line.data", np.arange(6) * 2.0)
    _add(st, p, readings, "bert_data", {}, "pr", s.id, "ert_measured")
    _add(st, p, model, "r2_res_dat", {"z_kind": "elevation"}, "pd", s.id)
    _add(st, q, readings, "bert_data", {}, "qr", "", "ert_measured")
    _add(st, q, model, "r2_res_dat", {"z_kind": "elevation"}, "qd")
    provider = SectionDataProvider(st)
    assert _source(provider, p.id, "pd") == "readings"
    assert provider.electrodes(q.id).kind == "readings"
    provider.remove_dataset("pr")
    provider.remove_dataset("qr")
    assert _source(provider, p.id, "pd") == "guessed"
    assert all(la.mesh is not None for la in provider.layers(p.id))
    assert all(la.mesh is not None for la in provider.layers(q.id))
    assert provider.electrodes(q.id).kind == "guessed"


def test_electrodes_of_a_drawn_line_with_one_model_are_guessed(tmp_path):
    st, p = _drawn(tmp_path)
    _add(st, p, _f001(tmp_path), "r2_res_dat", {"z_kind": "elevation"}, "d")
    provider = SectionDataProvider(st)
    pid = p.id
    assert provider.electrodes(pid).kind == "guessed" and provider.snapshot(pid).electrode_kind == "guessed"
    assert provider.coverage(pid) is None
    snap = provider.snapshot(pid)
    assert [s for s, _ in snap.stations] == pytest.approx([0, 2, 4, 6, 8, 10])
    assert [label for _, label in snap.stations] == ["1", "", "", "", "", ""]
    assert snap.coverage is None and np.isnan(snap.station_heights).all()
    assert provider.placement_note(pid) == ""


def test_electrodes_from_a_stated_spacing_start_at_file_distance_0(tmp_path):
    st, p = _drawn(tmp_path)
    p.metadata["electrode_spacing"] = 5.0
    st.save_profile(p)
    _add(st, p, _f001(tmp_path), "r2_res_dat",
         {"z_kind": "elevation", "placement": {"zero": 20.0, "direction": 1}}, "d")
    provider = SectionDataProvider(st)
    e = provider.electrodes(p.id)
    assert e.kind == "spacing" and e.chainage == pytest.approx([20.0, 25.0, 30.0])
    assert provider.coverage(p.id) == pytest.approx((20.0, 30.0))


def test_no_electrodes_from_a_triangulated_model(tmp_path):
    st, p = _drawn(tmp_path)
    src = tmp_path / "f001_res.vtk"
    shutil.copy(FIXTURES / "ert" / "f001_res.vtk", src)
    _add(st, p, src, "vtk_legacy", {"z_kind": "elevation"}, "d")
    provider = SectionDataProvider(st)
    assert provider.electrodes(p.id) is None
    snap = provider.snapshot(p.id)
    assert snap.stations == [] and snap.electrode_kind == "none"
    assert provider.layers(p.id)[0].mesh is not None
    assert provider.placement_note(p.id) == NO_ELECTRODES


def test_nothing_guessed_is_stored(tmp_path):
    st, p = _drawn(tmp_path)
    _add(st, p, _f001(tmp_path), "r2_res_dat", {"z_kind": "elevation"}, "d")
    path = Path(st.path)

    def sha1():
        return hashlib.sha1(path.read_bytes()).hexdigest()

    before = sha1()
    provider = SectionDataProvider(st)
    provider.layers(p.id)
    provider.snapshot(p.id)
    assert provider.electrodes(p.id).kind == "guessed"
    provider.layout(p.id)
    provider.fit(p.id, "d")
    provider.placement_note(p.id)
    assert sha1() == before


# -- map coordinates -----------------------------------------------------------------------

MAP_COLUMNS = ModelColumns(position="map", easting=0, northing=1, vertical=2,
                           vertical_kind="depth", value=3).to_dict()


def _map_points():
    return np.unique(np.loadtxt(FIXTURES / "wild" / "east_north_depth_rho.csv",
                                delimiter=",", skiprows=1)[:, :2], axis=0)


def _map_profile(tmp_path, end_xy, src=None, crs=""):
    """A profile from the file's first position to ``end_xy``, surveyed at both ends (the
    depth model hangs from them), with the map file as a dataset without a station set."""
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    start = _map_points()[0]
    p = profile_from_polyline("M", CRS, np.array([start, end_xy]))
    s = attach_station_set(p, "M", "ert", np.array([[*start, 57.0], [*end_xy, 58.0]]))
    st.save_profile(p); st.save_station_set(s)
    src = src or tmp_path / "east_north_depth_rho.csv"
    if not src.exists():
        shutil.copy(FIXTURES / "wild" / "east_north_depth_rho.csv", src)
    d = _add(st, p, src, "text_columns",
             {"table": {}, "columns": dict(MAP_COLUMNS, crs=crs), "z_kind": "depth"}, "m")
    return st, p, d


def test_map_file_lands_on_the_profile(qgis_app, tmp_path):
    st, p, _ = _map_profile(tmp_path, _map_points()[-1])
    provider = SectionDataProvider(st)
    [layer] = provider.layers(p.id)
    assert layer.error is None
    lo, hi = layer.mesh.bounds()[:2]
    length = p.chainage.length
    assert length == pytest.approx(95.0, abs=0.1)
    # the outer cells reach half the 5 m step past the first and last position
    assert lo == pytest.approx(0.0, abs=2.5) and hi == pytest.approx(length, abs=2.5)
    assert provider.fit(p.id, "m") is None


def test_map_cells_beyond_the_line_are_reported(qgis_app, tmp_path):
    pts = _map_points()
    st, p, d = _map_profile(tmp_path, pts[len(pts) // 2])
    provider = SectionDataProvider(st)
    [layer] = provider.layers(p.id)
    assert layer.mesh is not None
    assert provider._read(d, p).provenance["n_beyond"] > 0


def test_map_file_follows_a_moved_line(qgis_app, tmp_path):
    pts = _map_points()
    st, p, _ = _map_profile(tmp_path, pts[-1])
    provider = SectionDataProvider(st)
    full = provider.layers(p.id)[0].mesh.bounds()[1]
    p.xy = np.array([pts[len(pts) // 2], pts[-1]])                     # starts half-way
    st.save_profile(p)
    lo, hi = provider.layers(p.id)[0].mesh.bounds()[:2]                 # re-read
    assert hi < full - 30.0 and lo < -30.0       # the first half now lies before the start


def test_map_file_in_another_crs_is_transformed(qgis_app, tmp_path):
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY,
                           QgsProject)

    to_wgs84 = QgsCoordinateTransform(QgsCoordinateReferenceSystem(CRS),
                                      QgsCoordinateReferenceSystem("EPSG:4326"),
                                      QgsProject.instance())
    rows = np.loadtxt(FIXTURES / "wild" / "east_north_depth_rho.csv", delimiter=",",
                      skiprows=1)
    src = tmp_path / "lon_lat.csv"
    lines = ["lon,lat,depth,rho"]
    for e, n, z, v in rows:
        q = to_wgs84.transform(QgsPointXY(e, n))
        lines.append(f"{q.x():.9f},{q.y():.9f},{z},{v}")
    src.write_text("\n".join(lines) + "\n")
    st, p, _ = _map_profile(tmp_path, _map_points()[-1], src, crs="EPSG:4326")
    reference = tmp_path / "ref"
    reference.mkdir()
    st_ref, p_ref, _ = _map_profile(reference, _map_points()[-1])
    got = SectionDataProvider(st).layers(p.id)[0].mesh.bounds()
    want = SectionDataProvider(st_ref).layers(p_ref.id)[0].mesh.bounds()
    assert got == pytest.approx(want, abs=0.01)


# -- robustness ----------------------------------------------------------------------------

def test_one_bad_dataset_does_not_break_the_profile(tmp_path, monkeypatch):
    st, p = _drawn(tmp_path)
    _add(st, p, _bert(tmp_path / "line.data", np.arange(6) * 2.0), "bert_data", {}, "r", "",
         "ert_measured")
    _add(st, p, _f001(tmp_path), "r2_res_dat", {"z_kind": "elevation"}, "d")
    provider = SectionDataProvider(st)
    real = provider._read

    def odd(d, profile=None):
        result = real(d, profile)
        if d.id == "r":                         # an electrode block that is not numbers
            result = replace(result, provenance=dict(result.provenance,
                                                     electrode_x=["a", None, "b"]))
        return result

    monkeypatch.setattr(provider, "_read", odd)
    layers = provider.layers(p.id)
    snap = provider.snapshot(p.id)
    assert _mesh(provider, p.id, "d") is not None
    assert next(la for la in layers if la.dataset.id == "d").error is None
    assert snap.profile_id == p.id
    assert provider.electrodes(p.id).kind == "guessed"     # the readings give no layout


def test_real_pins_survive_a_rejected_guess(tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("R", CRS, np.array([[0.0, 0.0], [60.0, 0.0]]))
    # stations 1-3 surveyed with their file distances (5 m along the line per 4 m in the
    # file: they fit), stations 4-11 every 5 m without one; the model's 2 m top cells give a
    # guessed spacing of 2 m that squeezes them
    s_ = np.r_[0.0, 5.0, 10.0, 15.0 + 5.0 * np.arange(8)]
    inline = np.r_[0.0, 4.0, 8.0, np.full(8, np.nan)]
    s = attach_station_set(p, "R", "ert", np.column_stack([s_, np.zeros(11), np.full(11, 100.0)]),
                           inline=inline)
    st.save_profile(p); st.save_station_set(s)
    _add(st, p, _f001(tmp_path), "r2_res_dat", {"z_kind": "elevation"}, "d", s.id)
    provider = SectionDataProvider(st)
    assert provider.layout(p.id).guessed_spacing == pytest.approx(2.0)
    assert _source(provider, p.id, "d") == "distances"
    fit = provider.fit(p.id, "d")
    assert fit.n == 3 and not fit.warn
    # pinned by the three: file 0, 4, 8 at chainage 0, 5, 10, one metre per metre beyond
    assert _mesh(provider, p.id, "d").bounds()[:2] == pytest.approx((0.0, 12.0))
    assert provider.placement_note(p.id) == ""


def _surveyed_with_a_triangulated_model(tmp_path):
    """Profile G with six surveyed stations about 2 m apart and a triangulated VTK model
    (no guess) as its first dataset."""
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("G", CRS, np.array([[0.0, 0.0], [30.0, 0.0]]))
    s_true = np.array([0.0, 2.1, 3.9, 6.2, 8.0, 10.1])
    s = attach_station_set(p, "G", "ert", np.column_stack([s_true, np.full(6, 0.3),
                                                           np.full(6, 100.0)]))
    st.save_profile(p); st.save_station_set(s)
    tri = tmp_path / "f001_res.vtk"
    shutil.copy(FIXTURES / "ert" / "f001_res.vtk", tri)
    _add(st, p, tri, "vtk_legacy", {"z_kind": "elevation"}, "t", s.id)
    return st, p, s, s_true


def test_the_guess_comes_from_the_first_model_that_gives_one(tmp_path):
    """A triangulated model listed first gives no guess; the row model after it does."""
    st, p, s, s_true = _surveyed_with_a_triangulated_model(tmp_path)
    _add(st, p, _f001(tmp_path), "r2_res_dat", {"z_kind": "elevation"}, "d", s.id)
    provider = SectionDataProvider(st)
    assert provider.layout(p.id).guess is not None
    assert _source(provider, p.id, "d") == "guessed"
    xs = np.unique(np.round(_mesh(provider, p.id, "d").vertices[:, 0], 6))
    assert xs == pytest.approx(s_true)


def test_map_points_past_the_line_ends_extend_its_end_segments():
    """Before the start: negative chainage; after the end: beyond the length, along the
    first/last segment; ``beyond`` still marks them."""
    from groundwork_geophysics.core.model import Profile
    from groundwork_geophysics.section.data import xy_to_distance_on

    p = Profile("p", "P", np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]), CRS)
    s, offset, beyond = xy_to_distance_on(p, "", CRS)(np.array([-5.0, 5.0, 9.0]),
                                                       np.array([1.0, -2.0, 15.0]))
    assert s == pytest.approx([-5.0, 5.0, 25.0])
    assert offset == pytest.approx([1.0, -2.0, 1.0])
    assert beyond.tolist() == [True, False, True]


@pytest.mark.parametrize("names, at", [(["A1", "", "A3"], "A3"), (["A1", "B", ""], "16")])
def test_fit_report_names_the_station(tmp_path, names, at):
    """The station that moves most is named by its point name, else by its number."""
    from groundwork_geophysics.section.placement_resolve import resolve

    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("K", CRS, np.array([[0.0, 0.0], [73.4, 0.0], [124.5, 0.0]]))
    xyz = np.array([[0.0, 0.0, 100.0], [50.0, 0.0, 100.0], [73.4, 0.0, 100.0]])
    s = attach_station_set(p, "K", "ert", xyz, numbers=np.array([1, 11, 16]),
                           inline=np.array([0.0, 50.0, 75.0]), names=names)
    st.save_profile(p); st.save_station_set(s)
    d = _add(st, p, _text_model(tmp_path / "model.txt"), "text_columns", TEXT_OPTIONS, "t", s.id)
    provider = SectionDataProvider(st)
    r = resolve(p, st.station_sets(p.id), d, provider.layout(p.id))
    assert r.fit.at == at


def _refrapy(tmp_path) -> Path:
    for name in ("L9_xzv.txt", "L9_topography.txt"):
        shutil.copy(FIXTURES / "seismic" / name, tmp_path / name)
    return tmp_path / "L9_xzv.txt"


def test_station_x_is_the_layout_guess(tmp_path):
    """A Refrapy model is triangulated (no guess from its cells), but its topography file
    names the shot and geophone points: they are the guess."""
    st, p = _drawn(tmp_path)
    _add(st, p, _refrapy(tmp_path), "refrapy_xzv", {"z_kind": "elevation"}, "d",
         kind="srt_model")
    provider = SectionDataProvider(st)
    e = provider.electrodes(p.id)
    assert e is not None and e.kind == "guessed"
    assert e.chainage == pytest.approx([0.0, 2.0, 4.0, 8.0])


def test_a_refraction_profile_without_positions_asks_for_geophones(tmp_path):
    from groundwork_geophysics.core.layout import kind_text
    st, p = _drawn(tmp_path)
    vtk = tmp_path / "f001_res.vtk"
    shutil.copy(FIXTURES / "ert" / "f001_res.vtk", vtk)
    _add(st, p, vtk, "vtk_legacy", {"z_kind": "elevation"}, "d", kind="srt_model")
    provider = SectionDataProvider(st)
    assert provider.placement_note(p.id).startswith("No geophone positions")
    assert provider.station_method(p.id) == "srt"
    assert kind_text("guessed", "srt") == "geophones guessed from the model"
    assert kind_text("spacing", "ert", "2") == "electrodes from a spacing of 2 m"
