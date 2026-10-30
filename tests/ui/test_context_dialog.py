import pytest

from geophysics_workbench.core.context_settings import ContextSettings


def _tif(path):
    from osgeo import gdal
    ds = gdal.GetDriverByName("GTiff").Create(str(path), 2, 2, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((0, 1, 0, 2, 0, -1))
    ds.GetRasterBand(1).Fill(1.0)
    ds = None


def test_dialog_lists_layers_by_type_and_writes_entry(qgis_app, fake_iface, tmp_path):
    from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer

    from geophysics_workbench.ui.context_dialog import ContextDialog, read_settings

    prj = QgsProject()
    line = QgsVectorLayer("LineString?crs=EPSG:25832&field=name:string", "Powerline (OSM)", "memory")
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
    assert set(dlg.line_rows) == {line.id(), other.id()}
    assert set(dlg.point_rows) == {pts.id()}
    assert dlg.line_rows[line.id()].powerline.isChecked()
    assert not dlg.line_rows[other.id()].powerline.isChecked()
    dlg.line_rows[line.id()].check.setChecked(True)
    dlg.point_rows[pts.id()].check.setChecked(True)
    dlg.select_band(poly.id(), "unit")
    dlg.select_dem(dem.id())
    dlg.borehole.set_layer(pts.id())
    dlg.borehole.set_log_layer(table.id())
    dlg.buffer_spin.setValue(30)
    dlg.accept()

    got = read_settings(prj)
    assert [(s.layer_id, s.powerline) for s in got.line_layers] == [(line.id(), True)]
    assert [s.layer_id for s in got.point_layers] == [pts.id()]
    assert got.band.layer_id == poly.id() and got.band.label_field == "unit"
    assert got.dem_layer_id == dem.id()
    assert got.borehole.layer_id == pts.id() and got.borehole.log_layer_id == table.id()
    assert got.buffer == 30.0 and got.near_miss == 10.0 and got.dem_tolerance == 1.0
    assert dlg.settings() == got


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
