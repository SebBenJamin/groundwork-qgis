"""Shipped borehole styles (styles/boreholes/*.qml): Categorized on "lithology" with DIN-style
short codes or EN ISO 14688-1 symbols, FGDC patterns referenced by name (not by a path on
one machine), loadable in the Borehole style window."""
from pathlib import Path

import pytest

DIN = {"G", "fG", "mG", "gG", "S", "fS", "mS", "gS", "U", "T", "X", "Y", "H", "F", "Mu", "A",
       "Mg", "Lg"}
ISO = {"Bo", "Co", "Gr", "CGr", "MGr", "FGr", "Sa", "CSa", "MSa", "FSa", "Si", "Cl", "Or", "Mg"}


def _copy():
    from qgis.core import QgsVectorLayer
    layer = QgsVectorLayer("Polygon?field=lithology:string", "copy", "memory")
    assert layer.isValid()
    return layer


@pytest.mark.parametrize("name,codes", [("din_codes.qml", DIN), ("iso_14688.qml", ISO)])
def test_shipped_style_loads_with_its_classes_and_patterns(qgis_app, name, codes):
    from qgis.core import QgsMapLayer, QgsSVGFillSymbolLayer

    from geophysics_workbench.patterns import register_svg_path, unregister_svg_path
    from geophysics_workbench.styles import STYLE_DIR
    path = STYLE_DIR / "boreholes" / name
    text = path.read_text(encoding="utf-8")
    assert ":/" not in text.split("<renderer-v2")[1].split("</renderer-v2>")[0].replace(
        "qrc:/", "")                                   # no drive letters: works anywhere
    register_svg_path()
    try:
        layer = _copy()
        _msg, ok = layer.loadNamedStyle(str(path), QgsMapLayer.StyleCategory.Symbology)
        assert ok
        r = layer.renderer()
        assert r.type() == "categorizedSymbol" and r.classAttribute() == "lithology"
        cats = r.categories()
        assert {c.value() for c in cats} == codes
        svgs = [c.symbol().symbolLayer(i).svgFilePath() for c in cats
                for i in range(c.symbol().symbolLayerCount())
                if isinstance(c.symbol().symbolLayer(i), QgsSVGFillSymbolLayer)]
        assert svgs and all(Path(p).is_file() for p in svgs)
    finally:
        unregister_svg_path()


def test_readme_says_the_choices_are_not_a_standard():
    from geophysics_workbench.styles import STYLE_DIR
    text = (STYLE_DIR / "boreholes" / "README.md").read_text(encoding="utf-8")
    assert "not" in text and "DIN 4023" in text and "EN ISO 14688-1" in text


def test_import_starts_in_the_shipped_styles(qgis_app):
    from geophysics_workbench.styles import STYLE_DIR
    from geophysics_workbench.ui.borehole_style_dialog import import_folder
    assert Path(import_folder()) == STYLE_DIR / "boreholes"


def test_styles_are_in_the_plugin_zip():
    from scripts.package import PLUGIN, files_under
    rel = {p.relative_to(PLUGIN).as_posix() for p in files_under(PLUGIN)}
    assert {"styles/boreholes/din_codes.qml", "styles/boreholes/iso_14688.qml",
            "styles/boreholes/README.md"} <= rel


def test_readme_expression_keeps_the_main_component(qgis_app):
    from qgis.core import QgsExpression, QgsExpressionContext, QgsFeature, QgsField, QgsFields
    from qgis.PyQt.QtCore import QMetaType
    fields = QgsFields()
    fields.append(QgsField("lithology", QMetaType.Type.QString))
    expr = QgsExpression("""trim(regexp_substr("lithology", '^[^,;]+'))""")
    assert not expr.hasParserError()
    for text, main in (("fS, ms, u'", "fS"), ("T; u", "T"), ("Mu", "Mu"), (" G ", "G")):
        f = QgsFeature(fields)
        f["lithology"] = text
        ctx = QgsExpressionContext()
        ctx.setFeature(f)
        assert expr.evaluate(ctx) == main, text


GUELPE_CLASSES = {"sand", "loam", "clay", "peat", "Oh"}


def test_guelpe_core_style_classifies_by_main_class(qgis_app):
    """The Gülpe cores' values are "main class · texture code" (e.g. "sand · Ss (mS)"): the
    demo style is Categorized on an expression (the text before "·"), five classes."""
    from qgis.core import QgsMapLayer

    from geophysics_workbench.patterns import register_svg_path, unregister_svg_path
    path = Path(__file__).resolve().parents[1] / "demo_guelpe" / "context" / "core_logs_style.qml"
    register_svg_path()
    try:
        layer = _copy()
        _msg, ok = layer.loadNamedStyle(str(path), QgsMapLayer.StyleCategory.Symbology)
        assert ok
        r = layer.renderer()
        assert r.type() == "categorizedSymbol" and "lithology" in r.classAttribute()
        cats = r.categories()
        assert {c.value() for c in cats} == GUELPE_CLASSES
    finally:
        unregister_svg_path()


def test_gatherer_colours_intervals_by_main_class(qgis_app):
    """Stored as the interval table's style, the expression style colours "sand · Ss (mS)"
    like "sand · St2", and clay differently."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent / "section"))
    import numpy as np
    from qgis.core import QgsMapLayer, QgsProject

    from geophysics_workbench.core.context_settings import BoreholeSetting, ContextSettings
    from geophysics_workbench.core.model import Profile
    from geophysics_workbench.patterns import register_svg_path, unregister_svg_path
    from geophysics_workbench.section.borehole_style import save_renderer
    from test_context_layers import _add, _gatherer, _layer
    prj = QgsProject.instance()
    prj.clear()
    register_svg_path()
    try:
        bh = _layer(prj, "Point", "BH", "bid:string")
        _add(bh, "POINT(20 1)", ["RK1"])
        log = _layer(prj, "NoGeometry", "Log", "core_id:string&field=top:double"
                     "&field=bottom:double&field=lithology:string")
        for top, bottom, lith in ((0, 1, "sand · Ss (mS)"), (1, 2, "sand · St2"),
                                  (2, 3, "clay · Tu2")):
            _add(log, None, ["RK1", top, bottom, lith])
        style = _copy()
        style.loadNamedStyle(str(Path(__file__).resolve().parents[1] / "demo_guelpe" /
                                 "context" / "core_logs_style.qml"),
                             QgsMapLayer.StyleCategory.Symbology)
        save_renderer(prj, log.id(), style.renderer().clone())
        g = _gatherer(prj, ContextSettings(boreholes=[BoreholeSetting(
            bh.id(), "bid", "", log.id(), "core_id", "top", "bottom", "lithology")]))
        p = g.items_for(Profile("p1", "P1", np.array([[0.0, 0.0], [100.0, 0.0]]),
                                "EPSG:25832")).points[0]
        g.close()
        colours = [iv.symbol.symbolLayer(0).color().name() for iv in p.log]
        assert colours[0] == colours[1] != colours[2]
    finally:
        unregister_svg_path()
        prj.removeAllMapLayers()
        prj.clear()
