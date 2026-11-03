import pytest

from geophysics_workbench.core.context_settings import ContextSettings


def _tif(path):
    from osgeo import gdal
    with gdal.ExceptionMgr(useExceptions=True):         # scoped: no global GDAL state
        ds = gdal.GetDriverByName("GTiff").Create(str(path), 2, 2, 1, gdal.GDT_Float32)
        ds.SetGeoTransform((0, 1, 0, 2, 0, -1))
        ds.GetRasterBand(1).Fill(1.0)
        ds = None


def test_dialog_lists_layers_by_type_and_writes_entry(qgis_app, fake_iface, tmp_path):
    from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

    from geophysics_workbench.core.context_settings import LineLayerSetting
    from geophysics_workbench.ui.context_dialog import ContextDialog, read_settings

    prj = QgsProject()
    line = QgsVectorLayer("LineString?crs=EPSG:25832&field=name:string", "Lines (OSM)", "memory")
    other = QgsVectorLayer("LineString?crs=EPSG:25832&field=name:string", "Roads", "memory")
    pts = QgsVectorLayer("Point?crs=EPSG:25832&field=name:string", "Pipes", "memory")
    poly = QgsVectorLayer("Polygon?crs=EPSG:25832&field=unit:string", "Geology", "memory")
    table = QgsVectorLayer("None?field=hole:string&field=top:double", "Logs", "memory")
    tif = tmp_path / "dem.tif"
    _tif(tif)
    dem = QgsRasterLayer(str(tif), "DEM")
    assert dem.isValid() and table.isValid()
    for lyr in (line, other, pts, poly, table, dem):
        prj.addMapLayer(lyr)

    dlg = ContextDialog(fake_iface, prj)
    assert set(dlg.lines.rows) == {line.id(), other.id()}
    assert set(dlg.point_rows) == {pts.id()}
    dlg.lines.rows[line.id()].label.setCurrentIndex(
        dlg.lines.rows[line.id()].label.findData("name"))
    dlg.point_rows[pts.id()].check.setChecked(True)
    dlg.select_band(poly.id(), "unit")
    dlg.select_dem(dem.id())
    dlg.borehole.set_layer(pts.id())
    dlg.borehole.set_log_layer(table.id())
    dlg.buffer_spin.setValue(30)
    dlg.accept()

    got = read_settings(prj)
    assert got.line_layers == [LineLayerSetting(line.id(), "name"), LineLayerSetting(other.id())]
    assert [s.layer_id for s in got.point_layers] == [pts.id()]
    assert got.band.layer_id == poly.id() and got.band.label_field == "unit"
    assert got.dem_layer_id == dem.id()
    assert got.borehole.layer_id == pts.id() and got.borehole.log_layer_id == table.id()
    assert got.buffer == 30.0 and got.near_miss == 10.0 and got.dem_tolerance == 1.0
    assert dlg.settings() == got


@pytest.fixture
def project(qgis_app):
    from qgis.core import QgsProject
    # QgsProject() kept alive in a fixture cache crashes QgsApplication.exitQgis
    proj = QgsProject.instance()
    proj.clear()
    yield proj
    proj.removeAllMapLayers()
    proj.clear()


def _line(project, name):
    from qgis.core import QgsVectorLayer
    layer = QgsVectorLayer("LineString?crs=EPSG:25832&field=name:string", name, "memory")
    project.addMapLayer(layer)
    return layer


def _red(layer):
    from qgis.core import QgsLineSymbol, QgsSingleSymbolRenderer
    from qgis.PyQt.QtGui import QColor
    symbol = QgsLineSymbol.createSimple({})
    symbol.setColor(QColor(220, 0, 0))
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))


def test_visible_rows_start_ticked_and_follow_the_map(project, fake_iface):
    from geophysics_workbench.ui.context_dialog import ContextDialog

    a, b = _line(project, "A"), _line(project, "B")
    node_b = project.layerTreeRoot().findLayer(b.id())
    node_b.setItemVisibilityChecked(False)
    dlg = ContextDialog(fake_iface, project)
    try:
        rows = dlg.lines.rows
        assert rows[a.id()].check.isChecked() and not rows[b.id()].check.isChecked()
        node_b.setItemVisibilityChecked(True)
        assert rows[b.id()].check.isChecked()
        rows[b.id()].check.click()                      # the user's tick: B is now explicit
        assert rows[b.id()].explicit and not rows[b.id()].check.isChecked()
        node_b.setItemVisibilityChecked(False)
        node_b.setItemVisibilityChecked(True)
        assert not rows[b.id()].check.isChecked()
        assert {s.layer_id: s.checked for s in dlg.lines.settings()} == {a.id(): None,
                                                                         b.id(): False}
    finally:
        dlg.reject()


def test_excluded_layers_not_listed(project, fake_iface):
    from qgis.core import QgsVectorLayer

    from geophysics_workbench.ui.context_dialog import ContextDialog

    line = _line(project, "Own profiles")
    pts = QgsVectorLayer("Point?crs=EPSG:25832&field=name:string", "Own stations", "memory")
    project.addMapLayer(pts)
    dlg = ContextDialog(fake_iface, project, exclude={line.id(), pts.id()})
    try:
        assert line.id() not in dlg.lines.rows
        assert pts.id() not in dlg.point_rows
    finally:
        dlg.reject()


