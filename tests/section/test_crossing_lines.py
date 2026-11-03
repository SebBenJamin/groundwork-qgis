import pytest

AUTH = "EPSG:25832"


@pytest.fixture
def project(qgis_app):
    from qgis.core import QgsProject
    # QgsProject() kept alive in a fixture cache crashes QgsApplication.exitQgis
    proj = QgsProject.instance()
    proj.clear()
    yield proj
    proj.removeAllMapLayers()
    proj.clear()


def _layer(project, kind, name, fields="", crs=AUTH):
    from qgis.core import QgsVectorLayer
    uri = f"{kind}?crs={crs}" + (f"&field={fields}" if fields else "")
    layer = QgsVectorLayer(uri, name, "memory")
    assert layer.isValid()
    project.addMapLayer(layer)
    return layer


def test_candidates_are_line_layers_minus_excluded(project):
    from geophysics_workbench.section.crossing_lines import candidate_line_layers
    _layer(project, "LineString", "b")
    _layer(project, "LineString", "A")
    c = _layer(project, "LineString", "c")
    _layer(project, "Point", "pts")
    got = candidate_line_layers(project, {c.id()})
    assert [layer.name() for layer in got] == ["A", "b"]


def test_unsaved_visible_layer_is_active_hidden_is_not(project):
    from geophysics_workbench.core.context_settings import ContextSettings
    from geophysics_workbench.section.crossing_lines import active_line_settings
    shown = _layer(project, "LineString", "shown")
    hidden = _layer(project, "LineString", "hidden")
    project.layerTreeRoot().findLayer(hidden.id()).setItemVisibilityChecked(False)
    got = active_line_settings(project, ContextSettings(), set())
    assert [(layer.id(), s.layer_id) for layer, s in got] == [(shown.id(), shown.id())]


def test_layer_in_hidden_group_is_not_visible(project):
    from geophysics_workbench.section.crossing_lines import map_visible
    from qgis.core import QgsVectorLayer
    layer = QgsVectorLayer(f"LineString?crs={AUTH}", "L", "memory")
    project.addMapLayer(layer, False)          # only in the group, not at the root
    group = project.layerTreeRoot().addGroup("G")
    group.addLayer(layer)
    assert map_visible(project, layer.id())
    group.setItemVisibilityChecked(False)
    assert not map_visible(project, layer.id())
    assert not map_visible(project, "gone")


def test_explicit_tick_wins_over_visibility(project):
    from geophysics_workbench.core.context_settings import ContextSettings, LineLayerSetting
    from geophysics_workbench.section.crossing_lines import active_line_settings
    hidden = _layer(project, "LineString", "hidden")
    shown = _layer(project, "LineString", "shown")
    project.layerTreeRoot().findLayer(hidden.id()).setItemVisibilityChecked(False)
    settings = ContextSettings(line_layers=[LineLayerSetting(hidden.id(), checked=True),
                                            LineLayerSetting(shown.id(), checked=False)])
    got = active_line_settings(project, settings, set())
    assert [layer.id() for layer, _s in got] == [hidden.id()]


def _single(layer, rgb):
    from qgis.core import QgsLineSymbol, QgsSingleSymbolRenderer
    from qgis.PyQt.QtGui import QColor
    symbol = QgsLineSymbol.createSimple({})
    symbol.setColor(QColor(*rgb))
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))


def test_symbol_colour_single_categorised_and_none(project):
    from qgis.core import (QgsCategorizedSymbolRenderer, QgsLineSymbol,
                           QgsRendererCategory)
    from qgis.PyQt.QtGui import QColor
    from geophysics_workbench.core.context import DEFAULT_LINE_RGB
    from geophysics_workbench.section.crossing_lines import symbol_colour
    layer = _layer(project, "LineString", "L", "kind:string")
    _single(layer, (220, 0, 0))
    assert symbol_colour(layer) == (220, 0, 0)

    def category(value, rgb):
        symbol = QgsLineSymbol.createSimple({})
        symbol.setColor(QColor(*rgb))
        return QgsRendererCategory(value, symbol, value)
    layer.setRenderer(QgsCategorizedSymbolRenderer(
        "kind", [category("a", (0, 120, 0)), category("b", (1, 2, 3))]))
    assert symbol_colour(layer) == (0, 120, 0)
    try:
        layer.setRenderer(None)
    except TypeError:
        layer.setRenderer(QgsCategorizedSymbolRenderer("kind", []))
    assert symbol_colour(layer) == DEFAULT_LINE_RGB
    layer.setRenderer(QgsCategorizedSymbolRenderer("kind", []))
    assert symbol_colour(layer) == DEFAULT_LINE_RGB


def test_line_colour_prefers_saved_hex(project):
    from geophysics_workbench.core.context_settings import LineLayerSetting
    from geophysics_workbench.section.crossing_lines import line_colour
    layer = _layer(project, "LineString", "L")
    _single(layer, (220, 0, 0))
    assert line_colour(LineLayerSetting(layer.id(), colour="#0000ff"), layer) == (0, 0, 255)
    assert line_colour(LineLayerSetting(layer.id(), colour=""), layer) == (220, 0, 0)


def test_own_layer_ids_are_store_layers(project, store_with_model):
    from geophysics_workbench.section.crossing_lines import own_layer_ids
    from geophysics_workbench.ui import project_actions
    st, _p, _src = store_with_model
    added = project_actions.add_store_layers(st, project)
    assert own_layer_ids(st, project) == {layer.id() for layer in added.values()}
    assert len(added) == 2
