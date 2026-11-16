"""One surface per profile: station heights or the DEM, else the top of an elevation model,
else the top of a local-height model, else a flat line at 0. Without heights the section is
"local": drawn in depth, without what needs real elevations."""
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from groundwork_geophysics.core.context import ContextItems, ProjectedPoint
from groundwork_geophysics.core.model import Dataset, file_fingerprint, profile_from_polyline
from groundwork_geophysics.core.roles import ModelColumns
from groundwork_geophysics.section.data import SectionDataProvider
from groundwork_geophysics.store.gpkg_store import ProjectStore

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CRS = "EPSG:25832"
LOCAL_REASON = "No heights on this profile yet: the DEM line and boreholes are not drawn"


def _drawn(tmp_path, length=60.0):
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("D", CRS, np.array([[0.0, 0.0], [length, 0.0]]))
    st.save_profile(p)
    return st, p


def _add(st, p, path, reader, options, did, set_id=""):
    mt, sha = file_fingerprint(path)
    st.save_dataset(Dataset(did, p.id, set_id, "ert_model", str(path), mt, sha, reader,
                            options, {}, name=did))


def _text(kind):
    return {"table": {"header": False}, "z_kind": kind,
            "columns": ModelColumns(distance=0, vertical=1, vertical_kind=kind,
                                    value=2).to_dict()}


def _columns(path, tops, zero=0.0) -> Path:
    """Columns 2 m wide from distance 0, two 1 m cells each, column i topped at
    ``tops[i] + zero``."""
    rows = [f"{1.0 + 2.0 * i} {zero + top - 0.5 - k} 100\n"
            for i, top in enumerate(tops) for k in range(2)]
    path.write_text("".join(rows))
    return path


def _depth_rows(path) -> Path:
    """Two rows of 2 m cells over distance 0 .. 10, centres 0.5 and 1.5 m deep."""
    path.write_text("".join(f"{x} {z} 100\n" for z in (0.5, 1.5) for x in (1, 3, 5, 7, 9)))
    return path


def _depth_model(st, p, tmp_path, did="z"):
    src = tmp_path / f"{did}_depth.dat"
    shutil.copy(FIXTURES / "ert" / "zond_model_depth.dat", src)
    _add(st, p, src, "zondres_xyz", {"z_kind": "depth"}, did)


def _mesh(provider, pid, did):
    return next(la for la in provider.layers(pid) if la.dataset.id == did).mesh


def test_flat_surface_for_a_depth_model_without_heights(tmp_path):
    st, p = _drawn(tmp_path)
    _depth_model(st, p, tmp_path)
    provider, pid = SectionDataProvider(st), p.id
    s = provider.surface(pid)
    assert s.kind == "flat" and s.local and set(s.line[1].tolist()) == {0.0}
    assert s.line[0].tolist() == [0.0, 60.0] and s.shift == 0.0 and not s.has_reference
    assert provider.layers(pid)[0].error is None and provider.layers(pid)[0].mesh.bounds()[3] == 0.0
    assert provider.is_local(pid)
    np.testing.assert_array_equal(provider.topography(pid)[1], s.line[1])
    snap = provider.snapshot(pid)
    assert snap.local and snap.surface_kind == "flat" and not snap.dem_topo
    np.testing.assert_array_equal(snap.topo[0], s.line[0])
    assert snap.local_reason == ""                  # nothing was left out


def test_elevation_model_gives_the_surface_and_is_not_local(tmp_path):
    st, p = _drawn(tmp_path)
    _add(st, p, _depth_rows(tmp_path / "depth.txt"), "text_columns", _text("depth"), "z")
    tops = [250.0, 250.5, 251.0, 251.5, 252.0]
    _add(st, p, _columns(tmp_path / "elev.txt", tops), "text_columns", _text("elevation"), "e")
    provider, pid = SectionDataProvider(st), p.id
    s = provider.surface(pid)
    assert s.kind == "model" and not s.local and not provider.is_local(pid)
    elev, depth = _mesh(provider, pid, "e"), _mesh(provider, pid, "z")
    assert elev.bounds()[3] == 252.0                         # drawn as it is
    want = elev.top_edge()
    np.testing.assert_allclose(s.line[0], want[0])
    np.testing.assert_allclose(s.line[1], want[1])
    got = depth.top_edge()                                   # the depth model's top ...
    np.testing.assert_allclose(got[0], want[0])
    np.testing.assert_allclose(got[1], want[1])              # ... on the model's top
    assert not provider.snapshot(pid).local


