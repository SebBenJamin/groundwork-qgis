import numpy as np
import pytest


def _profile_point(s, z):
    from qgis.core import QgsProfilePoint
    return QgsProfilePoint(float(s), float(z))


def _send_mouse(widget, etype, pos):
    from qgis.core import QgsApplication
    from qgis.PyQt.QtCore import QPointF, Qt
    from qgis.PyQt.QtGui import QMouseEvent

    pos = QPointF(pos)
    ev = QMouseEvent(etype, pos, QPointF(widget.mapToGlobal(pos.toPoint())),
                     Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier)
    QgsApplication.sendEvent(widget, ev)


def _map_event(map_canvas, etype, xy, dy_px=0.0):
    """QgsMapMouseEvent at map coordinate ``xy`` shifted ``dy_px`` pixels down."""
    from qgis.core import QgsPointXY
    from qgis.gui import QgsMapMouseEvent
    from qgis.PyQt.QtCore import QPoint, Qt

    px = map_canvas.getCoordinateTransform().transform(QgsPointXY(*map(float, xy)))
    button = Qt.MouseButton.LeftButton if etype.name != "MouseMove" else Qt.MouseButton.NoButton
    return QgsMapMouseEvent(map_canvas, etype, QPoint(round(px.x()), round(px.y() + dy_px)),
                            button)


def _wait_generated(qgis_app, dock, timeout_s=30.0):
    """Spin the event loop until the canvas has had no active job for 300 ms (the count
    can bounce 1 -> 0 -> 1 after a refresh, so one transition is not enough)."""
    import time

    from qgis.PyQt.QtCore import QEventLoop, QTimer

    state = {"since": None}
    loop, timer = QEventLoop(), QTimer()
    deadline = time.perf_counter() + timeout_s

    def check():
        now = time.perf_counter()
        state["since"] = None if dock.is_busy() else (state["since"] or now)
        if (state["since"] and now - state["since"] > 0.3) or now > deadline:
            loop.quit()

    timer.timeout.connect(check)
    timer.start(5)
    loop.exec()
    timer.stop()
    assert time.perf_counter() <= deadline, "profile generation did not finish"


def _registered_ids():
    from qgis.core import QgsApplication
    return [s.profileSourceId() for s in QgsApplication.profileSourceRegistry().profileSources()]


def _markers(map_canvas):
    from qgis.gui import QgsVertexMarker
    return [i for i in map_canvas.scene().items() if isinstance(i, QgsVertexMarker)]


# -- brief tests ---------------------------------------------------------------------------
def test_open_profile_sets_curve_and_combo(qgis_app, store_with_model, make_dock):
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    assert dock.current_profile_id() == p.id
    assert dock.canvas.profileCurve().length() == pytest.approx(p.chainage.length)
    assert dock.profile_combo.currentText() == "P1"
    assert dock.objectName() == "GeophysicsWorkbenchSectionDock"


def test_cursor_moves_map_marker(qgis_app, store_with_model, make_dock_and_link):
    st, p, _ = store_with_model
    dock, link = make_dock_and_link(st)
    dock.open_profile(p.id)
    dock.cursor_moved.emit(25.0, 100.0)
    c = link.marker.center()
    assert (c.x(), c.y()) == pytest.approx(tuple(p.chainage.to_xy(25.0)))
    assert link.marker.isVisible()
    dock.cursor_left.emit()
    assert not link.marker.isVisible()


def test_hiding_layer_triggers_refresh(qgis_app, store_with_model, make_dock):
    st, p, _ = store_with_model
    dock = make_dock(st); dock.open_profile(p.id)
    ds_id = st.datasets(p.id)[0].id
    changed = []
    dock.layer_list.style_changed.connect(changed.append)
    dock.layer_list.set_visible(ds_id, False)
    assert dock.provider.style(ds_id).visible is False
    assert changed == [ds_id]


