"""Show in 3D: the models and boreholes the user ticked, as two temporary layers for QGIS's
3D view (and Qgis2threejs), never stored in the GeoPackage.

"Models in 3D" holds one vertical 3D polygon per model cell under its profile, coloured as
the section draws it; "Boreholes in 3D" one vertical 3D line per log interval of the
boreholes the ticked profiles' sections show, at their map position. The choice lives in
the project (entry ``view3d``); the layers are refilled from it whenever the data, the
section's colour scale or its fade change, and when the store is opened. Their styles (2D
and 3D) are written once when a layer is created and are the user's afterwards; they travel
with the project file like any layer's."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from qgis.core import (Qgis, QgsFeature, QgsFeatureRequest, QgsFillSymbol, QgsGeometry,
                       QgsLineString, QgsLineSymbol, QgsMessageLog, QgsPoint, QgsPolygon,
                       QgsProject, QgsProperty, QgsSingleSymbolRenderer, QgsSymbolLayer,
                       QgsVectorLayer)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

from ..ids import LEGACY_ID
from .project_actions import SCOPE, plugin_group

MODELS_NAME = "Models in 3D"
BOREHOLES_NAME = "Boreholes in 3D"
ENTRY = "view3d"
_FLAG = f"{LEGACY_ID}/view3d"              # custom property: "models" or "boreholes"
#: features one 3D chunk may hold: QGIS shows a layer split into chunks in pieces when
#: zoomed out, so a curtain layer is kept in one chunk
MAX_CHUNK = 5_000_000
_MODEL_FIELDS = ("&field=profile_id:string&field=profile:string&field=dataset_id:string"
                 "&field=dataset:string&field=value:double&field=coverage:double"
                 "&field=resolved:integer&field=color:string")
_BOREHOLE_FIELDS = ("&field=profile_id:string&field=borehole:string&field=layer:string"
                    "&field=top:double&field=bottom:double&field=text:string"
                    "&field=color:string")
#: layer id -> {dataset id: signature of what its cells were made from}
_built: dict[str, dict] = {}


@dataclass(frozen=True)
class Choice:
    models: frozenset = field(default_factory=frozenset)       # dataset ids
    boreholes: frozenset = field(default_factory=frozenset)    # profile ids


def read_choice(project: QgsProject) -> Choice:
    text = project.readEntry(SCOPE, ENTRY, "")[0]
    try:
        data = json.loads(text) if text else {}
        return Choice(frozenset(str(i) for i in data.get("models", [])),
                      frozenset(str(i) for i in data.get("boreholes", [])))
    except (ValueError, AttributeError, TypeError):
        return Choice()


def write_choice(project: QgsProject, choice: Choice) -> None:
    project.writeEntry(SCOPE, ENTRY, json.dumps({"models": sorted(choice.models),
                                                 "boreholes": sorted(choice.boreholes)}))


def layers_3d(project: QgsProject) -> dict[str, QgsVectorLayer]:
    """The 3D layers in the project by kind ("models", "boreholes")."""
    out = {}
    for layer in project.mapLayers().values():
        kind = layer.customProperty(_FLAG) if isinstance(layer, QgsVectorLayer) else None
        if kind in ("models", "boreholes"):
            out[kind] = layer
    return out


def _log(message: str) -> None:
    QgsMessageLog.logMessage(message, "Groundwork", Qgis.MessageLevel.Warning)


# -- styles ---------------------------------------------------------------------------------
def _colour_material():
    from qgis._3d import QgsAbstractMaterialSettings, QgsPhongMaterialSettings
    material = QgsPhongMaterialSettings()
    props = material.dataDefinedProperties()
    for prop in (QgsAbstractMaterialSettings.Property.Diffuse,
                 QgsAbstractMaterialSettings.Property.Ambient):
        props.setProperty(prop, QgsProperty.fromField("color"))
    material.setDataDefinedProperties(props)
    material.setShininess(0.0)
    return material


def _one_chunk(renderer) -> None:
    tiling = renderer.tilingSettings()
    tiling.setMaximumChunkFeatures(MAX_CHUNK)
    renderer.setTilingSettings(tiling)


def _style_models(layer: QgsVectorLayer) -> None:
    from qgis._3d import QgsPolygon3DSymbol, QgsVectorLayer3DRenderer
    fill = QgsFillSymbol.createSimple({"outline_style": "no"})
    fill.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.FillColor,
                                               QgsProperty.fromField("color"))
    layer.setRenderer(QgsSingleSymbolRenderer(fill))
    symbol = QgsPolygon3DSymbol()
    symbol.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
    symbol.setExtrusionHeight(0.0)
    symbol.setAddBackFaces(True)
    symbol.setMaterialSettings(_colour_material())
    renderer = QgsVectorLayer3DRenderer(symbol)
    _one_chunk(renderer)
    layer.setRenderer3D(renderer)


def _style_boreholes(layer: QgsVectorLayer) -> None:
    from qgis._3d import QgsLine3DSymbol, QgsVectorLayer3DRenderer
    line = QgsLineSymbol.createSimple({})
    line.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.StrokeColor,
                                               QgsProperty.fromField("color"))
    layer.setRenderer(QgsSingleSymbolRenderer(line))
    symbol = QgsLine3DSymbol()
    symbol.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
    symbol.setRenderAsSimpleLines(False)
    symbol.setWidth(1.0)                       # metres: a column you can see beside a curtain
    symbol.setMaterialSettings(_colour_material())
    renderer = QgsVectorLayer3DRenderer(symbol)
    _one_chunk(renderer)
    layer.setRenderer3D(renderer)


def _create(store, project: QgsProject, kind: str) -> QgsVectorLayer:
    geometry, fields, name = (("PolygonZ", _MODEL_FIELDS, MODELS_NAME) if kind == "models"
                              else ("LineStringZ", _BOREHOLE_FIELDS, BOREHOLES_NAME))
    layer = QgsVectorLayer(f"{geometry}?crs={store.crs_authid}{fields}", name, "memory")
    layer.setCustomProperty(_FLAG, kind)
    layer.setCustomProperty("skipMemoryLayersCheck", 1)     # no "scratch layer" warning
    layer.setReadOnly(True)
    (_style_models if kind == "models" else _style_boreholes)(layer)
    project.addMapLayer(layer, False)
    plugin_group(project.layerTreeRoot()).addLayer(layer)
    return layer


def _layer(store, project, kind: str, wanted: bool, create: bool) -> QgsVectorLayer | None:
    """The kind's layer when ``wanted`` (created only when ``create``); else it is removed."""
    layer = layers_3d(project).get(kind)
    if not wanted:
        if layer is not None:
            _built.pop(layer.id(), None)
            project.removeMapLayer(layer.id())
        return None
    if layer is None and create:
        layer = _create(store, project, kind)
    return layer