def test_two_local_height_models_share_one_surface(tmp_path):
    st, p = _drawn(tmp_path)
    tops = [10.0, 10.4, 10.8, 11.2, 11.6]
    _add(st, p, _columns(tmp_path / "a.txt", tops), "text_columns", _text("local"), "a")
    _add(st, p, _columns(tmp_path / "b.txt", tops, zero=100.0), "text_columns",
         _text("local"), "b")
    _depth_model(st, p, tmp_path)
    provider, pid = SectionDataProvider(st), p.id
    s = provider.surface(pid)
    assert s.kind == "local_model" and s.local
    assert s.line[1].max() == 0.0 and s.line[1].min() == pytest.approx(-1.6)
    a, b = _mesh(provider, pid, "a"), _mesh(provider, pid, "b")
    raw = provider._read(st.datasets(pid)[0]).mesh
    np.testing.assert_allclose(a.vertices, raw.vertices - [0.0, 11.6])   # its own shape
    np.testing.assert_allclose(b.vertices, a.vertices)                   # zero 100 too
    for mesh in (a, b):
        top = mesh.top_edge()
        np.testing.assert_allclose(top[0], s.line[0])
        np.testing.assert_allclose(top[1], s.line[1])
    depth = _mesh(provider, pid, "z")                # a depth model hangs from it as well
    assert depth.bounds()[3] == pytest.approx(np.interp(depth.bounds()[1], *s.line))


def test_reference_height_shifts_everything_local(tmp_path):
    st, p = _drawn(tmp_path)
    _depth_model(st, p, tmp_path)
    profile = st.profile(p.id)
    profile.metadata["reference_height"] = {"s": 20.0, "z": 57.5}
    st.save_profile(profile)
    provider, pid = SectionDataProvider(st), p.id
    s = provider.surface(pid)
    assert not s.local and np.interp(20.0, *s.line) == pytest.approx(57.5)
    assert s.kind == "flat" and s.has_reference and s.shift == pytest.approx(57.5)
    assert _mesh(provider, pid, "z").bounds()[3] == pytest.approx(57.5)
    snap = provider.snapshot(pid)
    assert not snap.local and snap.surface_kind == "flat"
    # a local-height model, columns topped at 10, 11, 12 over 0 .. 6: its unshifted top is
    # -1 at distance 3, so 57.5 there shifts it by 58.5
    _add(st, p, _columns(tmp_path / "a.txt", [10.0, 11.0, 12.0]), "text_columns",
         _text("local"), "a")
    profile.metadata["reference_height"] = {"s": 3.0, "z": 57.5}
    st.save_profile(profile)
    s = provider.surface(pid)
    assert s.kind == "local_model" and not s.local and s.has_reference
    assert s.shift == pytest.approx(58.5) and np.interp(3.0, *s.line) == pytest.approx(57.5)
    assert _mesh(provider, pid, "a").bounds()[3] == pytest.approx(58.5)
    assert _mesh(provider, pid, "z").bounds()[3] == pytest.approx(58.5)   # zond: 0 .. 10


def test_station_heights_win_over_models(store_with_model, tmp_path):
    st, p, _ = store_with_model
    [station_set] = st.station_sets(p.id)
    _add(st, p, _columns(tmp_path / "a.txt", [10.0, 11.0]), "text_columns", _text("local"),
         "a", station_set.id)
    provider = SectionDataProvider(st)
    s = provider.surface(p.id)
    assert s.kind == "stations" and not s.local
    np.testing.assert_allclose(s.line[0], [0.0, 50.0])
    np.testing.assert_allclose(s.line[1], [100.0, 102.0])
    # the elevation model is drawn as read: cells 0 .. 10, z -6 .. 0
    assert _mesh(provider, p.id, "d1").bounds() == pytest.approx((0, 10, -6, 0))
    local = _mesh(provider, p.id, "a")
    assert local.bounds()[3] == pytest.approx(np.interp(4.0, [0, 50], [100, 102]))
    snap = provider.snapshot(p.id)
    assert snap.surface_kind == "stations" and not snap.local and snap.local_reason == ""