# -- dock behaviour ------------------------------------------------------------------------
def test_open_profile_zooms_to_data_and_topography_with_exaggeration(qgis_app, store_with_model,
                                                                     make_dock):
    st, p, _ = store_with_model
    dock = make_dock(st)
    assert dock.ve_spin.value() == 2 and dock.ve_spin.minimum() == 1 and dock.ve_spin.maximum() == 20
    dock.open_profile(p.id)
    d, e = dock.canvas.visibleDistanceRange(), dock.canvas.visibleElevationRange()
    assert d.lower() <= 0 and d.upper() >= p.chainage.length          # whole profile
    assert e.lower() <= -5 and e.upper() >= 102                        # mesh and topography
    assert dock.canvas.axisScaleRatio() == pytest.approx(2, rel=0.02)
    dock.ve_spin.setValue(5)
    assert dock.canvas.axisScaleRatio() == pytest.approx(5, rel=0.02)
    e = dock.canvas.visibleElevationRange()
    assert e.lower() <= -5 and e.upper() >= 102                        # still fits

    # the canvas zooms itself when its first generation finishes: the fit must survive
    _wait_generated(qgis_app, dock)
    d, e = dock.canvas.visibleDistanceRange(), dock.canvas.visibleElevationRange()
    assert d.lower() <= 0 and d.upper() >= p.chainage.length
    assert e.lower() <= -5 and e.upper() >= 102
    assert dock.canvas.axisScaleRatio() == pytest.approx(5, rel=0.02)


def test_user_zoom_is_kept_after_refresh(qgis_app, store_with_model, make_dock):
    from qgis.PyQt.QtCore import QEvent, QPointF

    st, p, _ = store_with_model
    dock = make_dock(st); dock.open_profile(p.id)
    _wait_generated(qgis_app, dock)
    vp = dock.canvas.viewport()
    _send_mouse(vp, QEvent.Type.MouseButtonPress, QPointF(100, 100))   # user starts navigating
    _send_mouse(vp, QEvent.Type.MouseButtonRelease, QPointF(100, 100))
    dock.canvas.setVisiblePlotRange(0, 10, -6, 0)
    view = (dock.canvas.visibleDistanceRange().lower(), dock.canvas.visibleDistanceRange().upper())
    dock.layer_list.set_opacity(st.datasets(p.id)[0].id, 0.5)
    _wait_generated(qgis_app, dock)
    d = dock.canvas.visibleDistanceRange()
    assert (d.lower(), d.upper()) == pytest.approx(view)


def test_hover_emits_cursor_and_fills_readout(qgis_app, store_with_model, make_dock):
    from qgis.PyQt.QtCore import QEvent, QPointF

    st, p, _ = store_with_model
    dock = make_dock(st); dock.open_profile(p.id)
    dock.canvas.setVisiblePlotRange(0, 10, -6, 0.5)
    moved, left = [], []
    dock.cursor_moved.connect(lambda s, z: moved.append((s, z)))
    dock.cursor_left.connect(lambda: left.append(1))
    pt = dock.canvas.plotPointToCanvasPoint(_profile_point(5.0, -2.0))
    _send_mouse(dock.canvas.viewport(), QEvent.Type.MouseMove, QPointF(pt.x(), pt.y()))
    assert moved and moved[-1] == pytest.approx((5.0, -2.0), abs=0.3)
    text = dock.readout.text()
    expected = dock.provider.identify(p.id, *moved[-1])[0]["value"]
    value = f"{expected:.0f}" if expected >= 100 else f"{expected:.1f}"
    assert text.startswith("s = 5.") and "depth = " in text and " X " in text
    assert f"P1 model: {value} Ω·m" in text
    from qgis.core import QgsApplication
    QgsApplication.sendEvent(dock.canvas.viewport(), QEvent(QEvent.Type.Leave))
    assert left == [1]


def test_show_cursor_draws_and_hides_guide_line(qgis_app, store_with_model, make_dock):
    st, p, _ = store_with_model
    dock = make_dock(st); dock.open_profile(p.id)
    for view in (None, (20, 30, -4, -1)):                  # full extent; zoomed below z = 0
        if view:
            dock.canvas.setVisiblePlotRange(*view)
        dock.show_cursor(25.0)
        line = dock.guide_line
        assert line.isVisible() and line.scene() is dock.canvas.scene()
        e = dock.canvas.visibleElevationRange()
        x = dock.canvas.plotPointToCanvasPoint(_profile_point(25.0, e.lower() + 0.1)).x()
        assert x > 10 and line.line().x1() == pytest.approx(x, abs=1) == line.line().x2()
        assert "s = 25.0 m" in dock.readout.text()
    dock.show_cursor(None)
    assert not line.isVisible()


