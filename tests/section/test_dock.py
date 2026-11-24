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


def test_zoom_map_button_zooms_map_to_open_profile(qgis_app, store_with_model,
                                                  make_dock_and_link):
    st, p, _ = store_with_model                 # the line runs (0, 0) -> (50, 0)
    dock, link = make_dock_and_link(st)
    assert not dock.zoom_map_button.isEnabled()         # no profile open yet
    assert "open a profile" in dock.zoom_map_button.toolTip().lower()
    link.map_canvas.setExtent(link.map_canvas.extent().buffered(5000))   # far out
    dock.open_profile(p.id)
    assert dock.zoom_map_button.isEnabled()
    dock.zoom_map_button.click()
    e = link.map_canvas.extent()
    assert e.xMinimum() < 0 and e.xMaximum() > 50       # the whole line, with a margin
    assert e.xMinimum() > -50 and e.xMaximum() < 100    # zoomed in, not left far out
    assert e.yMinimum() < 0 < e.yMaximum()


def test_profile_menu_offers_zoom_map(qgis_app, store_with_model, make_dock):
    from groundwork_geophysics.section.dock import ZOOM_MAP_TEXT
    st, p, _ = store_with_model
    dock = make_dock(st)
    menu = dock.profile_menu()
    [entry] = [a for a in menu.actions() if a.text() == ZOOM_MAP_TEXT]
    assert not entry.isEnabled()
    dock.open_profile(p.id)
    got = []
    dock.zoom_map_requested.connect(got.append)
    menu = dock.profile_menu()
    [entry] = [a for a in menu.actions() if a.text() == ZOOM_MAP_TEXT]
    entry.trigger()
    assert got == [p.id]


def _second_profile(st, name="P2"):
    from groundwork_geophysics.core.model import profile_from_stations
    p2, s2 = profile_from_stations(name, st.crs_authid,
                                   np.array([[0, 10, 100], [50, 10, 101.0]]))
    st.save_profile(p2)
    st.save_station_set(s2)
    return p2


def test_previous_and_next_step_through_the_profiles(qgis_app, store_with_model, make_dock):
    st, p, _ = store_with_model
    p2 = _second_profile(st)
    dock = make_dock(st)
    order = [dock.profile_combo.itemData(i) for i in range(1, dock.profile_combo.count())]
    assert set(order) == {p.id, p2.id}
    assert dock.next_button.isEnabled()                 # nothing open: Next opens the first
    dock.next_button.click()
    assert dock.current_profile_id() == order[0]
    assert not dock.previous_button.isEnabled()         # the first: nothing before it
    dock.next_button.click()
    assert dock.current_profile_id() == order[1]
    assert not dock.next_button.isEnabled()             # the last: nothing after it
    assert "last" in dock.next_button.toolTip().lower()
    dock.previous_button.click()
    assert dock.current_profile_id() == order[0]


def test_page_keys_step_through_the_profiles(qgis_app, store_with_model, make_dock):
    st, p, _ = store_with_model
    _second_profile(st)
    dock = make_dock(st)
    dock.open_profile(dock.profile_combo.itemData(1))
    assert dock.next_shortcut.key().toString() == "PgDown"
    assert dock.previous_shortcut.key().toString() == "PgUp"
    dock.next_shortcut.activated.emit()
    assert dock.current_profile_id() == dock.profile_combo.itemData(2)
    dock.previous_shortcut.activated.emit()
    assert dock.current_profile_id() == dock.profile_combo.itemData(1)


def test_section_image_copies_and_saves_the_section(qgis_app, store_with_model, make_dock,
                                                    tmp_path):
    from qgis.PyQt.QtGui import QImage
    from qgis.PyQt.QtWidgets import QApplication
    st, p, _ = store_with_model
    dock = make_dock(st)
    assert not dock.image_button.isEnabled()            # nothing open: nothing to copy
    dock.open_profile(p.id)
    _wait_generated(qgis_app, dock)
    assert dock.image_button.isEnabled()
    dock.copy_image()
    copied = QApplication.clipboard().image()
    assert not copied.isNull() and copied.width() >= dock.canvas.width() - 1
    assert "clipboard" in dock.readout.text()
    path = tmp_path / "P1 section"
    dock.save_image(str(path))                          # ".png" added
    saved = QImage(str(path) + ".png")
    assert not saved.isNull() and saved.size() == copied.size()
    assert "P1 section.png" in dock.readout.text()


