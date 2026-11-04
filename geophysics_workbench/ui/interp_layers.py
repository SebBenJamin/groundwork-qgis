"""Interpretation layers in the QGIS project.

``interp_features`` is editable (attributes, and fields the user adds); the derived 3D and
footprint layers are read-only for geometry and rebuilt from the pieces. Their default styles
are written once, when the layers are added; afterwards they are ordinary QGIS styles the user
can change, and the section draws with the same styles.
"""
from __future__ import annotations

from qgis.core import (QgsCategorizedSymbolRenderer, QgsFillSymbol, QgsLineSymbol,
                       QgsMarkerSymbol, QgsPalLayerSettings, QgsProject, QgsProperty,
                       QgsRendererCategory, QgsSymbolLayer, QgsTextFormat, QgsVectorLayer,
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
DEFAULT_HUE = 310


def interp_layers(store: ProjectStore, project: QgsProject) -> dict[str, QgsVectorLayer]:
    return find_store_layers(store, project, INTERP_NAMES)


STROKE_BY_CONFIDENCE = ("CASE WHEN \"confidence\" = 'certain' THEN 'solid' "
                        "WHEN \"confidence\" = 'uncertain' THEN 'dot' ELSE 'dash' END")


def entity_label(feat) -> str:
    return " · ".join(x for x in (feat.letter, feat.type) if x) or "(unnamed)"


def _entity_symbol(geom, rgb):
    """A symbol in ``rgb`` whose line style follows ``confidence`` (data-defined)."""
    colour = ",".join(map(str, rgb))
    if geom == QgsWkbTypes.GeometryType.PolygonGeometry:
        sym = QgsFillSymbol.createSimple({"color": f"{colour},60", "outline_color": colour,
                                          "outline_width": "0.6"})
    elif geom == QgsWkbTypes.GeometryType.PointGeometry:
        return QgsMarkerSymbol.createSimple({"name": "cross2", "color": colour,
                                             "outline_color": colour, "size": "3"})
    else:
        sym = QgsLineSymbol.createSimple({"color": colour, "width": "0.6"})
    sym.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.StrokeStyle,
                                              QgsProperty.fromExpression(STROKE_BY_CONFIDENCE))
    return sym


def _entity_rgb(index: int) -> tuple[int, int, int]:
    c = QColor.fromHsv((DEFAULT_HUE + index * 67) % 360, 200, 190)
    return c.red(), c.green(), c.blue()


def default_style(layer: QgsVectorLayer) -> None:
    """One legend entry and colour per entity (``feature_id``); the line style follows
    ``confidence``; ``letter`` labels. Categories are filled by ``sync_categories``."""
    layer.setRenderer(QgsCategorizedSymbolRenderer("feature_id", []))
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


def sync_categories(layer: QgsVectorLayer, features) -> None:
    """Keep one category per entity: add new ones, relabel, drop deleted ones. Colours the
    user changed stay; a renderer the user replaced is left alone."""
    r = layer.renderer()
    if not isinstance(r, QgsCategorizedSymbolRenderer) or r.classAttribute() != "feature_id":
        return
    wanted = {f.id: f for f in features}
    for i in reversed(range(len(r.categories()))):
        if r.categories()[i].value() not in wanted:
            r.deleteCategory(i)
    have = {c.value(): i for i, c in enumerate(r.categories())}
    for fid, feat in wanted.items():
        if fid in have:
            r.updateCategoryLabel(have[fid], entity_label(feat))
        else:
            r.addCategory(QgsRendererCategory(fid, _entity_symbol(layer.geometryType(),
                                                                  _entity_rgb(len(r.categories()))),
                                              entity_label(feat)))


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
        if name == "interp_features":
            # only the current version is editable here; frozen copies stay out of reach
            layer.setSubsetString(f"\"version_id\" = '{store.current_version().id}'")
        else:
            default_style(layer)
            sync_categories(layer, store.features(store.current_version().id))
            layer.setReadOnly(True)
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        have[name] = layer
    return have


def reload_interp_layers(store: ProjectStore, project: QgsProject) -> None:
    features = store.features(store.current_version().id) if store.has_interpretation() else []
    for name, layer in interp_layers(store, project).items():
        if name != "interp_features":
            sync_categories(layer, features)
            layer.emitStyleChanged()            # the legend lists the entities
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
            self.store.drop_orphan_pieces(self.version_id())
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
