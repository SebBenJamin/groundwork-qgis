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

from qgis.core import (Qgis, QgsFeature, QgsFillSymbol, QgsGeometry,
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
#: layer id -> {dataset id: (signature of what its cells were made from, their feature ids)}
_built: dict[str, dict] = {}
_FILLED = "groundworkFilled"            # Qt property: this layer object was filled


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
    fill = QgsFillSymbol.createSimple({"outline_style": "no"})
    fill.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.FillColor,
                                               QgsProperty.fromField("color"))
    layer.setRenderer(QgsSingleSymbolRenderer(fill))
    try:
        from qgis._3d import QgsPolygon3DSymbol, QgsVectorLayer3DRenderer
    except ImportError:                         # a QGIS built without 3D
        return
    symbol = QgsPolygon3DSymbol()
    symbol.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
    symbol.setExtrusionHeight(0.0)
    symbol.setAddBackFaces(True)
    symbol.setMaterialSettings(_colour_material())
    renderer = QgsVectorLayer3DRenderer(symbol)
    _one_chunk(renderer)
    layer.setRenderer3D(renderer)


def _style_boreholes(layer: QgsVectorLayer) -> None:
    line = QgsLineSymbol.createSimple({})
    line.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.StrokeColor,
                                               QgsProperty.fromField("color"))
    layer.setRenderer(QgsSingleSymbolRenderer(line))
    try:
        from qgis._3d import (QgsAbstractMaterialSettings, QgsLine3DSymbol,
                              QgsSimpleLineMaterialSettings, QgsVectorLayer3DRenderer)
    except ImportError:                         # a QGIS built without 3D
        return
    symbol = QgsLine3DSymbol()
    symbol.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
    # simple lines keep each vertex's height; a wide (buffered) line lies flat at height 0,
    # which turns a vertical borehole into a disc at sea level
    symbol.setRenderAsSimpleLines(True)
    symbol.setWidth(6.0)                       # pixels: a column you can see beside a curtain
    material = QgsSimpleLineMaterialSettings()
    props = material.dataDefinedProperties()
    props.setProperty(QgsAbstractMaterialSettings.Property.Ambient, QgsProperty.fromField("color"))
    material.setDataDefinedProperties(props)
    symbol.setMaterialSettings(material)
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


def _edit(layer: QgsVectorLayer, drop_ids, features) -> list[int]:
    """Delete ``drop_ids`` and add ``features`` through the provider (by id, so a filter on
    the layer never hides a feature from it); the ids of the added features."""
    provider = layer.dataProvider()
    if drop_ids:
        provider.deleteFeatures(list(drop_ids))
    added = []
    if features:
        ok, out = provider.addFeatures(features)
        added = [f.id() for f in out] if ok else []
    layer.updateExtents()
    layer.triggerRepaint()
    try:
        layer.trigger3DUpdate()
    except AttributeError:
        pass
    return added


def _fresh(layer: QgsVectorLayer) -> dict:
    """The layer's build record; a new one (and an emptied layer) when this layer object was
    never filled in this session, e.g. a memory layer read back empty from a project file.
    The mark is a Qt property, which a project file does not keep."""
    built = _built.get(layer.id())
    if built is None or not layer.property(_FILLED):
        layer.dataProvider().truncate()
        layer.setProperty(_FILLED, True)
        built = _built[layer.id()] = {}
    return built


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


def _drop(layer, built: dict, dataset_id: str) -> None:
    entry = built.pop(dataset_id, None)
    if entry is not None:
        _edit(layer, entry[1], [])


def _is_local(provider, profile_id: str) -> bool:
    try:
        return bool(provider.is_local(profile_id))
    except Exception:
        return False


def _sync_models(store, provider, project, choice: Choice, create: bool):
    chosen = _chosen_models(store, choice)
    layer = _layer(store, project, "models", bool(chosen), create)
    if layer is None:
        return None
    built = _fresh(layer)
    by_profile: dict[str, dict] = {}
    for profile, d in chosen:
        if profile.id not in by_profile:
            by_profile[profile.id] = {}
            if not _is_local(provider, profile.id):        # no real heights: not in 3D
                try:
                    by_profile[profile.id] = {la.dataset.id: la
                                              for la in provider.layers(profile.id)}
                except Exception as exc:
                    _log(f"3D view: profile '{profile.name}' could not be built: {exc}")
        section_layer = by_profile[profile.id].get(d.id)
        if section_layer is None or section_layer.mesh is None:
            _drop(layer, built, d.id)
            if section_layer is not None and section_layer.error:
                _log(f"3D view: '{d.name or d.id}' left out: {section_layer.error}")
            continue
        signature = (_signature(section_layer, profile), profile.name, d.name)
        if d.id in built and built[d.id][0] == signature:
            continue
        try:
            features = _model_features(layer, profile, d, section_layer)
        except Exception as exc:
            _log(f"3D view: '{d.name or d.id}' could not be shown: {exc}")
            _drop(layer, built, d.id)
            continue
        old = built[d.id][1] if d.id in built else []
        built[d.id] = (signature, _edit(layer, old, features))
    wanted = {d.id for _p, d in chosen}
    for gone in [i for i in built if i not in wanted]:
        _drop(layer, built, gone)
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


def _borehole_rows(store, provider, project, choice: Choice) -> list[tuple]:
    from ..core.context import borehole_key
    from ..core.view3d import borehole_intervals
    rows, seen = [], set()
    for profile in store.profiles():
        if profile.id not in choice.boreholes or _is_local(provider, profile.id):
            continue                                # a local section shows no boreholes
        try:
            items = provider.drawn_context(profile.id)
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
            source = project.mapLayer(point.layer_id) if point.layer_id else None
            name = source.name() if source is not None else ""
            for iv in borehole_intervals(point, surface, _interval_colour):
                rows.append((profile.id, point.label, name, iv))
    return rows


def _sync_boreholes(store, provider, project, choice: Choice, create: bool):
    known = {p.id for p in store.profiles()}
    wanted = bool(choice.boreholes & known)
    layer = _layer(store, project, "boreholes", wanted, create)
    if layer is None:
        return None
    rows = _borehole_rows(store, provider, project, choice)
    signature = [(pid, label, lid, iv) for pid, label, lid, iv in rows]
    built = _fresh(layer)
    built["hidden"] = _hidden(store, choice)
    if built.get("rows") == signature:
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


def _hidden(store, choice: Choice) -> tuple:
    """The boreholes hidden in the ticked profiles' sections (what a redraw may change)."""
    out = []
    for pid in sorted(choice.boreholes):
        try:
            out.append((pid, tuple(sorted(store.hidden_boreholes(pid)))))
        except Exception:
            continue
    return tuple(out)


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
    layer = layers_3d(project).get("boreholes")
    if not boreholes and layer is not None:
        # a redraw: of the boreholes, only hiding or showing one in a section can change
        boreholes = _built.get(layer.id(), {}).get("hidden") != _hidden(store, choice)
    if boreholes or layer is None:
        layer = _sync_boreholes(store, provider, project, choice, create)
    if layer is not None:
        out["boreholes"] = layer
    return out