def test_ve_box_shows_its_whole_auto_text_at_laptop_width(qgis_app, store_with_model,
                                                         make_dock):
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    dock.ve_spin.setSpecialValueText("Auto (12.5×)")
    dock.ve_spin.setValue(dock.ve_spin.minimum())
    dock.resize(1000, 420)                      # narrower than a 1280 px laptop panel
    qgis_app.processEvents()
    edit = dock.ve_spin.lineEdit()
    assert edit.width() >= edit.fontMetrics().horizontalAdvance("Auto (12.5×)")


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
    assert dock.ve_spin.value() == 0 and dock.ve_spin.specialValueText().startswith("Auto")
    assert dock.ve_spin.maximum() == 20
    dock.ve_spin.setValue(2.0)                  # a typed exaggeration is kept exactly
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
    assert "P1 model:" in dock.errors.text() and "file not found" in dock.errors.text()
    assert "red" in dock.errors.styleSheet() or "#" in dock.errors.styleSheet()
    assert not dock.errors.isHidden()


def test_scale_dialog_auto_apply_and_validation(qgis_app, store_with_model, make_dock):
    from groundwork_geophysics.core.colors import COLORMAPS, ColorScale
    from groundwork_geophysics.section.scale_dialog import ColorScaleDialog

    st, p, _ = store_with_model
    dock = make_dock(st); dock.open_profile(p.id)
    ds_id = st.datasets(p.id)[0].id
    [layer] = dock.provider.layers(p.id)
    dlg = ColorScaleDialog(ColorScale("viridis", 1, 10, True), layer.mesh.values, "Ω·m")
    assert dlg.ramp_button.colorRamp() is not None                    # QGIS colour ramps
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
    from groundwork_geophysics.section.readout import format_readout

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

    from groundwork_geophysics.plugin import WorkbenchPlugin
    from groundwork_geophysics.section.profile_source import SOURCE_ID

    st, p, _ = store_with_model
    window, map_canvas = fake_iface.mainWindow(), fake_iface.mapCanvas()
    for _ in range(2):
        plugin = WorkbenchPlugin(fake_iface)
        plugin.initGui()
        texts = [a.text() for a in plugin.menu.actions()]
        assert "Show Section Panel" in texts and "Pick Profile on Map" in texts
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
    from groundwork_geophysics.plugin import WorkbenchPlugin
    from groundwork_geophysics.section.profile_source import SOURCE_ID

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


def test_open_profile_makes_it_active_for_the_source(qgis_app, store_with_model, make_dock):
    """Identical geometry: the canvas draws the opened profile's data, not its twin's."""
    from qgis.core import QgsCoordinateReferenceSystem, QgsProfileRequest, QgsLineString, QgsPoint

    from groundwork_geophysics.core.model import Profile

    st, p, _ = store_with_model
    twin = Profile("twin", "A twin", p.xy.copy(), p.crs_authid)
    st.save_profile(twin)
    dock = make_dock(st)
    source = dock._source
    req = QgsProfileRequest(QgsLineString([QgsPoint(float(x), float(y)) for x, y in p.xy]))
    req.setCrs(QgsCoordinateReferenceSystem(st.crs_authid))
    for pid in (p.id, twin.id, p.id):
        dock.open_profile(pid)
        assert dock.provider.active_profile_id == pid
        gen = source.createProfileGenerator(req)
        assert gen._snapshot.profile_id == pid
    dock.set_provider(None)
    assert source.provider.active_profile_id is None