def _edit(layer: QgsVectorLayer, drop_ids, features) -> None:
    provider = layer.dataProvider()
    if drop_ids:
        provider.deleteFeatures(list(drop_ids))
    if features:
        provider.addFeatures(features)
    layer.updateExtents()
    layer.triggerRepaint()
    try:
        layer.trigger3DUpdate()
    except AttributeError:
        pass


def _ids_where(layer: QgsVectorLayer, field_name: str, value: str) -> list[int]:
    request = QgsFeatureRequest().setFilterExpression(
        f"\"{field_name}\" = '{value.replace(chr(39), chr(39) * 2)}'")
    request.setFlags(QgsFeatureRequest.Flag.NoGeometry)
    return [f.id() for f in layer.getFeatures(request)]


# -- models ---------------------------------------------------------------------------------
def _signature(section_layer, profile) -> tuple:
    mesh, style = section_layer.mesh, section_layer.style
    sc = style.scale
    cov = mesh.coverage
    return (hash(mesh.vertices.tobytes()), hash(mesh.values.tobytes()),
            None if cov is None else hash(cov.tobytes()), hash(profile.xy.tobytes()),
            None if sc is None else (sc.cmap, sc.vmin, sc.vmax, sc.log, sc.ramp, sc.lut),
            style.fade_coverage, style.coverage_threshold)


def _threshold(section_layer) -> float | None:
    from ..core.gridding import default_threshold
    style, mesh = section_layer.style, section_layer.mesh
    if not style.fade_coverage or mesh.coverage is None:
        return None
    if style.coverage_threshold is not None:
        return float(style.coverage_threshold)
    return default_threshold(mesh.coverage, getattr(mesh, "coverage_cut", None))


def _model_features(layer, profile, dataset, section_layer) -> list[QgsFeature]:
    from ..core.colors import ColorScale
    from ..core.view3d import curtain_cells
    mesh = section_layer.mesh
    scale = section_layer.style.scale or ColorScale.auto(mesh.values)
    cells = curtain_cells(mesh, profile.chainage, scale.rgba(mesh.values),
                          _threshold(section_layer))
    out = []
    for cell in cells:
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry(QgsPolygon(QgsLineString([QgsPoint(*p) for p in cell.ring]))))
        f.setAttributes([profile.id, profile.name, dataset.id, dataset.name or dataset.id,
                         cell.value, cell.coverage, int(cell.resolved),
                         QColor(*cell.rgb).name()])
        out.append(f)
    return out


def _chosen_models(store, choice: Choice) -> list[tuple]:
    """(profile, dataset) of every chosen model that still exists."""
    out = []
    for profile in store.profiles():
        for d in store.datasets(profile.id):
            if d.id in choice.models and d.kind.endswith("_model"):
                out.append((profile, d))
    return out


