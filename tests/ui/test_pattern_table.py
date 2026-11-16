"""Patterns…: one row per class of a categorized borehole style, a colour and an FGDC pattern
each; the result is ordinary QGIS symbols (simple fill + SVG fill)."""
import pytest


def _renderer():
    from qgis.core import QgsCategorizedSymbolRenderer, QgsFillSymbol, QgsRendererCategory
    return QgsCategorizedSymbolRenderer("lith", [
        QgsRendererCategory("sand", QgsFillSymbol.createSimple({"color": "240,220,120"}), "sand"),
        QgsRendererCategory("clay", QgsFillSymbol.createSimple({"color": "120,140,170"}), "clay")])


def _svg_layers(symbol):
    from qgis.core import QgsSVGFillSymbolLayer
    return [symbol.symbolLayer(i) for i in range(symbol.symbolLayerCount())
            if isinstance(symbol.symbolLayer(i), QgsSVGFillSymbolLayer)]


def _symbols(renderer):
    """value -> cloned symbol (categories() returns copies: keep nothing that points into
    them after the list is gone)."""
    cats = renderer.categories()
    return {c.value(): c.symbol().clone() for c in cats}


def test_rows_follow_the_classes_with_their_colours(qgis_app):
    from groundwork_geophysics.ui.pattern_table import PatternTable
    t = PatternTable(_renderer())
    assert t.values() == ["sand", "clay"]
    c = t.colour("sand")
    assert (c.red(), c.green(), c.blue()) == (240, 220, 120)
    assert t.pattern("sand") is None
    t.deleteLater()


def test_chosen_pattern_becomes_a_qgis_svg_fill_over_the_colour(qgis_app):
    from groundwork_geophysics.patterns import catalogue
    from groundwork_geophysics.ui.pattern_table import PatternTable
    sand = next(p for p in catalogue() if p.code == "607")
    t = PatternTable(_renderer())
    t.set_pattern("sand", sand)
    r = t.result()
    cats = _symbols(r)
    svg = _svg_layers(cats["sand"])
    assert len(svg) == 1 and svg[0].svgFilePath().endswith("607 Massive sand or sandstone.svg")
    assert cats["sand"].symbolLayer(0).color().red() == 240        # the colour stays below
    assert _svg_layers(cats["clay"]) == []                          # untouched class
    t.deleteLater()


def test_existing_pattern_is_recognised_and_can_be_removed(qgis_app):
    from groundwork_geophysics.patterns import catalogue
    from groundwork_geophysics.ui.pattern_table import PatternTable
    sand = next(p for p in catalogue() if p.code == "607")
    first = PatternTable(_renderer())
    first.set_pattern("sand", sand)
    again = PatternTable(first.result())
    assert again.pattern("sand") == sand
    again.set_pattern("sand", None)
    assert _svg_layers(_symbols(again.result())["sand"]) == []
    first.deleteLater()
    again.deleteLater()


def test_pattern_search_matches_names(qgis_app):
    from groundwork_geophysics.ui.pattern_table import PatternTable
    t = PatternTable(_renderer())
    hits = t.search("sandstone")
    assert hits and all("sandstone" in p.name.lower() for p in hits)
    assert [p.code for p in t.search("607")] == ["607"]
    t.deleteLater()


def test_style_window_patterns_need_categorized(qgis_app):
    """Patterns… on a non-categorized style says what to do instead of failing; on a
    categorized one it hands the result to QGIS's editor."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "section"))
    from qgis.core import QgsProject

    from groundwork_geophysics.core.context_settings import BoreholeSetting
    from groundwork_geophysics.patterns import catalogue
    from groundwork_geophysics.ui.borehole_style_dialog import BoreholeStyleDialog
    from test_context_layers import _add, _layer
    prj = QgsProject.instance()
    prj.clear()
    log = _layer(prj, "NoGeometry", "Log", "bid:string&field=top:double&field=bot:double"
                 "&field=lith:string")
    _add(log, None, ["B1", 0.0, 2.0, "sand"])
    dlg = BoreholeStyleDialog(prj, BoreholeSetting("p", "bid", "", log.id(), "bid", "top",
                                                   "bot", ""), [], lambda: None)
    assert dlg.copy.renderer().type() == "singleSymbol"            # no text field: default
    assert dlg.patterns_table() is None and "Categorized" in dlg.note.text()
    dlg.copy.setRenderer(_renderer())
    dlg.reload_editor()
    table = dlg.patterns_table()
    table.set_pattern("sand", next(p for p in catalogue() if p.code == "607"))
    dlg.take_patterns(table)
    sand = _symbols(dlg.copy.renderer())["sand"]
    assert len(_svg_layers(sand)) == 1
    dlg.close()
    prj.removeAllMapLayers()
    prj.clear()