def test_open_missing_profile_shows_message_not_traceback(qgis_app, store_with_model, make_dock):
    """E.g. a profile deleted from the GeoPackage behind the plugin's back."""
    st, p, _ = store_with_model
    dock = make_dock(st)
    assert dock.open_profile("no-such-profile") is False
    assert dock.current_profile_id() is None
    assert "not found" in dock.readout.text()
    assert dock.profile_combo.currentIndex() == 0
    combo = dock.profile_combo
    assert [combo.itemData(i) for i in range(combo.count())] == [None, p.id]
    assert dock.open_profile(p.id) is True and dock.current_profile_id() == p.id


def test_format_value_keeps_small_values_visible():
    from groundwork_geophysics.section.readout import format_value

    assert format_value(0.0123) == "0.0123" and format_value(0.04) == "0.04"
    assert format_value(0.5) == "0.5" and format_value(-0.00456) == "-0.00456"
    assert format_value(0.0) == "0.0"
    assert format_value(27.34) == "27.3" and format_value(1234.6) == "1235"


def test_long_readout_never_resizes_the_canvas(qgis_app, store_with_model, make_dock):
    """Hovering a core, crossing or note made the readout longer; the label grew the
    panel's minimum width, the canvas shrank and the section seemed to zoom in."""
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    qgis_app.processEvents()
    before = (dock.canvas.width(), dock.canvas.height())
    dock.readout.setText("s = 5.0 m · " + " · ".join(f"Core EN-RK {i} (+2 m): SU5.2 silty, "
                                                    f"humic, calcareous" for i in range(40)))
    qgis_app.processEvents()
    assert (dock.canvas.width(), dock.canvas.height()) == before
    assert "EN-RK 39" in dock.readout.toolTip()                 # the full text on hover


def test_second_readout_line_never_resizes_the_canvas(qgis_app, store_with_model, make_dock):
    """Usability review 2, R2: hovering a borehole added a readout line, the canvas lost
    16 px and the section re-fitted (twitched)."""
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    dock.readout.setText("s = 5.0 m")
    qgis_app.processEvents()
    before = dock.canvas.height()
    dock.readout.setText("s = 5.0 m\nBorehole EN-RK 4 (0 m): 1.9–3.0 m SU2")
    qgis_app.processEvents()
    assert dock.canvas.height() == before


def _drawn_store(tmp_path, model="ert/f001_res.dat", reader="r2_res_dat"):
    import shutil

    from groundwork_geophysics.core.model import (Dataset, file_fingerprint,
                                                 profile_from_polyline)
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    from pathlib import Path
    FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
    st = ProjectStore.create(tmp_path / "d.gpkg", "EPSG:25832")
    p = profile_from_polyline("D", "EPSG:25832", np.array([[0.0, 0.0], [60.0, 0.0]]))
    st.save_profile(p)
    src = tmp_path / ("m" + model[-4:])
    shutil.copy(FIXTURES / model, src)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("d", p.id, "", "ert_model", str(src), mt, sha, reader,
                            {"z_kind": "elevation"}, {}, name="d"))
    return st, p


def test_info_line_names_the_kind(qgis_app, tmp_path, make_dock):
    st, p = _drawn_store(tmp_path)
    dock = make_dock(st)
    assert dock.info_text() == "" and dock.info.isHidden()
    dock.open_profile(p.id)
    assert dock.info_text().startswith("Electrodes guessed from the model")   # a capital
    assert not dock.info.isHidden()


def test_info_line_asks_for_positions_when_there_is_no_guess(qgis_app, tmp_path, make_dock):
    st, p = _drawn_store(tmp_path, "ert/f001_res.vtk", "vtk_legacy")
    dock = make_dock(st)
    dock.open_profile(p.id)
    assert ("No electrode positions: import them or type the spacing in Profile Properties"
            in dock.info_text())


def test_events_while_the_panel_is_taken_apart_are_ignored(qgis_app):
    """Reinstalling the plugin tears the old panel down while Qt still sends it events; its
    Python side may already have dropped the canvas then."""
    from qgis.PyQt.QtCore import QEvent, QObject

    from groundwork_geophysics.section.dock import SectionDock
    dock = SectionDock()
    canvas = dock.canvas
    del dock.canvas
    assert dock.eventFilter(QObject(), QEvent(QEvent.Type.Leave)) is False
    dock.canvas = canvas
    dock.deleteLater()