def test_layer_errors_shown_in_red(qgis_app, store_with_model, make_dock):
    st, p, src = store_with_model
    src.unlink()
    dock = make_dock(st); dock.open_profile(p.id)
    assert "P1 model: source missing" in dock.errors.text()
    assert "red" in dock.errors.styleSheet() or "#" in dock.errors.styleSheet()
    assert not dock.errors.isHidden()


def test_scale_dialog_auto_apply_and_validation(qgis_app, store_with_model, make_dock):
    from geophysics_workbench.core.colors import COLORMAPS, ColorScale
    from geophysics_workbench.section.scale_dialog import ColorScaleDialog

    st, p, _ = store_with_model
    dock = make_dock(st); dock.open_profile(p.id)
    ds_id = st.datasets(p.id)[0].id
    [layer] = dock.provider.layers(p.id)
    dlg = ColorScaleDialog(ColorScale("viridis", 1, 10, True), layer.mesh.values, "Ω·m")
    assert [dlg.cmap_combo.itemText(i) for i in range(dlg.cmap_combo.count())] == COLORMAPS
    applied = []
    dlg.applied.connect(applied.append)
    dlg.auto()
    expected = ColorScale.auto(layer.mesh.values, log=True, cmap="viridis")
    assert dlg.min_spin.value() == pytest.approx(expected.vmin, abs=1e-3)
    assert dlg.apply() and applied[-1].cmap == "viridis" and applied[-1].log
    assert dlg.min_spin.minimum() > 0                              # log: positive only
    dlg.log_check.setChecked(False)
    dlg.min_spin.setValue(-5)
    dlg.max_spin.setValue(-10)
    assert not dlg.apply() and len(applied) == 1 and not dlg.message.isHidden()
    dlg.deleteLater()

    dock.layer_list.set_scale(ds_id, ColorScale("gray", 50, 500, False))
    assert dock.provider.style(ds_id).scale == ColorScale("gray", 50, 500, False)


def test_readout_format():
    from geophysics_workbench.section.readout import format_readout

    hits = [{"name": "P1 model", "value": 27.31, "unit": "ohm.m"},
            {"name": "P1 it2", "value": 1234.6, "unit": "ohm.m"},
            {"name": "IP", "value": 3.0, "unit": "mV/V"}]
    assert format_readout(123.44, 61.2, 3.8, (432105.21, 5851234.94), hits) == (
        "s = 123.4 m · z = 61.2 m · depth = 3.8 m · X 432105.2 Y 5851234.9 · "
        "P1 model: 27.3 Ω·m · P1 it2: 1235 Ω·m · IP: 3.0 mV/V")
    assert format_readout(5.0, 1.0, None, None, []) == "s = 5.0 m · z = 1.0 m"


# -- map link ------------------------------------------------------------------------------
def test_pick_tool_opens_profile_and_links_cursor(qgis_app, store_with_model, make_dock_and_link):
    from qgis.PyQt.QtCore import QEvent

    st, p, _ = store_with_model
    dock, link = make_dock_and_link(st)
    canvas, tool = link.map_canvas, link.tool
    canvas.setMapTool(tool)
    release = QEvent.Type.MouseButtonRelease
    tool.canvasReleaseEvent(_map_event(canvas, release, (25, 0), dy_px=20))   # too far
    assert dock.current_profile_id() is None
    tool.canvasReleaseEvent(_map_event(canvas, release, (25, 0), dy_px=6))
    assert dock.current_profile_id() == p.id

    tool.canvasMoveEvent(_map_event(canvas, QEvent.Type.MouseMove, (20, 0), dy_px=25))
    assert dock.guide_line.isVisible()
    assert dock.cursor_chainage() == pytest.approx(20.0, abs=0.5)
    tool.canvasMoveEvent(_map_event(canvas, QEvent.Type.MouseMove, (20, 0), dy_px=40))
    assert not dock.guide_line.isVisible() and dock.cursor_chainage() is None
    canvas.unsetMapTool(tool)