def test_local_snapshot_leaves_out_what_needs_elevation(tmp_path):
    st, p = _drawn(tmp_path)
    _depth_model(st, p, tmp_path)
    provider, pid = SectionDataProvider(st), p.id
    dem_s = np.linspace(0.0, 60.0, 7)
    dem_z = np.full(7, np.nan)
    dem_z[3] = 250.0                               # one sample: no DEM line to hang from
    items = ContextItems(points=[ProjectedPoint(12.0, 3.0, "BH1", "borehole"),
                                 ProjectedPoint(30.0, 1.0, "W1", "point")],
                         dem=(dem_s, dem_z))
    provider.context_source = lambda profile: items
    snap = provider.snapshot(pid)
    boreholes = [pt for pt in snap.context.points if pt.kind == "borehole"]
    assert snap.local and snap.context.dem is None and not boreholes and snap.local_reason
    assert snap.local_reason == LOCAL_REASON
    assert [pt.label for pt in snap.context.points] == ["W1"]
    assert provider.context(pid).dem is not None    # the provider's context is untouched


def test_add_model_accepts_depth_without_elevations(qgis_app, tmp_path):
    from groundwork_geophysics.ui.project_actions import add_model

    st, p = _drawn(tmp_path)
    src = tmp_path / "zond_model_depth.dat"
    shutil.copy(FIXTURES / "ert" / "zond_model_depth.dat", src)
    d = add_model(st, p.id, "", src, "zondres_xyz", {}, "depth model")
    assert d.reader_options["z_kind"] == "depth"
    local = add_model(st, p.id, "", _columns(tmp_path / "a.txt", [10.0, 11.0]), "text_columns",
                      _text("local"), "local model")
    assert local.reader_options["z_kind"] == "local"
    layers = SectionDataProvider(st).layers(p.id)
    assert [la.error for la in layers] == [None, None]


def _count_placements(provider, monkeypatch) -> list:
    """Calls of the provider's placement step (``_placed``), one entry per pass."""
    calls = []
    real = provider._placed

    def counting(*args):
        calls.append(1)
        return real(*args)
    monkeypatch.setattr(provider, "_placed", counting)
    return calls


def test_surface_is_computed_once_per_build(tmp_path, monkeypatch):
    st, p = _drawn(tmp_path)
    _depth_model(st, p, tmp_path)
    provider, pid = SectionDataProvider(st), p.id
    calls = _count_placements(provider, monkeypatch)
    provider.layers(pid)
    provider.topography(pid)
    provider.is_local(pid)
    snap = provider.snapshot(pid)
    assert len(calls) == 1
    assert snap.local and snap.surface_kind == "flat"


def test_surface_cache_follows_changes(store_with_model, tmp_path):
    st, p, _ = store_with_model
    [stations] = st.station_sets(p.id)
    [d] = st.datasets(p.id)
    st.save_station_set(replace(stations, xyz=np.column_stack(
        [stations.xyz[:, :2], np.full(len(stations.xyz), np.nan)])))
    st.save_dataset(replace(d, reader_options={"z_kind": "local"}))
    provider, pid = SectionDataProvider(st), p.id
    assert provider.surface(pid).kind == "local_model" and provider.is_local(pid)
    provider.set_reference_height(pid, 10.0, 50.0)          # a reference height set
    s = provider.surface(pid)
    assert s.referenced and not provider.is_local(pid)
    assert np.interp(10.0, *s.line) == pytest.approx(50.0)
    provider.remove_dataset(d.id)                            # a dataset removed
    s = provider.surface(pid)
    assert s.kind == "flat" and set(s.line[1].tolist()) == {50.0}
    st.save_station_set(stations)                            # station elevations attached
    s = provider.surface(pid)
    assert s.kind == "stations" and not s.local
    np.testing.assert_allclose(s.line[1], [100.0, 102.0])


def test_station_heights_surface_places_nothing(store_with_model, monkeypatch):
    st, p, _ = store_with_model
    provider, pid = SectionDataProvider(st), p.id
    calls = _count_placements(provider, monkeypatch)
    assert provider.surface(pid).kind == "stations"
    assert not provider.is_local(pid) and provider.topography(pid) is not None
    assert calls == []
    profile = st.profile(pid)                                # the DEM chosen: no placement
    profile.metadata["topography"] = "dem"
    st.save_profile(profile)
    dem_s = np.linspace(0.0, 50.0, 6)
    provider.context_source = lambda pr: ContextItems(dem=(dem_s, np.full(6, 99.0)))
    assert provider.surface(pid).kind == "dem"
    assert calls == []
