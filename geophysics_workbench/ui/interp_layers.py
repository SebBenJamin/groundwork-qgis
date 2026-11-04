"""Interpretation layers in the QGIS project.

``interp_features`` is editable (attributes, and fields the user adds); the derived 3D and
footprint layers are read-only for geometry and rebuilt from the pieces. Their default styles
are written once, when the layers are added; afterwards they are ordinary QGIS styles the user
can change, and the section draws with the same styles.
"""
from __future__ import annotations

from qgis.core import (QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings,
                       QgsProject, QgsRuleBasedRenderer, QgsTextFormat, QgsVectorLayer,
                       QgsVectorLayerSimpleLabeling, QgsWkbTypes)
from qgis.PyQt.QtGui import QColor

from ..store.gpkg_store import ProjectStore
from .project_actions import GROUP_NAME, find_store_layers

INTERP_GROUP = "Interpretation"
INTERP_NAMES = ("interp_features", "interp_polygons_3d", "interp_lines_3d", "interp_points_3d",
                "interp_footprints")
TITLES = {"interp_features": "Interpretation features (attributes)",
          "interp_polygons_3d": "Interpretation polygons (3D)",
          "interp_lines_3d": "Interpretation lines (3D)",
          "interp_points_3d": "Interpretation points (3D)",
          "interp_footprints": "Interpretation footprints"}
# default look, written once into the layer styles (the user restyles in QGIS afterwards)
DEFAULT_RGB = (170, 0, 140)
DASHES = {"certain": "solid", "probable": "dash", "uncertain": "dot"}


def interp_layers(store: ProjectStore, project: QgsProject) -> dict[str, QgsVectorLayer]:
    return find_store_layers(store, project, INTERP_NAMES)


def default_style(layer: QgsVectorLayer) -> None:
    """Rule-based by ``confidence`` (solid / dashed / dotted, grey dashed when unset) and
    ``letter`` labels."""
    colour = ",".join(map(str, DEFAULT_RGB))
    geom = layer.geometryType()

    def symbol(style: str, rgb: str):
        if geom == QgsWkbTypes.GeometryType.PolygonGeometry:
            return QgsFillSymbol.createSimple({"color": f"{rgb},50", "outline_color": rgb,
                                               "outline_width": "0.6", "outline_style": style})
        if geom == QgsWkbTypes.GeometryType.PointGeometry:
            return QgsMarkerSymbol.createSimple({"name": "cross2", "color": rgb,
                                                 "outline_color": rgb, "size": "3"})
        return QgsLineSymbol.createSimple({"color": rgb, "width": "0.6", "line_style": style})

    root = QgsRuleBasedRenderer.Rule(None)
    for value, style in DASHES.items():
        root.appendChild(QgsRuleBasedRenderer.Rule(symbol(style, colour),
                                                   filterExp=f"\"confidence\" = '{value}'",
                                                   label=value))
    root.appendChild(QgsRuleBasedRenderer.Rule(symbol("dash", "120,120,120"), elseRule=True,
                                               label="not set"))
    layer.setRenderer(QgsRuleBasedRenderer(root))
    settings = QgsPalLayerSettings()
    settings.fieldName = "letter"
    fmt = QgsTextFormat()
    fmt.setSize(10.0)
    fmt.setColor(QColor(*DEFAULT_RGB))
    buffer = fmt.buffer()
    buffer.setEnabled(True)
    fmt.setBuffer(buffer)
    settings.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def add_interp_layers(store: ProjectStore, project: QgsProject) -> dict[str, QgsVectorLayer]:
    """Add the interpretation layers in an "Interpretation" subgroup unless already there."""
    have = interp_layers(store, project)
    root = project.layerTreeRoot()
    top = root.findGroup(GROUP_NAME) or root.insertGroup(0, GROUP_NAME)
    group = top.findGroup(INTERP_GROUP) or top.insertGroup(0, INTERP_GROUP)
    for name in INTERP_NAMES:
        if name in have:
            continue
        layer = QgsVectorLayer(store.layer_uri(name), TITLES[name], "ogr")
        if not layer.isValid():
            raise ValueError(f"QGIS cannot load layer {name!r} from {store.path}")
        if name != "interp_features":
            default_style(layer)
            layer.setReadOnly(True)
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        have[name] = layer
    return have


def reload_interp_layers(store: ProjectStore, project: QgsProject) -> None:
    for layer in interp_layers(store, project).values():
        layer.dataProvider().reloadData()
        layer.reload()
        layer.updateExtents()
        layer.triggerRepaint()


class InterpSync:
    """Rebuild the derived layers when the features table is edited in QGIS."""

    def __init__(self, store, project, on_change, version_id, chainages):
        self.store, self.project, self.on_change = store, project, on_change
        self.version_id, self.chainages = version_id, chainages
        self._layer = interp_layers(store, project).get("interp_features")
        if self._layer is not None:
            self._layer.afterCommitChanges.connect(self._committed)

    def _committed(self) -> None:
        try:
            self.store.rebuild_derived(self.version_id(), self.chainages())
        finally:
            reload_interp_layers(self.store, self.project)
            self.on_change()

    def detach(self) -> None:
        if self._layer is not None:
            try:
                self._layer.afterCommitChanges.disconnect(self._committed)
            except (TypeError, RuntimeError):
                pass
            self._layer = None
