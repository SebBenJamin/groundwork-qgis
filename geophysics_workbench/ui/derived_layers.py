"""Derived electrodes on the map: one temporary layer, never stored in the GeoPackage.

A profile without a station set has its electrode positions worked out at draw time (from
the readings file, a typed spacing, or a guess from the model). They are shown as the memory
layer ``electrodes (derived)`` in the "Geophysics Workbench" group below ``stations``, so
they can be compared with the real positions. The layer is refilled whenever the provider
reports a change and removed when no profile has derived electrodes. Its style is the
user's: the default is built from the ``stations`` layer's symbol, and a changed style is
kept as QML in the project entry ``geophysics_workbench/derived_style``."""
from __future__ import annotations

from qgis.core import (QgsCategorizedSymbolRenderer, QgsFeature, QgsGeometry, QgsMarkerSymbol,
                       QgsPointXY, QgsProject, QgsRendererCategory, QgsVectorLayer)
from qgis.PyQt.QtXml import QDomDocument

from .project_actions import GROUP_NAME, SCOPE, store_layers

DERIVED_NAME = "electrodes (derived)"
STYLE_KEY = "derived_style"
_FLAG = "geophysics_workbench/derived"          # custom property marking the layer
_defaults: dict[str, str] = {}      # layer id -> the QML the layer was built with
_OPACITY = {"guessed": 0.5, "spacing": 0.75, "readings": 0.75}
_FIELDS = "&field=profile_id:string&field=profile:string&field=number:string&field=kind:string"


def derived_layer(project: QgsProject) -> QgsVectorLayer | None:
    for layer in project.mapLayers().values():
        if isinstance(layer, QgsVectorLayer) and layer.customProperty(_FLAG):
            return layer
    return None


def _number(value) -> str:
    v = float(value)
    return str(int(v)) if v.is_integer() else str(v)


def _rows(store, provider) -> list[tuple]:
    """(profile_id, name, number, kind, x, y) of every derived electrode."""
    rows = []
    for profile in store.profiles():
        try:
            found = provider.electrodes(profile.id)
        except Exception:                           # not workable for this profile: skip it
            continue
        if found is None or found.kind == "imported" or not len(found.chainage):
            continue
        xy = profile.chainage.to_xy(found.chainage)
        for n, (x, y) in zip(found.numbers, xy):
            rows.append((profile.id, profile.name, _number(n), found.kind, float(x), float(y)))
    return rows


def _default_renderer(project: QgsProject, store):
    base = None
    stations = store_layers(store, project).get("stations")
    if stations is not None and hasattr(stations.renderer(), "symbol"):
        base = stations.renderer().symbol()
    categories = []
    for kind, opacity in _OPACITY.items():
        symbol = base.clone() if base is not None else QgsMarkerSymbol.createSimple({})
        symbol.setOpacity(opacity)
        categories.append(QgsRendererCategory(kind, symbol, kind))
    return QgsCategorizedSymbolRenderer("kind", categories)


def _qml(layer: QgsVectorLayer) -> str:
    doc = QDomDocument()
    layer.exportNamedStyle(doc)
    return doc.toString()


def _restore_style(layer: QgsVectorLayer, project: QgsProject) -> None:
    qml = project.readEntry(SCOPE, STYLE_KEY, "")[0]
    if not qml:
        return
    doc = QDomDocument()
    if doc.setContent(qml):
        layer.importNamedStyle(doc)


def save_style(project: QgsProject) -> None:
    """Keep the layer's QML in the project, only when the user changed it from the default
    (an unchanged layer is rebuilt from the stations' symbol)."""
    layer = derived_layer(project)
    if layer is None:
        return
    qml = _qml(layer)
    entry = "" if qml == _defaults.get(layer.id()) else qml
    if project.readEntry(SCOPE, STYLE_KEY, "")[0] != entry:
        project.writeEntry(SCOPE, STYLE_KEY, entry)


def _create(store, project: QgsProject) -> QgsVectorLayer:
    layer = QgsVectorLayer(f"Point?crs={store.crs_authid}{_FIELDS}", DERIVED_NAME, "memory")
    layer.setCustomProperty(_FLAG, True)
    layer.setReadOnly(True)
    layer.setCustomProperty("skipMemoryLayersCheck", 1)    # no "scratch layer" warning on close
    layer.setRenderer(_default_renderer(project, store))
    project.addMapLayer(layer, False)
    root = project.layerTreeRoot()
    group = root.findGroup(GROUP_NAME) or root.insertGroup(0, GROUP_NAME)
    stations = store_layers(store, project).get("stations")
    node = None if stations is None else group.findLayer(stations.id())
    index = group.children().index(node) + 1 if node is not None else len(group.children())
    group.insertLayer(index, layer)
    _defaults[layer.id()] = _qml(layer)   # as it is in the project: what save_style compares
    _restore_style(layer, project)
    layer.rendererChanged.connect(lambda: save_style(project))
    return layer


def _contents(layer: QgsVectorLayer) -> list[tuple]:
    return sorted((f["profile_id"], f["profile"], f["number"], f["kind"],
                   round(f.geometry().asPoint().x(), 6), round(f.geometry().asPoint().y(), 6))
                  for f in layer.getFeatures())


def sync(store, provider, project: QgsProject, create: bool = True) -> QgsVectorLayer | None:
    """Create (only when ``create``) or refill the derived layer; remove it when nothing is
    derived. A layer the user removed stays gone until the store is opened again. Returns
    the layer."""
    layer = derived_layer(project)
    if layer is None and not create:
        return None
    rows = _rows(store, provider)
    if not rows:
        if layer is not None:
            project.removeMapLayer(layer.id())
        return None
    if layer is None:
        layer = _create(store, project)
    elif _contents(layer) == sorted((r[0], r[1], r[2], r[3], round(r[4], 6), round(r[5], 6))
                                    for r in rows):
        return layer                                # nothing changed: no refill, no repaint
    layer.dataProvider().truncate()
    features = []
    for pid, name, number, kind, x, y in rows:
        f = QgsFeature(layer.fields())
        f.setAttributes([pid, name, number, kind])
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        features.append(f)
    layer.dataProvider().addFeatures(features)
    layer.updateExtents()
    layer.triggerRepaint()
    return layer
