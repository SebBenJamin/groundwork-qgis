"""A local section (a profile without real heights) leaves the boreholes and the DEM out
everywhere the section's context is used: drawing, readout, snapping, map picking, the
borehole viewer's surface and tie strips."""
from dataclasses import replace

import numpy as np
import pytest

from groundwork_geophysics.core.context import ContextItems, LogInterval, ProjectedPoint
from groundwork_geophysics.section.data import SectionDataProvider
from test_borehole_open import _release, flushed  # noqa: F401
from test_context_snapshot import _add_b
from test_dock import _map_event


def _local(st, p):
    """No heights at all: the stations lose theirs, the model is read as local heights."""
    [s] = st.station_sets(p.id)
    [d] = st.datasets(p.id)
    st.save_station_set(replace(s, xyz=np.column_stack([s.xyz[:, :2],
                                                        np.full(len(s.xyz), np.nan)])))
    st.save_dataset(replace(d, reader_options={"z_kind": "local"}))
    return s


def _borehole(s=25.0, offset=0.0):
    return ProjectedPoint(s, offset, "BH1", "borehole", None,
                          [LogInterval(0.0, 3.0, "sand"), LogInterval(3.0, 6.0, "clay")])


def _items(dem_z=None):
    """A borehole at chainage 25, a plain point and a DEM (one sample by default: no DEM
    line to hang a section from)."""
    dem_s = np.linspace(0.0, 50.0, 6)
    if dem_z is None:
        dem_z = np.full(6, np.nan)
        dem_z[3] = 250.0
    return ContextItems(points=[_borehole(), ProjectedPoint(30.0, 1.0, "W1", "point")],
                        dem=(dem_s, dem_z))


def _visible(qgis_app, dock):
    for _ in range(50):
        qgis_app.processEvents()
        if not dock.is_busy():
            break
    dock.fit.user_navigated()
    dock.canvas.setVisiblePlotRange(0.0, 50.0, -10.0, 5.0)
    qgis_app.processEvents()


def test_drawn_context_leaves_out_boreholes_and_dem_when_local(store_with_model):
    st, p, _ = store_with_model
    _local(st, p)
    provider = SectionDataProvider(st)
    provider.context_source = lambda profile: _items()
    assert provider.is_local(p.id)
    drawn = provider.drawn_context(p.id)
    assert drawn.dem is None and [pt.label for pt in drawn.points] == ["W1"]
    full = provider.context(p.id)                   # the full context is untouched
    assert full.dem is not None and [pt.label for pt in full.points] == ["BH1", "W1"]
    hidden = provider.drawn_context(p.id, include_hidden=True)
    assert [pt.label for pt in hidden.points] == ["W1"]
    assert provider.drawn_context("no such profile") is None


def test_drawn_context_is_unchanged_with_real_heights(store_with_model):
    st, p, _ = store_with_model
    provider = SectionDataProvider(st)
    provider.context_source = lambda profile: _items(np.full(6, 101.0))
    assert not provider.is_local(p.id)
    drawn, full = provider.drawn_context(p.id), provider.context(p.id)
    assert [pt.label for pt in drawn.points] == [pt.label for pt in full.points] == ["BH1", "W1"]
    assert drawn.dem is not None
    np.testing.assert_array_equal(drawn.dem[1], full.dem[1])


def test_readout_reports_no_borehole_in_a_local_section(qgis_app, store_with_model, make_dock):
    from groundwork_geophysics.section.dock_context import borehole_point, context_lines
    st, p, _ = store_with_model
    _local(st, p)
    dock = make_dock(st)
    dock.provider.context_source = lambda profile: _items()
    dock.open_profile(p.id)
    _visible(qgis_app, dock)
    dock._current_layers()
    z = float(np.interp(25.0, *dock._topo)) - 1.0       # in the sand, hung from the ground
    lines = context_lines(dock, 25.0, z)
    assert not any("Borehole" in line or "BH1" in line for line in lines), lines
    assert not any("DEM" in line or "collar" in line.lower() for line in lines), lines
    assert borehole_point(dock, 25.0, z) is None


def test_no_borehole_snap_targets_in_a_local_section(qgis_app, store_with_model, make_dock):
    st, p, _ = store_with_model
    _local(st, p)
    dock = make_dock(st)
    dock.provider.context_source = lambda profile: _items()
    dock.open_profile(p.id)
    _visible(qgis_app, dock)
    dock.interp._targets = None
    targets = dock.interp.snap_targets()
    assert targets.boundaries == []
    assert targets.ground is not None                   # the ground line still is a target


def test_map_pick_ignores_boreholes_in_a_local_section(qgis_app, flushed,  # noqa: F811
                                                        store_with_model, make_dock_and_link):
    st, p, _ = store_with_model
    _local(st, p)
    dock, link = make_dock_and_link(st)
    dock.provider.context_source = lambda profile: _items()
    dock.open_profile(p.id)
    got = []
    dock.borehole_clicked.connect(lambda e, label: got.append((e, label)))
    link.tool.canvasReleaseEvent(_map_event(link.map_canvas, _release(), (25, 0), dy_px=3))
    assert got == [] and dock.current_profile_id() == p.id     # a profile pick, no viewer


def test_borehole_viewer_takes_no_surface_from_a_local_profile(qgis_app, store_with_model,
                                                               make_dock):
    from qgis.core import QgsProject

    from groundwork_geophysics.section.borehole_viewer import BoreholeViewer
    st, p, _ = store_with_model
    stations = _local(st, p)
    dock = make_dock(st)
    dock.provider.context_source = lambda profile: _items()
    dock.open_profile(p.id)
    viewer = BoreholeViewer(dock, QgsProject.instance())
    try:
        viewer.show_profile(p.id)
        assert [b.label for b in viewer.boreholes] == ["BH1"]     # still listed
        assert viewer.topo is None and viewer.surface_at(25.0) is None
        st.save_station_set(stations)                             # heights again
        dock.provider.notify_changed()
        viewer.refresh()
        assert viewer.topo is not None
        assert viewer.surface_at(25.0) == pytest.approx(101.0)
    finally:
        viewer.close()
        viewer.deleteLater()


def test_no_tie_strips_in_a_local_section(store_with_model, tmp_path):
    st, p, _ = store_with_model
    b = _add_b(st, tmp_path)
    provider = SectionDataProvider(st)
    provider.context_source = lambda profile: ContextItems()
    assert [t.other_id for t in provider.snapshot(p.id).context.ties] == [b.id]
    _local(st, p)
    provider.notify_changed()
    assert provider.is_local(p.id)
    assert provider.snapshot(p.id).context.ties == []
    assert provider.snapshot(b.id).context.ties == []           # nor drawn on the other one


def test_piece_saves_on_a_local_section_place_nothing(qgis_app, store_with_model, make_dock,
                                                      monkeypatch):
    st, p, _ = store_with_model
    _local(st, p)
    dock = make_dock(st)
    dock.open_profile(p.id)
    _visible(qgis_app, dock)
    calls = []
    real = dock.provider._placed
    monkeypatch.setattr(dock.provider, "_placed",
                        lambda *args: calls.append(1) or real(*args))
    dock.interp._mark_local(p.id)                 # the surface worked out for drawing
    assert st.profile(p.id).metadata.get("local_pieces") is True and calls == []
    monkeypatch.setattr(dock.provider, "surface",
                        lambda pid: pytest.fail("surface asked again"))
    dock.interp._mark_local(p.id)                 # already marked: returns at once
