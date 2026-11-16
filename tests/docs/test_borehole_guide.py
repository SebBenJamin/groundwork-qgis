"""The borehole guide's steps work on its templates (docs/user/boreholes.md): the Excel sheets
open in QGIS with typed columns, QGIS's "Create points layer from table" makes the collars,
and Context Layers… with the guide's field names gives boreholes with layers and curves."""
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def templates(tmp_path, qgis_app):
    import make_borehole_templates
    make_borehole_templates.write(tmp_path)
    return tmp_path


def test_committed_templates_are_current(tmp_path, qgis_app):
    """docs/user/templates holds what the script writes (the CSVs byte for byte)."""
    import make_borehole_templates
    make_borehole_templates.write(tmp_path)
    for name in ("collars", "layers", "curves"):
        f = f"boreholes_{name}.csv"
        assert (tmp_path / f).read_bytes() == (make_borehole_templates.OUT / f).read_bytes()
    assert (make_borehole_templates.OUT / "boreholes_template.xlsx").is_file()


def test_excel_sheets_open_with_typed_columns(templates):
    from qgis.core import QgsVectorLayer
    from qgis.PyQt.QtCore import QMetaType
    xlsx = templates / "boreholes_template.xlsx"
    collars = QgsVectorLayer(f"{xlsx}|layername=collars", "collars", "ogr")
    layers = QgsVectorLayer(f"{xlsx}|layername=layers", "layers", "ogr")
    assert collars.isValid() and layers.isValid()
    assert collars.fields().names() == ["id", "x", "y", "elevation", "total_depth"]
    numeric = (QMetaType.Type.Double, QMetaType.Type.Int, QMetaType.Type.LongLong)
    assert collars.fields().field("x").type() in numeric         # whole numbers: Integer
    assert layers.fields().field("top").type() in numeric
    assert layers.fields().field("lithology").type() == QMetaType.Type.QString
    assert collars.featureCount() == 3


def test_guide_steps_give_boreholes_with_layers_and_curves(templates, project):
    """Points from the collars sheet (QGIS's processing tool, as in the guide), then the
    guide's Context Layers… settings: every borehole is found on a line along them, with its
    layers and both curves."""
    from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsVectorLayer
    sys.path.insert(0, str(Path(QgsApplication.pkgDataPath()) / "python" / "plugins"))
    import processing
    from processing.core.Processing import Processing

    from groundwork_geophysics.core.context_settings import (BoreholeSetting, ContextSettings,
                                                            CurveField, CurveTableSetting)
    from groundwork_geophysics.core.model import Profile
    from groundwork_geophysics.section.context_layers import ContextGatherer
    from groundwork_geophysics.ui.context_dialog import write_settings
    Processing.initialize()
    xlsx = templates / "boreholes_template.xlsx"
    result = processing.run("native:createpointslayerfromtable", {
        "INPUT": f"{xlsx}|layername=collars", "XFIELD": "x", "YFIELD": "y",
        "TARGET_CRS": QgsCoordinateReferenceSystem("EPSG:25833"),
        "OUTPUT": str(templates / "collars.gpkg")})
    collars = QgsVectorLayer(result["OUTPUT"], "Collars", "ogr")
    layers = QgsVectorLayer(f"{xlsx}|layername=layers", "Layers", "ogr")
    curves = QgsVectorLayer(f"{xlsx}|layername=curves", "Curves", "ogr")
    for lyr in (collars, layers, curves):
        assert lyr.isValid()
        project.addMapLayer(lyr)
    settings = ContextSettings(boreholes=[BoreholeSetting(
        collars.id(), "id", "elevation", layers.id(), "id", "top", "bottom", "lithology",
        total_depth_field="total_depth",
        curve_tables=[CurveTableSetting(curves.id(), "id", "depth",
                                        [CurveField("gamma_api", "API"),
                                         CurveField("resistivity_ohmm", "ohm.m")])])],
        buffer=10.0)
    line = Profile("p", "Line", np.array([[400000.0, 5800000.0], [400100.0, 5800000.0]]),
                   "EPSG:25833")
    write_settings(project, settings)
    g = ContextGatherer(project, "EPSG:25833", lambda: None)
    items = g.items_for(line)
    g.close()
    bh = sorted((p for p in items.points if p.kind == "borehole"), key=lambda p: p.s)
    assert [p.label for p in bh] == ["BH1", "BH2", "BH3"]
    assert [p.z_source for p in bh] == ["field"] * 3
    assert [len(p.log) for p in bh] == [3, 3, 2] and bh[0].log[1].text == "sand"
    assert all(len(p.curves) == 2 for p in bh)
    assert bh[1].total_depth == pytest.approx(8.0)


@pytest.fixture
def project(qgis_app):
    from qgis.core import QgsProject
    proj = QgsProject.instance()
    proj.clear()
    yield proj
    proj.removeAllMapLayers()
    proj.clear()


def _processing():
    from qgis.core import QgsApplication
    sys.path.insert(0, str(Path(QgsApplication.pkgDataPath()) / "python" / "plugins"))
    import processing
    from processing.core.Processing import Processing
    Processing.initialize()
    return processing


def test_one_sheet_layout_gives_one_collar_per_borehole(tmp_path, project):
    """Everything on one sheet (coordinates repeated on every layer row): points from the
    table, then "Delete duplicates by attribute" on the id gives one collar each."""
    from qgis.core import QgsCoordinateReferenceSystem, QgsVectorLayer
    processing = _processing()
    sheet = tmp_path / "all.csv"
    sheet.write_text("id,x,y,elevation,top,bottom,lithology\n"
                     "BH1,400010,5800001.5,31.2,0,0.4,topsoil\n"
                     "BH1,400010,5800001.5,31.2,0.4,2.5,sand\n"
                     "BH2,400050,5799998,30.85,0,4,sand\n", encoding="utf-8")
    pts = processing.run("native:createpointslayerfromtable", {
        "INPUT": str(sheet), "XFIELD": "x", "YFIELD": "y",
        "TARGET_CRS": QgsCoordinateReferenceSystem("EPSG:25833"), "OUTPUT": "memory:"})["OUTPUT"]
    one = processing.run("native:removeduplicatesbyattribute", {
        "INPUT": pts, "FIELDS": ["id"], "OUTPUT": "memory:"})["OUTPUT"]
    assert sorted(f["id"] for f in one.getFeatures()) == ["BH1", "BH2"]
    layers = QgsVectorLayer(str(sheet), "all", "ogr")
    assert layers.featureCount() == 3                     # the same sheet is the layer table


def test_one_file_per_borehole_tables_merge(tmp_path, project):
    """One file per borehole: "Merge vector layers" combines tables without geometry."""
    from qgis.core import QgsVectorLayer
    processing = _processing()
    paths = []
    for bid, rows in (("BH1", "0,0.4,topsoil\n0.4,2.5,sand\n"), ("BH2", "0,4,sand\n")):
        p = tmp_path / f"{bid}.csv"
        p.write_text("id,top,bottom,lithology\n" + "".join(f"{bid},{r}\n" for r in
                                                          rows.strip().split("\n")),
                     encoding="utf-8")
        paths.append(str(p))
    merged = processing.run("native:mergevectorlayers", {
        "LAYERS": paths, "OUTPUT": str(tmp_path / "layers.gpkg")})["OUTPUT"]
    out = QgsVectorLayer(merged, "layers", "ogr")
    assert out.isValid() and out.featureCount() == 3
    assert sorted({f["id"] for f in out.getFeatures()}) == ["BH1", "BH2"]