def _sync_models(store, provider, project, choice: Choice, create: bool):
    chosen = _chosen_models(store, choice)
    layer = _layer(store, project, "models", bool(chosen), create)
    if layer is None:
        return None
    built = _built.get(layer.id())
    if built is None or (layer.featureCount() == 0 and built):
        built = _built[layer.id()] = {}
        layer.dataProvider().truncate()
    by_profile: dict[str, list] = {}
    for profile, d in chosen:
        if profile.id not in by_profile:
            try:
                by_profile[profile.id] = {la.dataset.id: la for la in provider.layers(profile.id)}
            except Exception as exc:
                _log(f"3D view: profile '{profile.name}' could not be built: {exc}")
                by_profile[profile.id] = {}
        section_layer = by_profile[profile.id].get(d.id)
        if section_layer is None or section_layer.mesh is None:
            if d.id in built:
                _edit(layer, _ids_where(layer, "dataset_id", d.id), [])
                built.pop(d.id)
            if section_layer is not None and section_layer.error:
                _log(f"3D view: '{d.name or d.id}' left out: {section_layer.error}")
            continue
        signature = _signature(section_layer, profile)
        if built.get(d.id) == signature:
            continue
        drop = _ids_where(layer, "dataset_id", d.id) if d.id in built else []
        _edit(layer, drop, _model_features(layer, profile, d, section_layer))
        built[d.id] = signature
    wanted = {d.id for _p, d in chosen}
    for gone in [i for i in built if i not in wanted]:
        _edit(layer, _ids_where(layer, "dataset_id", gone), [])
        built.pop(gone)
    return layer


# -- boreholes ------------------------------------------------------------------------------
def _interval_colour(text: str, symbol) -> tuple:
    """The colour the section draws an interval in: its class's fill, the outline of a
    switched-off class, or the neutral colour of an unstyled text."""
    from ..section.borehole_style import default_symbol
    symbol = symbol if symbol is not None else default_symbol(text)
    first = symbol.symbolLayer(0) if symbol.symbolLayerCount() else None
    colour = symbol.color()
    if first is not None and hasattr(first, "brushStyle") \
            and first.brushStyle() == Qt.BrushStyle.NoBrush and hasattr(first, "strokeColor"):
        colour = first.strokeColor()
    return colour.red(), colour.green(), colour.blue()


def _surface_line(provider, profile_id: str):
    """The section's drawn surface (s, z) of a profile, or None."""
    try:
        surface = provider.surface(profile_id)
    except Exception:
        return None
    return None if surface is None else surface.line


def _surface_at(line, s: float) -> float | None:
    import numpy as np
    if line is None:
        return None
    return float(np.interp(s, line[0], line[1]))


def _borehole_rows(store, provider, choice: Choice) -> list[tuple]:
    from ..core.context import borehole_key
    from ..core.view3d import borehole_intervals
    rows, seen = [], set()
    for profile in store.profiles():
        if profile.id not in choice.boreholes:
            continue
        try:
            items = provider.context(profile.id)
        except Exception as exc:
            _log(f"3D view: boreholes of '{profile.name}' could not be gathered: {exc}")
            continue
        line = None
        for point in [] if items is None else items.points:
            if point.kind != "borehole":
                continue
            key = borehole_key(point) or (round(point.x or 0, 3), round(point.y or 0, 3),
                                          point.label)
            if key in seen:
                continue
            seen.add(key)
            surface = None
            if point.z_top is None:                 # only then is the drawn surface needed
                line = _surface_line(provider, profile.id) if line is None else line
                surface = _surface_at(line, point.s)
            for iv in borehole_intervals(point, surface, _interval_colour):
                rows.append((profile.id, point.label, point.layer_id, iv))
    return rows


def _sync_boreholes(store, provider, project, choice: Choice, create: bool):
    known = {p.id for p in store.profiles()}
    wanted = bool(choice.boreholes & known)
    rows = _borehole_rows(store, provider, choice) if wanted else []
    layer = _layer(store, project, "boreholes", wanted, create)
    if layer is None:
        return None
    signature = [(pid, label, lid, iv) for pid, label, lid, iv in rows]
    built = _built.setdefault(layer.id(), {})
    if built.get("rows") == signature and layer.featureCount() == len(rows):
        return layer
    features = []
    for pid, label, lid, iv in rows:
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry(QgsLineString([QgsPoint(iv.x, iv.y, iv.z_top),
                                                 QgsPoint(iv.x, iv.y, iv.z_bottom)])))
        f.setAttributes([pid, label, lid, iv.top, iv.bottom, iv.text, QColor(*iv.rgb).name()])
        features.append(f)
    layer.dataProvider().truncate()
    _edit(layer, [], features)
    built["rows"] = signature
    return layer


def sync(store, provider, project: QgsProject, create: bool = False,
         boreholes: bool = True) -> dict[str, QgsVectorLayer]:
    """Fill the 3D layers for the project's choice: a layer is created only when ``create``
    (the user asked), and removed when its part of the choice is empty. Ids that no longer
    exist are ignored; a model that cannot be read is left out (and logged). Without
    ``boreholes`` (only a section style changed) the borehole layer is left as it is."""
    choice = read_choice(project)
    out = {}
    models = _sync_models(store, provider, project, choice, create)
    if models is not None:
        out["models"] = models
    if boreholes:
        layer = _sync_boreholes(store, provider, project, choice, create)
    else:
        layer = layers_3d(project).get("boreholes")
    if layer is not None:
        out["boreholes"] = layer
    return out