def test_row_colour_and_selection_saved(project, fake_iface):
    from qgis.PyQt.QtGui import QColor

    from geophysics_workbench.core.context_settings import LineLayerSetting
    from geophysics_workbench.ui.context_dialog import ContextDialog, read_settings

    lines = _line(project, "Red")
    _red(lines)
    dlg = ContextDialog(fake_iface, project)
    row = dlg.lines.rows[lines.id()]
    assert row.colour.color().name() == "#dc0000"
    assert row.setting().colour == ""
    row.colour.setColor(QColor("#0000ff"))
    row.selected_only.click()
    dlg.accept()
    assert read_settings(project).line_layers == [
        LineLayerSetting(lines.id(), colour="#0000ff", selected_only=True)]

    dlg = ContextDialog(fake_iface, project)
    try:
        row = dlg.lines.rows[lines.id()]
        assert row.colour.color().name() == "#0000ff"
        assert row.selected_only.isChecked()
    finally:
        dlg.reject()


def test_layer_added_and_removed_while_open(project, fake_iface):
    from geophysics_workbench.ui.context_dialog import ContextDialog, read_settings

    a, b = _line(project, "A").id(), _line(project, "B").id()
    dlg = ContextDialog(fake_iface, project)
    try:
        c = _line(project, "C").id()
        assert dlg.lines.rows[c].check.isChecked()
        dlg.lines.rows[a].check.click()                 # explicit: unticked
        project.removeMapLayer(a)
        assert a not in dlg.lines.rows and dlg.lines.stale_count() == 1
        project.removeMapLayer(b)                       # automatic: dropped entirely
        assert b not in dlg.lines.rows and dlg.lines.stale_count() == 1
        dlg.apply()
        assert [(s.layer_id, s.checked) for s in read_settings(project).line_layers] == [
            (c, None), (a, False)]
    finally:
        dlg.reject()


def test_apply_writes_and_stays_open(project, fake_iface):
    from geophysics_workbench.ui.context_dialog import ContextDialog, read_settings

    dlg = ContextDialog(fake_iface, project)
    fired = []
    dlg.applied.connect(lambda: fired.append(True))
    dlg.show()
    try:
        dlg.buffer_spin.setValue(40)
        dlg.apply_button.click()
        assert read_settings(project).buffer == 40.0
        assert fired == [True]
        assert dlg.isVisible()
        dlg.buffer_spin.setValue(50)
    finally:
        dlg.reject()
    assert read_settings(project).buffer == 40.0
    assert fired == [True]


def test_read_settings_empty_project(qgis_app):
    from qgis.core import QgsProject

    from geophysics_workbench.ui.context_dialog import read_settings
    assert read_settings(QgsProject()) == ContextSettings()


def test_menu_action_enabled_only_with_store(qgis_app, fake_iface, store_with_model):
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench.plugin import WorkbenchPlugin

    store = store_with_model[0]
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        assert plugin.context_action.text() == "Context layers…"
        plugin.set_store(None)
        assert not plugin.context_action.isEnabled()
        plugin.set_store(store)
        assert plugin.context_action.isEnabled()
    finally:
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()


def test_missing_layers_keep_their_settings(qgis_app, fake_iface):
    from qgis.core import QgsProject

    from geophysics_workbench.core.context_settings import (BandSetting, BoreholeSetting,
                                                            LineLayerSetting)
    from geophysics_workbench.ui.context_dialog import (ContextDialog, read_settings,
                                                        write_settings)

    prj = QgsProject()
    saved = ContextSettings(line_layers=[LineLayerSetting("gone_line", "name", checked=True)],
                            borehole=BoreholeSetting("gone_bh", "id", "z", "gone_log", "hid",
                                                     "t", "b", "lith"),
                            band=BandSetting("gone_band", "unit"), dem_layer_id="gone_dem")
    write_settings(prj, saved)
    dlg = ContextDialog(fake_iface, prj)
    assert "4" in dlg.note.text() or "5" in dlg.note.text()
    dlg.accept()
    assert read_settings(prj) == saved

    dlg = ContextDialog(fake_iface, prj)
    dlg.select_dem("")                                   # the user picks "None"
    dlg.accept()
    got = read_settings(prj)
    assert got.dem_layer_id == ""
    assert got.line_layers == saved.line_layers and got.borehole == saved.borehole
    assert got.band == saved.band


def test_context_dialog_is_non_modal_and_apply_redraws(qgis_app, fake_iface, store_with_model):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench.plugin import WorkbenchPlugin
    from geophysics_workbench.section.crossing_lines import own_layer_ids
    from geophysics_workbench.ui.project_actions import add_store_layers

    store = store_with_model[0]
    project = QgsProject.instance()
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        add_store_layers(store, project)
        plugin.set_store(store)
        plugin.edit_context()
        dlg = plugin._context_dialog
        assert dlg.isVisible() and not dlg.isModal()
        plugin.edit_context()
        assert plugin._context_dialog is dlg
        own = own_layer_ids(store, project)
        assert own and not own & set(dlg.lines.rows) and not own & set(dlg.point_rows)
        calls = []
        plugin.provider.on_change.append(lambda: calls.append(1))
        dlg.near_miss_spin.setValue(20)
        dlg.apply_button.click()
        assert plugin.provider.near_miss == 20
        assert calls == [1]
        assert dlg.isVisible()
        plugin.set_store(None)
        assert plugin._context_dialog is None
    finally:
        plugin.unload()
        project.removeAllMapLayers()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()
