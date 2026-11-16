"""Opening the borehole viewer: a click on a section column, or on a borehole on the map."""
import pytest

from test_dock import _map_event
from test_interp_tools import dock  # noqa: F401


def _release():
    from qgis.PyQt.QtCore import QEvent
    return QEvent.Type.MouseButtonRelease


def _bh(s=5.0, offset=1.5, label="RK1", entry=0):
    from groundwork_geophysics.core.context import LogInterval, ProjectedPoint
    return ProjectedPoint(s, offset, label, "borehole", 0.0,
                          [LogInterval(0.0, 1.0, "peat"), LogInterval(1.0, 3.0, "sand")],
                          entry=entry)


@pytest.fixture
def flushed(qgis_app):
    """Run the deferred deletes of earlier tests' docks first (as the ``dock`` fixture does):
    their canvases still follow QgsProject.instance() until then."""
    from qgis.PyQt.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qgis_app.processEvents()


def _visible(qgis_app, dock):
    dock.fit.user_navigated()
    dock.canvas.setVisiblePlotRange(0.0, 20.0, -10.0, 5.0)
    qgis_app.processEvents()


def test_pan_click_on_column_emits_borehole_clicked(qgis_app, dock):
    from groundwork_geophysics.core.context import ContextItems
    _visible(qgis_app, dock)
    dock._ctx = (ContextItems(points=[_bh()]), None)
    got = []
    dock.borehole_clicked.connect(lambda e, label: got.append((e, label)))
    dock.handle_click(5.0, -2.0, None)
    assert got == [(0, "RK1")]
    assert dock.details_popup is None or not dock.details_popup.isVisible()
    dock.handle_click(12.0, -2.0, None)                 # beside the column: nothing
    assert got == [(0, "RK1")]


def test_click_on_column_and_piece_keeps_details_with_open_line(qgis_app, dock):
    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.core.interpretation import InterpFeature, InterpPiece, new_id
    _visible(qgis_app, dock)
    dock._ctx = (ContextItems(points=[_bh()]), None)
    store = dock.provider.store
    store.ensure_interpretation()
    v = store.current_version()
    f = InterpFeature(new_id(), v.id, type="clay lens", name="C")
    store.save_feature(f)
    store.save_piece(InterpPiece(new_id(), v.id, f.id, dock.current_profile_id(), "polygon",
                                 [(3, 0), (8, 0), (8, -5), (3, -5)]))
    got = []
    dock.borehole_clicked.connect(lambda e, label: got.append((e, label)))
    dock.handle_click(5.0, -2.0, None)
    assert got == []
    popup = dock.details_popup
    assert popup is not None and popup.isVisible()
    assert "Interpretation C" in popup.text() and "Open in borehole viewer" in popup.text()
    popup.linkActivated.emit("open")
    assert got == [(0, "RK1")] and not popup.isVisible()


def test_map_click_near_current_profile_borehole_opens_viewer(qgis_app, flushed, store_with_model,
                                                             make_dock_and_link):
    from groundwork_geophysics.core.context import ContextItems
    st, p, _ = store_with_model
    dock, link = make_dock_and_link(st)
    dock.open_profile(p.id)
    dock.provider.context_source = lambda profile: ContextItems(
        points=[_bh(25.0, 0.0, "B7", 1)])
    got = []
    dock.borehole_clicked.connect(lambda e, label: got.append((e, label)))
    release = _release()
    link.tool.canvasReleaseEvent(_map_event(link.map_canvas, release, (25, 0), dy_px=3))
    assert got == [(1, "B7")]
    # far from the borehole, near the line: a profile pick as before, no viewer
    link.tool.canvasReleaseEvent(_map_event(link.map_canvas, release, (40, 0), dy_px=3))
    assert got == [(1, "B7")] and dock.current_profile_id() == p.id


def test_map_click_without_open_profile_picks_profile_as_today(qgis_app, flushed, store_with_model,
                                                                make_dock_and_link):
    st, p, _ = store_with_model
    dock, link = make_dock_and_link(st)
    got = []
    dock.borehole_clicked.connect(lambda e, label: got.append((e, label)))
    link.tool.canvasReleaseEvent(_map_event(link.map_canvas, _release(),
                                            (25, 0), dy_px=3))
    assert got == [] and dock.current_profile_id() == p.id


def test_plugin_opens_one_viewer_and_closes_it_on_unload(qgis_app, flushed, fake_iface,
                                                         store_with_model):
    from groundwork_geophysics import classFactory
    st, p, _ = store_with_model
    plugin = classFactory(fake_iface)
    plugin.initGui()
    try:
        plugin.set_store(st)
        plugin.dock.open_profile(p.id)
        plugin.dock.borehole_clicked.emit(0, "RK1")
        viewer = plugin.borehole_viewer
        assert viewer is not None and viewer.isVisible() and viewer.highlight == (0, "RK1")
        plugin.dock.borehole_clicked.emit(0, "RK2")
        assert plugin.borehole_viewer is viewer and viewer.highlight == (0, "RK2")
    finally:
        plugin.unload()
        # run the viewer's and dock's deferred deletes now, as QGIS's event loop would,
        # not in the middle of a later test
        from qgis.PyQt.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()
    assert plugin.borehole_viewer is None



def test_new_store_closes_the_viewer(qgis_app, flushed, fake_iface, store_with_model, tmp_path):
    """I5: switching the workbench store (New/Open workbench project) closes the viewer."""
    from groundwork_geophysics import classFactory
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    st, p, _ = store_with_model
    plugin = classFactory(fake_iface)
    plugin.initGui()
    try:
        plugin.set_store(st)
        plugin.dock.open_profile(p.id)
        plugin.dock.borehole_clicked.emit(0, "RK1")
        assert plugin.borehole_viewer is not None
        plugin.set_store(ProjectStore.create(tmp_path / "other.gpkg", "EPSG:25832"))
        assert plugin.borehole_viewer is None
    finally:
        plugin.unload()
        from qgis.PyQt.QtCore import QCoreApplication, QEvent
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()


def test_details_popup_goes_away(qgis_app, dock):
    """M7: the "Open in borehole viewer" popup hides on the next click and when the
    profile closes."""
    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.core.interpretation import InterpFeature, InterpPiece, new_id
    _visible(qgis_app, dock)
    dock._ctx = (ContextItems(points=[_bh()]), None)
    store = dock.provider.store
    store.ensure_interpretation()
    v = store.current_version()
    f = InterpFeature(new_id(), v.id, type="lens", name="L")
    store.save_feature(f)
    store.save_piece(InterpPiece(new_id(), v.id, f.id, dock.current_profile_id(), "polygon",
                                 [(3, 0), (8, 0), (8, -5), (3, -5)]))
    dock.handle_click(5.0, -2.0, None)
    assert dock.details_popup.isVisible()
    dock.handle_click(15.0, -2.0, None)                 # a click elsewhere
    assert not dock.details_popup.isVisible()
    dock.handle_click(5.0, -2.0, None)
    assert dock.details_popup.isVisible()
    dock._close_profile()
    assert not dock.details_popup.isVisible()
