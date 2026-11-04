"""Which line layers cross a section, and in which colour (main thread only).

A line layer is active when its saved ``checked`` is True, or when it was never ticked
(``checked`` is None) and is visible in the layer tree. The workbench's own layers are
never candidates."""
from __future__ import annotations

from qgis.core import Qgis, QgsRenderContext, QgsVectorLayer

from ..core.context import DEFAULT_LINE_RGB
from ..core.context_settings import ContextSettings, LineLayerSetting
from ..ui import project_actions


def own_layer_ids(store, project) -> set[str]:
    """Ids of the store's own layers in ``project``: profiles, stations, interpretation."""
    from ..ui.interp_layers import interp_layers
    own = list(project_actions.store_layers(store, project).values())
    own += list(interp_layers(store, project).values())
    return {layer.id() for layer in own}


def candidate_line_layers(project, exclude: set[str]) -> list[QgsVectorLayer]:
    """Valid line layers not in ``exclude``, sorted by name."""
    found = [layer for layer in project.mapLayers().values()
             if isinstance(layer, QgsVectorLayer) and layer.isValid()
             and layer.geometryType() == Qgis.GeometryType.Line
             and layer.id() not in exclude]
    return sorted(found, key=lambda layer: layer.name().casefold())


def map_visible(project, layer_id: str) -> bool:
    node = project.layerTreeRoot().findLayer(layer_id)
    return node is not None and node.isVisible()


def active_line_settings(project, settings: ContextSettings, exclude: set[str]
                         ) -> list[tuple[QgsVectorLayer, LineLayerSetting]]:
    saved = {s.layer_id: s for s in settings.line_layers}
    out = []
    for layer in candidate_line_layers(project, exclude):
        setting = saved.get(layer.id()) or LineLayerSetting(layer.id())
        if setting.checked is True or (setting.checked is None
                                       and map_visible(project, layer.id())):
            out.append((layer, setting))
    return out


def symbol_colour(layer) -> tuple[int, int, int]:
    """The first renderer symbol's colour, else the default grey."""
    renderer = layer.renderer()
    if renderer is None:
        return DEFAULT_LINE_RGB
    symbols = renderer.symbols(QgsRenderContext())
    if not symbols:
        return DEFAULT_LINE_RGB
    colour = symbols[0].color()
    return (colour.red(), colour.green(), colour.blue())


def line_colour(setting: LineLayerSetting, layer) -> tuple[int, int, int]:
    text = setting.colour
    if text:
        return (int(text[1:3], 16), int(text[3:5], 16), int(text[5:7], 16))
    return symbol_colour(layer)
