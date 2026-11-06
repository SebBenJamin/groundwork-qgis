"""Borehole intervals drawn with a QGIS renderer stored in the project per interval table."""
import pytest

from test_context_layers import AUTH, _add, _gatherer, _layer, profile, project  # noqa: F401


def _fields(*names):
    from qgis.core import QgsField, QgsFields
    from qgis.PyQt.QtCore import QMetaType
    out = QgsFields()
    for n in names:
        out.append(QgsField(n, QMetaType.Type.QString))
    return out


def _feature(fields, **values):
    from qgis.core import QgsFeature
    f = QgsFeature(fields)
    for k, v in values.items():
        f[k] = v
    return f


def _categorized(field="lithology", value="Sand", rgb=(240, 220, 120)):
    from qgis.core import QgsCategorizedSymbolRenderer, QgsFillSymbol, QgsRendererCategory
    sym = QgsFillSymbol.createSimple({"color": ",".join(map(str, rgb))})
    return QgsCategorizedSymbolRenderer(field, [QgsRendererCategory(value, sym, value)])


def _rgb(symbol):
    c = symbol.color()
    return c.red(), c.green(), c.blue()


def test_save_load_round_trip(project):
    from geophysics_workbench.section.borehole_style import load_renderer, save_renderer
    save_renderer(project, "logs1", _categorized())
    back = load_renderer(project, "logs1")
    assert back is not None and back.type() == "categorizedSymbol"
    cat = back.categories()[0]
    assert cat.value() == "Sand" and _rgb(cat.symbol()) == (240, 220, 120)
    save_renderer(project, "logs1", None)
    assert load_renderer(project, "logs1") is None


def test_no_renderer_gives_label_colour(qgis_app):
    from geophysics_workbench.core.lithology import label_colour
    from geophysics_workbench.section.borehole_style import interval_symbols
    fields = _fields("lithology")
    (sym, feat), = interval_symbols(None, fields, [_feature(fields, lithology="Sand")],
                                    texts=["Sand"])
    assert _rgb(sym) == label_colour("Sand") and feat["lithology"] == "Sand"


def test_renderer_on_missing_field_falls_back(qgis_app):
    from geophysics_workbench.core.lithology import label_colour
    from geophysics_workbench.section.borehole_style import interval_symbols
    fields = _fields("lithology")
    (sym, _f), = interval_symbols(_categorized(field="gone"), fields,
                                  [_feature(fields, lithology="Sand")], texts=["Sand"])
    assert _rgb(sym) == label_colour("Sand")


def test_rule_with_bad_expression_falls_back(qgis_app):
    from qgis.core import QgsFillSymbol, QgsRuleBasedRenderer
    from geophysics_workbench.core.lithology import label_colour
    from geophysics_workbench.section.borehole_style import interval_symbols
    root = QgsRuleBasedRenderer.Rule(None)
    root.appendChild(QgsRuleBasedRenderer.Rule(
        QgsFillSymbol.createSimple({"color": "255,0,0"}), 0, 0, "\"lithology\" = = 'x' ((("))
    fields = _fields("lithology")
    (sym, _f), = interval_symbols(QgsRuleBasedRenderer(root), fields,
                                  [_feature(fields, lithology="Clay")], texts=["Clay"])
    assert _rgb(sym) == label_colour("Clay")


def test_gatherer_attaches_symbols(project, profile):
    from geophysics_workbench.core.context_settings import BoreholeSetting, ContextSettings
    from geophysics_workbench.section.borehole_style import save_renderer
    bh = _layer(project, "Point", "BH", "bid:string")
    _add(bh, "POINT(20 1)", ["B1"])
    log = _layer(project, "NoGeometry", "Log",
                 "bid:string&field=top:double&field=bot:double&field=lith:string"
                 "&field=code:string")
    _add(log, None, ["B1", 0.0, 2.0, "fine sand", "S"])
    _add(log, None, ["B1", 2.0, 3.0, "clay", "T"])
    # styled on a field the gatherer does not otherwise read
    save_renderer(project, log.id(), _categorized(field="code", value="S", rgb=(10, 200, 30)))
    g = _gatherer(project, ContextSettings(boreholes=[BoreholeSetting(
        bh.id(), "bid", "", log.id(), "bid", "top", "bot", "lith")]))
    p = g.items_for(profile).points[0]
    g.close()
    from geophysics_workbench.core.lithology import label_colour
    assert _rgb(p.log[0].symbol) == (10, 200, 30)
    assert _rgb(p.log[1].symbol) == label_colour("clay")      # no category: neutral default
    assert p.log[0].feature["code"] == "S"