def test_map_link_transforms_between_store_and_map_crs(qgis_app, store_with_model,
                                                       make_dock_and_link):
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY,
                           QgsProject, QgsRectangle)
    from qgis.PyQt.QtCore import QEvent

    st, p, _ = store_with_model
    dock, link = make_dock_and_link(st)
    canvas = link.map_canvas
    map_crs = QgsCoordinateReferenceSystem("EPSG:3857")
    canvas.setDestinationCrs(map_crs)
    to_map = QgsCoordinateTransform(QgsCoordinateReferenceSystem(st.crs_authid), map_crs,
                                    QgsProject.instance())
    a, b = (to_map.transform(QgsPointXY(*map(float, xy))) for xy in p.xy[[0, -1]])
    pad = 0.5 * abs(b.x() - a.x())
    canvas.setExtent(QgsRectangle(a.x() - pad, a.y() - 3 * pad, b.x() + pad, b.y() + 3 * pad))
    canvas.refresh()
    mid = to_map.transform(QgsPointXY(25.0, 0.0))
    link.tool.canvasReleaseEvent(_map_event(canvas, QEvent.Type.MouseButtonRelease,
                                            (mid.x(), mid.y()), dy_px=6))
    assert dock.current_profile_id() == p.id
    dock.cursor_moved.emit(25.0, -2.0)
    c = link.marker.center()
    assert (c.x(), c.y()) == pytest.approx((mid.x(), mid.y()), abs=1e-3)


# -- plugin --------------------------------------------------------------------------------
def test_plugin_reload_leaves_no_dock_marker_tool_or_source(qgis_app, store_with_model, fake_iface):
    from qgis.PyQt.QtCore import QCoreApplication, QEvent
    from qgis.PyQt.QtWidgets import QDockWidget

    from geophysics_workbench.plugin import WorkbenchPlugin
    from geophysics_workbench.section.profile_source import SOURCE_ID

    st, p, _ = store_with_model
    window, map_canvas = fake_iface.mainWindow(), fake_iface.mapCanvas()
    for _ in range(2):
        plugin = WorkbenchPlugin(fake_iface)
        plugin.initGui()
        texts = [a.text() for a in plugin.menu.actions()]
        assert "Show section panel" in texts and "Pick profile on map" in texts
        plugin.set_store(st)
        assert _registered_ids().count(SOURCE_ID) == 1
        assert plugin.dock.canvas.sources() == [plugin.source]
        plugin.set_store(st)                                   # replacing keeps one source
        assert _registered_ids().count(SOURCE_ID) == 1
        assert plugin.dock.canvas.sources() == [plugin.source]
        plugin.pick_action.trigger()
        assert map_canvas.mapTool() is plugin.map_link.tool
        plugin.show_section_panel()
        assert plugin.dock.isVisible()
        plugin.dock.open_profile(p.id)
        plugin.dock.cursor_moved.emit(10.0, 0.0)
        assert len(_markers(map_canvas)) == 1

        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()
        assert SOURCE_ID not in _registered_ids()
        assert _markers(map_canvas) == []
        assert map_canvas.mapTool() is None
        assert window.findChildren(QDockWidget, "GeophysicsWorkbenchSectionDock") == []


def test_set_store_none_tears_down(qgis_app, store_with_model, fake_iface):
    from geophysics_workbench.plugin import WorkbenchPlugin
    from geophysics_workbench.section.profile_source import SOURCE_ID

    st, p, _ = store_with_model
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.set_store(st)
        plugin.dock.open_profile(p.id)
        plugin.set_store(None)
        assert plugin.provider is None and plugin.source is None
        assert SOURCE_ID not in _registered_ids()
        assert plugin.dock.canvas.sources() == [] and plugin.dock.current_profile_id() is None
    finally:
        plugin.unload()
