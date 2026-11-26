"""Import LAS… in a borehole entry of Context Layers: files matched to boreholes, written as a
curve table in the Groundwork GeoPackage, and set up as the entry's curve table."""
import shutil
from pathlib import Path

import pytest

LAS = Path(__file__).resolve().parent.parent / "fixtures" / "las"


@pytest.fixture
def collars(qgis_app):
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer
    project = QgsProject.instance()
    project.clear()
    layer = QgsVectorLayer("Point?crs=EPSG:25832&field=bid:string", "Collars", "memory")
    feats = []
    for i, name in enumerate(["JW11", "JW12", "B7"]):
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(i * 10.0, 0.0)))
        f.setAttributes([name])
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    project.addMapLayer(layer)
    yield project, layer
    project.removeAllMapLayers()
    project.clear()


def test_the_dialog_matches_files_and_lists_what_is_ready(qgis_app, collars):
    from groundwork_geophysics.ui.las_import_dialog import (CHOOSE, READY, LasImportDialog)
    dlg = LasImportDialog([LAS / "bh1_feet.las", LAS / "wrapped_metres.las",
                           LAS / "no_name.las"], ["JW11", "JW12", "B7"])
    assert [dlg.borehole(r) for r in range(3)] == ["JW11", None, None]
    assert [dlg.status(r) for r in range(3)] == [READY, CHOOSE, CHOOSE]
    dlg.set_borehole(1, "B7")
    dlg.set_offset(0, 0.6)
    entries = dlg.entries()
    assert [(bid, round(off, 2)) for bid, _log, off in entries] == [("JW11", 0.6), ("B7", 0.0)]
    assert dlg.import_button.isEnabled()
    dlg.deleteLater()


def test_a_file_that_cannot_be_read_says_why(qgis_app, collars, tmp_path):
    from groundwork_geophysics.ui.las_import_dialog import LasImportDialog
    bad = tmp_path / "bad.las"
    bad.write_text("hello")
    dlg = LasImportDialog([bad], ["JW11"])
    assert "not a LAS file" in dlg.status(0)
    assert dlg.entries() == [] and not dlg.import_button.isEnabled()
    dlg.deleteLater()


def test_import_las_sets_up_the_entrys_curve_table(qgis_app, collars, tmp_path, monkeypatch):
    from qgis.PyQt.QtWidgets import QDialog, QFileDialog

    from groundwork_geophysics.ui import las_import_dialog
    from groundwork_geophysics.ui.borehole_mapping import BoreholeGroup
    project, layer = collars
    src = tmp_path / "JW11_logs.las"
    shutil.copy(LAS / "bh1_feet.las", src)
    gpkg = tmp_path / "site_groundwork.gpkg"
    group = BoreholeGroup(project, [layer], [layer], store_path=lambda: gpkg)
    group.set_layer(layer.id())
    group.id_combo.setCurrentIndex(group.id_combo.findData("bid"))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: ([str(src)], "")))
    monkeypatch.setattr(las_import_dialog.LasImportDialog, "exec",
                        lambda self: QDialog.DialogCode.Accepted)
    assert group.import_las_button.isEnabled()
    group.import_las()
    [editor] = group.curve_editors
    table = editor.setting()
    assert table.id_field == "id" and table.depth_field == "depth"
    assert [(c.field, c.unit) for c in table.curves] == [("gr", "GAPI"), ("res", "OHMM")]
    added = project.mapLayer(table.layer_id)
    assert added.name() == "LAS curves" and added.featureCount() == 5
    assert "site_groundwork.gpkg" in added.source()
    group.deleteLater()


def test_import_las_waits_for_a_borehole_layer_and_a_project(qgis_app, collars):
    from groundwork_geophysics.ui.borehole_mapping import BoreholeGroup
    project, layer = collars
    group = BoreholeGroup(project, [layer], [layer], store_path=lambda: None)
    group.set_layer(layer.id())
    assert not group.import_las_button.isEnabled()
    assert "Groundwork project" in group.import_las_button.toolTip()
    group.deleteLater()
