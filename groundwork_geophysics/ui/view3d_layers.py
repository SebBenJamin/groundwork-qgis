"""Show in 3D: the models and boreholes the user ticked, as two temporary layers for QGIS's
3D view (and Qgis2threejs), never stored in the GeoPackage.

Each ticked model stands as its section shows it ("Models in 3D" holds one vertical 3D
polygon per model cell under its profile, coloured as the section draws it; a smooth model
is a point cloud, contours are lines), as a point cloud whatever the section shows, or in
its profile's section picture (3D Tiles: the profile's picture models in one picture, as the
section stacks them, optionally with the interpretation). "Boreholes in 3D" holds one round
column per log interval of the boreholes the ticked profiles' sections show, at their map
position. "Ground in 3D" holds the section's ground line of every profile with something
ticked, so the profiles stay readable with the terrain off. The choice lives in
the project (entry ``view3d``); while a 3D view is open, the layers are refilled from it
whenever the data, the section's colour scale or its fade change, and when the store is
opened (``sync``); without one, only what was deleted is taken out (``prune``). Their styles (2D
and 3D) are written once when a layer is created and are the user's afterwards; they travel
with the project file like any layer's."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

from qgis.core import (Qgis, QgsFeature, QgsFillSymbol, QgsGeometry,
                       QgsLineString, QgsLineSymbol, QgsMessageLog, QgsPoint, QgsPolygon,
                       QgsProject, QgsProperty, QgsSingleSymbolRenderer, QgsSymbolLayer,
                       QgsVectorLayer, QgsWkbTypes)
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

from ..ids import LEGACY_ID
from .project_actions import SCOPE, plugin_group, station_radius
from .qgis_objects import as_kind, handed_over

MODELS_NAME = "Models in 3D"
BOREHOLES_NAME = "Boreholes in 3D"
CONTOURS_NAME = "Contours in 3D"
GROUND_NAME = "Ground in 3D"
NAMES_GROUP = "Profile names in 3D"
#: borehole names float this far above their column's collar; QGIS draws all texts of one
#: annotation layer at one height, so the names are grouped by collar height in steps of
#: BOREHOLE_NAME_STEP_M, one small layer per step, in this group
BOREHOLE_NAMES_GROUP = "Borehole names in 3D"
BOREHOLE_NAME_LIFT_M, BOREHOLE_NAME_STEP_M = 1.0, 0.5
#: every layer Show in 3D makes sits in this group of the plugin's, collapsed, so one tick
#: hides or shows all of them and the Layers panel stays short
VIEW3D_GROUP = "3D View"
#: a profile's name floats this far above the start of its ground line: a share of the
#: profile's length, at least NAME_LIFT_M
NAME_LIFT_SHARE, NAME_LIFT_M = 0.03, 1.0
SMOOTH_GROUP = "Smooth models in 3D"
PICTURES_GROUP = "Section pictures in 3D"
#: how a ticked model stands in 3D: as its section shows it (cells, a point cloud or contour
#: lines, by its display there), as a point cloud whatever the section shows (with the
#: section's contour lines when it shows them), or in its profile's section picture
REPRESENTATIONS = ("section", "cloud", "picture")
ENTRY = "view3d"
#: project entry: the kinds of 3D layer the plugin has made in this project (a kind new in an
#: update is made when needed; one the user removed is not made again by itself)
ENTRY_MADE = "view3d_made"
_FLAG = f"{LEGACY_ID}/view3d"              # custom property: "models", "boreholes", ... "cloud"
_DATASET = f"{LEGACY_ID}/view3d_dataset"   # a cloud's dataset id
_PROFILE = f"{LEGACY_ID}/view3d_profile"   # a section picture's profile id
_NAME_ITEM = f"{LEGACY_ID}/view3d_name_item"   # a name layer: the id of the plugin's text
_CALLOUTS_SET = f"{LEGACY_ID}/view3d_callouts_set"   # a name layer: callouts switched off once
_GIVEN_NAME = f"{LEGACY_ID}/view3d_given_name"  # a picture: the layer name the plugin gave
_HEIGHT = f"{LEGACY_ID}/view3d_height"     # a borehole names layer: its collar height step
_NEEDS = "groundwork3dNeeds"            # Qt property on the project: what the last sync showed
#: points of a smooth curtain are at least this far apart (m), along and across
CLOUD_SPACING = 0.05
_SMOOTH, _LINES = ("smooth", "smooth+contours"), ("contours", "smooth+contours")
#: features one 3D chunk may hold: QGIS shows a layer split into chunks in pieces when
#: zoomed out, so a curtain layer is kept in one chunk
MAX_CHUNK = 5_000_000
_MODEL_FIELDS = ("&field=profile_id:string&field=profile:string&field=dataset_id:string"
                 "&field=dataset:string&field=value:double&field=coverage:double"
                 "&field=resolved:integer&field=color:string&field=faded:integer")
#: a cell the section fades (``faded`` = 1) is drawn this see-through in 3D: the 3D style's
#: rule for it (the section's own floor, FADE_ALPHA)
FADED_RULE, OPAQUE_RULE = '"faded" = 1', 'coalesce("faded", 0) <> 1'
_BOREHOLE_FIELDS = ("&field=profile_id:string&field=borehole:string&field=layer:string"
                    "&field=top:double&field=bottom:double&field=text:string"
                    "&field=color:string&field=height:double")
_CONTOUR_FIELDS = ("&field=profile_id:string&field=profile:string&field=dataset_id:string"
                   "&field=dataset:string&field=level:double&field=color:string")
_GROUND_FIELDS = "&field=profile_id:string&field=profile:string"
#: a section picture's 2D visibility ends at this scale (1:1): the 2D map would decode its
#: textures on every redraw to draw nothing useful; the 3D view ignores scale ranges
PICTURE_2D_SCALE = 1.0
#: layer id -> {dataset id: (signature of what its cells were made from, their feature ids)}
_built: dict[str, dict] = {}
_FILLED = "groundworkFilled"            # Qt property: this layer object was filled


@dataclass(frozen=True)
class Choice:
    models: frozenset = field(default_factory=frozenset)       # dataset ids
    boreholes: frozenset = field(default_factory=frozenset)    # profile ids
    #: dataset id -> "cloud" or "picture"; a model not in it stands as its section shows it
    looks: dict = field(default_factory=dict, hash=False)
    interpretation: bool = False        # the section pictures show the interpretation
    borehole_width: float | None = None     # the columns' diameter (m); None: automatic
    station_size: float | None = None       # the station spheres' diameter (m); None: automatic

    def __post_init__(self):
        looks = {str(k): v for k, v in dict(self.looks or {}).items()
                 if v in REPRESENTATIONS[1:]}
        object.__setattr__(self, "looks", looks)

    def look_of(self, dataset_id: str) -> str:
        """The dataset's representation, one of ``REPRESENTATIONS``."""
        return self.looks.get(dataset_id, REPRESENTATIONS[0])


def _size(value) -> float | None:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return None
    return size if np.isfinite(size) and size > 0 else None


def read_choice(project: QgsProject) -> Choice:
    text = project.readEntry(SCOPE, ENTRY, "")[0]
    try:
        data = json.loads(text) if text else {}
        models = frozenset(str(i) for i in data.get("models", []))
        looks = data.get("looks")
        if not isinstance(looks, dict):          # saved before a look per model
            looks = {m: "picture" for m in models} if data.get("look") == "pictures" else {}
        return Choice(models, frozenset(str(i) for i in data.get("boreholes", [])), looks,
                      bool(data.get("interpretation", False)),
                      _size(data.get("borehole_width")), _size(data.get("station_size")))
    except (ValueError, AttributeError, TypeError):
        return Choice()


def write_choice(project: QgsProject, choice: Choice) -> None:
    project.writeEntry(SCOPE, ENTRY, json.dumps({
        "models": sorted(choice.models), "boreholes": sorted(choice.boreholes),
        "looks": dict(sorted(choice.looks.items())), "interpretation": choice.interpretation,
        "borehole_width": choice.borehole_width, "station_size": choice.station_size}))


def auto_borehole_width(store) -> float:
    """The borehole columns' diameter (m) without a chosen width: from the station spacing."""
    return 4 * station_radius(store)


def auto_station_size(store) -> float:
    """The station spheres' diameter (m) without a chosen size: from the station spacing."""
    return 2 * station_radius(store)


def layers_3d(project: QgsProject) -> dict[str, QgsVectorLayer]:
    """The 3D vector layers in the project by kind ("models", "boreholes", "contours",
    "ground")."""
    out = {}
    for layer in project.mapLayers().values():
        kind = layer.customProperty(_FLAG) if isinstance(layer, QgsVectorLayer) else None
        if kind in _KINDS:
            out[kind] = layer
    return out


def clouds_3d(project: QgsProject) -> dict:
    """The point-cloud curtains in the project by dataset id."""
    from qgis.core import QgsPointCloudLayer
    return {layer.customProperty(_DATASET): layer for layer in project.mapLayers().values()
            if isinstance(layer, QgsPointCloudLayer) and layer.customProperty(_FLAG) == "cloud"}


def _picture_layers(project: QgsProject) -> list:
    from qgis.core import QgsTiledSceneLayer
    return [layer for layer in project.mapLayers().values()
            if isinstance(layer, QgsTiledSceneLayer)
            and layer.customProperty(_FLAG) == "picture"]


def pictures_3d(project: QgsProject) -> dict:
    """The section pictures (3D Tiles) in the project by profile id."""
    return {layer.customProperty(_PROFILE): layer for layer in _picture_layers(project)
            if layer.customProperty(_PROFILE)}


def cloud_folder(store) -> Path:
    """Where the point-cloud curtains are written: ``<store stem>_3d`` beside the store."""
    path = Path(store.path)
    return path.with_name(f"{path.stem}_3d")


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
    _style_models_3d(layer)


def _style_models_3d(layer: QgsVectorLayer) -> None:
    """Each cell in its section colour; a cell the section fades as see-through as there."""
    try:
        from qgis._3d import Qgs3DTypes, QgsPolygon3DSymbol, QgsRuleBased3DRenderer
    except ImportError:                         # a QGIS built without 3D
        return
    from ..core.gridding import FADE_ALPHA
    root = QgsRuleBased3DRenderer.Rule(None)
    for expression, opacity, text in ((OPAQUE_RULE, 1.0, "Cells"),
                                      (FADED_RULE, FADE_ALPHA, "Faded cells (low coverage)")):
        symbol = QgsPolygon3DSymbol()
        symbol.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
        symbol.setExtrusionHeight(0.0)
        # each cell is two faces a little behind the plane on either side; hiding back
        # faces leaves the one behind, so an interpretation drawn in the plane is in front
        symbol.setAddBackFaces(False)
        symbol.setCullingMode(Qgs3DTypes.CullingMode.Back)
        material = _colour_material()
        material.setOpacity(opacity)
        symbol.setMaterialSettings(material)
        root.appendChild(QgsRuleBased3DRenderer.Rule(symbol, expression, text))
    renderer = QgsRuleBased3DRenderer(root)
    _one_chunk(renderer)
    layer.setRenderer3D(renderer)


def _plain_models_3d(layer: QgsVectorLayer) -> bool:
    """The cells' 3D style is the plugin's own from before faded cells: one symbol coloured
    by the "color" field (a style of the user's own is anything else, and stays)."""
    renderer = layer.renderer3D()
    if renderer is None or renderer.type() != "vector":
        return False
    try:
        from qgis._3d import QgsAbstractMaterialSettings, QgsVectorLayer3DRenderer
        from qgis.PyQt import sip
        symbol = sip.cast(renderer, QgsVectorLayer3DRenderer).symbol()
        prop = symbol.materialSettings().dataDefinedProperties().property(
            QgsAbstractMaterialSettings.Property.Diffuse)
    except Exception:                           # an odd renderer: the user's
        return False
    return prop.isActive() and prop.field() == "color"


def _upgrade_models(layer: QgsVectorLayer) -> None:
    """A cells layer made before faded cells: the "faded" field (and a refill), and the
    see-through style for them while its 3D style is still the plugin's plain one."""
    if layer.fields().indexOf("faded") < 0:
        from qgis.core import QgsField
        from qgis.PyQt.QtCore import QMetaType
        layer.dataProvider().addAttributes([QgsField("faded", QMetaType.Type.Int)])
        layer.updateFields()
        layer.dataProvider().truncate()
        _built.pop(layer.id(), None)
    if _plain_models_3d(layer):
        _style_models_3d(layer)


def _style_boreholes(layer: QgsVectorLayer) -> None:
    """Each interval a round column in its colour: the base extruded by the "height" field
    (a polygon, so the 3D view can identify it; lines cannot be picked there)."""
    fill = QgsFillSymbol.createSimple({"outline_style": "no"})
    fill.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.FillColor,
                                               QgsProperty.fromField("color"))
    layer.setRenderer(QgsSingleSymbolRenderer(fill))
    try:
        from qgis._3d import QgsPolygon3DSymbol, QgsVectorLayer3DRenderer
    except ImportError:                         # a QGIS built without 3D
        return
    from qgis.core import QgsAbstract3DSymbol
    symbol = QgsPolygon3DSymbol()
    symbol.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
    props = symbol.dataDefinedProperties()
    props.setProperty(QgsAbstract3DSymbol.Property.ExtrusionHeight,
                      QgsProperty.fromField("height"))
    symbol.setDataDefinedProperties(props)
    symbol.setMaterialSettings(_colour_material())
    renderer = QgsVectorLayer3DRenderer(symbol)
    _one_chunk(renderer)
    layer.setRenderer3D(renderer)


def _style_contours(layer: QgsVectorLayer) -> None:
    _style_lines(layer, 2.0)


def _style_ground(layer: QgsVectorLayer) -> None:
    from ..section.profile_source import GROUND_COLOUR
    _style_lines(layer, 2.0, QColor(GROUND_COLOUR))


def _style_lines(layer: QgsVectorLayer, width: float, colour: QColor | None = None) -> None:
    """Lines in their "color" field's colour, or all in ``colour``; in 3D as simple lines."""
    line = QgsLineSymbol.createSimple({})
    if colour is None:
        line.symbolLayer(0).setDataDefinedProperty(QgsSymbolLayer.Property.StrokeColor,
                                                   QgsProperty.fromField("color"))
    else:
        line.setColor(colour)
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
    symbol.setWidth(width)                     # pixels
    material = QgsSimpleLineMaterialSettings()
    if colour is None:
        props = material.dataDefinedProperties()
        props.setProperty(QgsAbstractMaterialSettings.Property.Ambient,
                          QgsProperty.fromField("color"))
        material.setDataDefinedProperties(props)
    else:
        material.setAmbient(colour)
    symbol.setMaterialSettings(material)
    renderer = QgsVectorLayer3DRenderer(symbol)
    _one_chunk(renderer)
    layer.setRenderer3D(renderer)


_KINDS = {"models": ("MultiPolygonZ", _MODEL_FIELDS, MODELS_NAME, _style_models),
          "boreholes": ("PolygonZ", _BOREHOLE_FIELDS, BOREHOLES_NAME, _style_boreholes),
          "contours": ("LineStringZ", _CONTOUR_FIELDS, CONTOURS_NAME, _style_contours),
          "ground": ("LineStringZ", _GROUND_FIELDS, GROUND_NAME, _style_ground)}
#: the kinds the project's "made" record knows (a kind new in an update comes by itself)
_MADE_KINDS = set(_KINDS) | {"names", "bhnames"}


def _view3d_group(project: QgsProject):
    """The plugin's "3D View" group (made collapsed when missing)."""
    top = plugin_group(project.layerTreeRoot())
    group = top.findGroup(VIEW3D_GROUP)
    if group is None:
        group = top.addGroup(VIEW3D_GROUP)
        group.setExpanded(False)
    return group


def _subgroup(project: QgsProject, name: str):
    """A group in "3D View" (made collapsed when missing)."""
    parent = _view3d_group(project)
    group = parent.findGroup(name)
    if group is None:
        group = parent.addGroup(name)
        group.setExpanded(False)
    return group


def _is_3d_layer(layer) -> bool:
    return layer is not None and layer.customProperty(_FLAG) in (
        *_KINDS, "cloud", "picture", "name", "bhname")


def _settle_groups(project: QgsProject) -> None:
    """Move the 3D layers and groups an older version put straight into the plugin's group
    into "3D View"; ones the user moved anywhere else stay where they are."""
    top = plugin_group(project.layerTreeRoot())
    from qgis.core import QgsLayerTreeGroup, QgsLayerTreeLayer
    loose = [node for node in top.children()
             if (isinstance(node, QgsLayerTreeLayer) and _is_3d_layer(node.layer()))
             or (isinstance(node, QgsLayerTreeGroup)
                 and node.name() in (SMOOTH_GROUP, PICTURES_GROUP, NAMES_GROUP,
                                     BOREHOLE_NAMES_GROUP))]
    if not loose:
        return
    group = _view3d_group(project)
    for node in loose:
        group.addChildNode(node.clone())
        top.removeChildNode(node)


def _create(store, project: QgsProject, kind: str) -> QgsVectorLayer:
    geometry, fields, name, style = _KINDS[kind]
    layer = QgsVectorLayer(f"{geometry}?crs={store.crs_authid}{fields}", name, "memory")
    layer.setCustomProperty(_FLAG, kind)
    layer.setCustomProperty("skipMemoryLayersCheck", 1)     # no "scratch layer" warning
    layer.setReadOnly(True)
    style(layer)
    project.addMapLayer(layer, False)
    _view3d_group(project).addLayer(layer)
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
            style.fade_coverage, style.coverage_threshold, style.fade_mode)


def _threshold(section_layer) -> float | None:
    from ..core.gridding import default_threshold
    style, mesh = section_layer.style, section_layer.mesh
    if not style.fade_coverage or mesh.coverage is None:
        return None
    if style.coverage_threshold is not None:
        return float(style.coverage_threshold)
    return default_threshold(mesh.coverage, getattr(mesh, "coverage_cut", None))


def _model_features(layer, profile, dataset, section_layer, gap: float) -> list[QgsFeature]:
    from qgis.core import QgsMultiPolygon

    from ..core.colors import ColorScale
    from ..core.view3d import curtain_cells
    mesh = section_layer.mesh
    scale = section_layer.style.scale or ColorScale.auto(mesh.values)
    cells = curtain_cells(mesh, profile.chainage, scale.rgba(mesh.values),
                          _threshold(section_layer), gap,
                          keep_faded=section_layer.style.fade_mode != "blank")
    out = []
    for cell in cells:
        f = QgsFeature(layer.fields())
        both = QgsMultiPolygon()
        for face in cell.faces:
            both.addGeometry(QgsPolygon(QgsLineString([QgsPoint(*p) for p in face])))
        f.setGeometry(QgsGeometry(both))
        f.setAttributes([profile.id, profile.name, dataset.id, dataset.name or dataset.id,
                         cell.value, cell.coverage, int(cell.resolved),
                         QColor(*cell.rgb).name(), int(cell.faded)])
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


def _gather(store, provider, choice: Choice) -> list[tuple]:
    """(profile, dataset, section layer or None) of every chosen model that still exists;
    None for a model on a local profile (no real heights: not in 3D) or one whose profile
    could not be read (logged)."""
    out, by_profile = [], {}
    for profile, d in _chosen_models(store, choice):
        if profile.id not in by_profile:
            by_profile[profile.id] = {}
            if not _is_local(provider, profile.id):
                try:
                    by_profile[profile.id] = {la.dataset.id: la
                                              for la in provider.layers(profile.id)}
                except Exception as exc:
                    _log(f"3D view: profile '{profile.name}' could not be built: {exc}")
        out.append((profile, d, by_profile[profile.id].get(d.id)))
    return out


def _shown(section_layer) -> bool:
    return section_layer is not None and section_layer.mesh is not None


def _as_cells(section_layer) -> bool:
    """Cells unless the section draws the model smooth or as contours."""
    return section_layer.style.mode not in _SMOOTH + _LINES


def _stack_gaps(provider, cells, pictured) -> tuple[dict, dict]:
    """How far each curtain stands back from its profile's plane, so that no two share one
    and flicker: the cell models (by dataset id) and the section picture (by profile id) of
    a profile, in the section's stacking order, the top one closest (``curtain_gap``) and
    each one below a gap further back."""
    from ..core.view3d import curtain_gap
    by_profile: dict = {}
    for profile, d, _la in cells:
        by_profile.setdefault(profile.id, (profile, set(), set()))[1].add(d.id)
    for profile, d, _la in pictured:
        by_profile.setdefault(profile.id, (profile, set(), set()))[2].add(d.id)
    cell_gaps, picture_gaps = {}, {}
    for pid, (profile, cell_ids, picture_ids) in by_profile.items():
        try:
            order = {la.dataset.id: i for i, la in enumerate(provider.layers(pid))}
        except Exception:                       # unreadable: any order, still apart
            order = {}
        items = [(order.get(did, -1), did) for did in cell_ids]
        if picture_ids:
            items.append((max(order.get(did, -1) for did in picture_ids), ""))
        items.sort(reverse=True)                # the top one first
        base = curtain_gap(profile.chainage.length)
        for k, (_i, did) in enumerate(items):
            if did:
                cell_gaps[did] = base * (k + 1)
            else:
                picture_gaps[pid] = base * (k + 1)
    return cell_gaps, picture_gaps


def _sync_models(store, project, chosen, create: bool, gaps: dict):
    """The cells of ``chosen`` (those shown as cells) in "Models in 3D", each model's faces
    ``gaps[dataset id]`` back from the plane."""
    from ..core.view3d import curtain_gap
    old = layers_3d(project).get("models")
    if old is not None and not QgsWkbTypes.isMultiType(old.wkbType()):
        _built.pop(old.id(), None)                  # saved while cells were one face
        project.removeMapLayer(old.id())
        create = True
    layer = _layer(store, project, "models", bool(chosen), create)
    if layer is None:
        return None
    _upgrade_models(layer)
    built = _fresh(layer)
    for profile, d, section_layer in chosen:
        if not _shown(section_layer):
            _drop(layer, built, d.id)
            if section_layer is not None and section_layer.error:
                _log(f"3D view: '{d.name or d.id}' left out: {section_layer.error}")
            continue
        gap = gaps.get(d.id) or curtain_gap(profile.chainage.length)
        signature = (_signature(section_layer, profile), profile.name, d.name, gap)
        if d.id in built and built[d.id][0] == signature:
            continue
        try:
            features = _model_features(layer, profile, d, section_layer, gap)
        except Exception as exc:
            _log(f"3D view: '{d.name or d.id}' could not be shown: {exc}")
            _drop(layer, built, d.id)
            continue
        old = built[d.id][1] if d.id in built else []
        built[d.id] = (signature, _edit(layer, old, features))
    wanted = {d.id for _p, d, _la in chosen}
    for gone in [i for i in built if i not in wanted]:
        _drop(layer, built, gone)
    return layer


# -- smooth models as point clouds, contours as lines ---------------------------------------
def _field(section_layer, topo):
    """The section's smooth grid of the model and the colour scale it is drawn with."""
    from ..core.colors import ColorScale
    from ..core.view3d import field_grid
    style = section_layer.style
    scale = style.scale or ColorScale.auto(section_layer.mesh.values)
    grid = field_grid(section_layer.mesh, topo, replace(style, scale=scale),
                      _threshold(section_layer))
    return grid, scale


def _cloud_signature(section_layer, profile, topo) -> str:
    """A short stable fingerprint of what a cloud is made of (also its file name)."""
    mesh, style = section_layer.mesh, section_layer.style
    sc = style.scale
    h = hashlib.sha1()
    for a in (mesh.vertices, mesh.values, mesh.coverage, profile.xy,
              *(() if topo is None else topo)):
        if a is not None:
            h.update(np.ascontiguousarray(a, dtype=float).tobytes())
    h.update(repr((None if sc is None else (sc.cmap, sc.vmin, sc.vmax, sc.log, sc.ramp, sc.lut),
                   style.grid_cell, style.fade_coverage, style.coverage_threshold,
                   style.fade_mode, CLOUD_SPACING)).encode())
    return h.hexdigest()[:10]


def _write_cloud(path: Path, store, profile, section_layer, topo) -> int:
    """The model's smooth field as a LAS file at ``path``; the number of points (0: none)."""
    from qgis.core import QgsCoordinateReferenceSystem

    from ..core.las import write_las
    from ..core.view3d import field_points
    grid, scale = _field(section_layer, topo)
    pts = field_points(grid, profile.chainage, scale, CLOUD_SPACING)
    if not len(pts.value):
        return 0
    wkt = QgsCoordinateReferenceSystem(store.crs_authid).toWkt(Qgis.CrsWktVariant.Wkt1Gdal)
    with np.errstate(divide="ignore", invalid="ignore"):
        log10 = np.log10(np.where(pts.value > 0, pts.value, np.nan))
    path.parent.mkdir(parents=True, exist_ok=True)
    write_las(path, pts.xyz, pts.rgb, {"Value": pts.value, "Log10Value": log10}, wkt)
    return len(pts.value)


def _smooth_group(project: QgsProject):
    return _subgroup(project, SMOOTH_GROUP)


def _new_cloud(project: QgsProject, path: Path, name: str, dataset_id: str):
    from qgis.core import QgsPointCloudLayer, QgsPointCloudRgbRenderer
    layer = QgsPointCloudLayer(str(path), name, "pdal")
    rgb = QgsPointCloudRgbRenderer()                # the section's own colours
    rgb.setRedAttribute("Red")
    rgb.setGreenAttribute("Green")
    rgb.setBlueAttribute("Blue")
    layer.setRenderer(rgb)
    layer.setCustomProperty(_FLAG, "cloud")
    layer.setCustomProperty(_DATASET, dataset_id)
    try:
        from qgis._3d import QgsPointCloudLayer3DRenderer
        renderer = QgsPointCloudLayer3DRenderer()
        renderer.convertFrom2DRenderer(rgb)
        layer.setRenderer3D(renderer)
        layer.setSync3DRendererTo2DRenderer(True)   # the 3D look follows the 2D style
    except ImportError:                             # a QGIS built without 3D
        pass
    project.addMapLayer(layer, False)
    _smooth_group(project).addLayer(layer)
    return layer


#: curtain files this session moved a cloud away from, deleted once nothing holds them
_stale: set[Path] = set()
#: <dataset id>-<signature>.las (a cloud) or .json (a picture's tileset)
_OWN_NAME = re.compile(r".+-[0-9a-f]{10}\.(las|json)$")


def _companions(path: Path) -> set:
    """A curtain file with the files that belong to it: QGIS's index of a cloud, the glTF
    of a tileset."""
    if path.suffix == ".las":
        return {path, path.with_name(path.name[:-4] + ".copc.laz")}
    return {path, path.with_suffix(".glb")}


def _let_go(path: Path) -> None:
    """Mark a curtain file the plugin wrote (and what belongs to it) for deletion; never a
    file it did not write."""
    if _OWN_NAME.match(path.name):
        _stale.update(_companions(path))


def _delete_stale(in_use: set) -> None:
    """Delete the curtain files let go of that no cloud uses; a file QGIS still holds open
    stays marked for a later sync."""
    for path in list(_stale):
        if path in in_use:
            _stale.discard(path)
            continue
        try:
            path.unlink(missing_ok=True)
            _stale.discard(path)
        except OSError:
            pass


def _drop_cloud(project, layer) -> None:
    _let_go(Path(layer.source()))
    project.removeMapLayer(layer.id())


def _sync_clouds(store, provider, project, chosen, may_create, retry, topo_of) -> dict:
    """A point cloud for each of ``chosen`` (shown models standing as a cloud)."""
    wanted = {d.id: (p, d, la) for p, d, la in chosen}
    existing = clouds_3d(project)
    for did, layer in existing.items():
        if did not in wanted:
            _drop_cloud(project, layer)
    folder = cloud_folder(store)
    out = {}
    for did, (profile, d, section_layer) in wanted.items():
        layer = existing.get(did)
        allowed = may_create(f"cloud:{did}")       # noted for every cloud shown
        if layer is None and not allowed:
            continue                            # e.g. the user removed it
        topo = topo_of(profile.id)
        failed = False
        try:
            signature = _cloud_signature(section_layer, profile, topo)
            path = folder / f"{did}-{signature}.las"
            if layer is not None and layer.isValid() and Path(layer.source()) == path \
                    and path.exists():
                out[did] = layer
                continue
            # the same signature always gives the same file: one already there is reused
            count = 1 if path.exists() else _write_cloud(path, store, profile,
                                                         section_layer, topo)
        except Exception as exc:
            _log(f"3D view: '{d.name or d.id}' could not be shown smooth: {exc}")
            count, failed = 0, True
        if not count:
            if not failed:
                _log(f"3D view: '{d.name or d.id}' has nothing to show smooth")
            if layer is not None:
                _drop_cloud(project, layer)
            retry(f"cloud:{did}")               # comes back by itself once it has points
            continue
        _stale.difference_update(_companions(path))
        if layer is None:
            layer = _new_cloud(project, path, d.name or d.id, did)
        else:
            _let_go(Path(layer.source()))
            layer.setDataSource(str(path), layer.name(), "pdal")    # the user's style stays
            layer.trigger3DUpdate()     # a new source alone leaves the 3D view's old content
        out[did] = layer
    _drop_empty_group(project, SMOOTH_GROUP)
    return out


def _drop_empty_group(project: QgsProject, name: str) -> None:
    group = project.layerTreeRoot().findGroup(name)
    if group is not None and not group.children():
        group.parent().removeChildNode(group)


# -- section pictures (3D Tiles) -------------------------------------------------------------
def _picture_source(path: Path) -> str:
    """A tileset's layer source, through QGIS's own encoding (a "#" in a folder name is not
    taken for a URL fragment)."""
    from qgis.core import QgsProviderRegistry
    return QgsProviderRegistry.instance().encodeUri("cesiumtiles", {"path": str(path)})


def _picture_file(layer) -> Path | None:
    """The tileset file a picture layer shows (also an older "url=file:///…" source)."""
    from qgis.core import QgsProviderRegistry
    from qgis.PyQt.QtCore import QUrl
    source = layer.source()
    if source.startswith("url="):
        local = QUrl(source[4:]).toLocalFile()
    else:
        local = QgsProviderRegistry.instance().decodeUri("cesiumtiles", source).get("path")
    return Path(local) if local else None


def _symbol_text(symbol) -> str:
    from qgis.core import QgsSymbolLayerUtils
    try:
        return QgsSymbolLayerUtils.symbolProperties(symbol)
    except Exception:                            # never let a fingerprint stop a picture
        return repr(symbol)


def _interp_signature(interpretation) -> str:
    """A fingerprint of the interpretation a picture paints: its pieces in drawing order,
    their names, symbols (the 2D style) and the attributes that drive them."""
    if not interpretation:
        return ""
    pieces, features, symbols = interpretation
    h = hashlib.sha1()
    for piece in pieces:
        feat = features.get(piece.feature_id)
        h.update(repr((piece.id, piece.kind, [(float(s), float(z)) for s, z in piece.vertices],
                       None if feat is None else feat.name)).encode())
        entry = symbols.get(piece.id)
        if entry is None:
            continue
        symbol, feature = entry if isinstance(entry, tuple) else (entry, None)
        h.update(_symbol_text(symbol).encode())
        if feature is not None:
            h.update(repr(feature.attributes()).encode())
    return h.hexdigest()


def _picture_signature(layers, profile, topo, interpretation=None, gap: float = 0.0) -> str:
    """A short stable fingerprint of what a profile's picture shows: everything the section
    draws of its models (in their order) and, when painted in, the interpretation."""
    from ..section import picture
    h = hashlib.sha1()
    for section_layer in layers:
        style = section_layer.style
        h.update(_cloud_signature(section_layer, profile, topo).encode())
        h.update(repr((section_layer.dataset.id, style.mode, style.contour_step,
                       tuple(style.contour_major), tuple(style.contour_minor),
                       style.opacity)).encode())
    h.update(repr((picture.PX_PER_M, picture.MAX_PIXELS, picture.LABEL_SHARE, 2,
                   round(gap, 6))).encode())
    h.update(_interp_signature(interpretation).encode())
    return h.hexdigest()[:10]


def _png(image) -> bytes:
    from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG", 50)              # quicker than the default, about as small
    buffer.close()
    return bytes(data)


def _write_picture(path: Path, store, project, profile, layers, topo,
                   interpretation=None, gap: float | None = None) -> bool:
    """The profile's section picture of ``layers`` (bottom first; with ``interpretation``
    over them) as a tileset at ``path`` (and its glTF beside it), each face ``gap`` back from
    the plane; False when nothing is painted."""
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                           QgsVector3D)

    from ..core.tiles3d import enu_axes, glb, tileset
    from ..core.view3d import bend_chainages, curtain_gap, left_normals, picture_strip
    from ..section.picture import section_pictures
    bends = bend_chainages(profile.chainage)
    gap = gap or curtain_gap(profile.chainage.length)
    raw = []
    for pic in section_pictures(layers, topo, interpretation):
        if not pic.alpha.any():
            continue
        sz, tris = picture_strip(pic.alpha, pic.s0, pic.s1, pic.z0, pic.z1, bends, step=0.5)
        # two faces, as for the cells: the strip's triangles face the right of the line and
        # stand ``gap`` to its left; their reversed copy faces left and stands to the right
        n = len(sz)
        raw.append((np.vstack([sz, sz]), np.vstack([tris, tris[:, ::-1] + n]),
                    _png(pic.image), n))
    if not raw:
        return False
    sz = np.vstack([r[0] for r in raw])
    xy = np.atleast_2d(profile.chainage.to_xy(sz[:, 0])).reshape(-1, 2)
    side = left_normals(profile.chainage, sz[:, 0]) * gap
    first = np.concatenate([np.r_[np.ones(r[3]), -np.ones(r[3])] for r in raw])
    xy = xy + side * first[:, None]
    to_ecef = QgsCoordinateTransform(QgsCoordinateReferenceSystem(store.crs_authid),
                                     QgsCoordinateReferenceSystem("EPSG:4978"), project)
    ecef = np.array([[q.x(), q.y(), q.z()] for q in
                     (to_ecef.transform(QgsVector3D(float(x), float(y), float(z)))
                      for (x, y), z in zip(xy, sz[:, 1]))])
    origin = ecef.mean(axis=0)
    east, north, up = enu_axes(origin)
    local = ecef - origin
    enu = np.column_stack([local @ east, local @ north, local @ up])
    gltf = np.column_stack([enu[:, 0], enu[:, 2], -enu[:, 1]])          # glTF is y-up
    pieces, start = [], 0
    for psz, tris, png, _n in raw:
        end = start + len(psz)
        pieces.append((gltf[start:end], psz[:, 2:4], tris, png))
        start = end
    lo, hi = enu.min(axis=0), enu.max(axis=0)
    path.parent.mkdir(parents=True, exist_ok=True)
    model = path.with_suffix(".glb")
    for target, data in ((model, glb(pieces)),
                         (path, json.dumps(tileset(model.name, east, north, up, origin,
                                                   (lo + hi) / 2,
                                                   np.maximum((hi - lo) / 2, 0.5)),
                                           indent=1).encode())):
        part = target.with_name(target.name + ".part")
        part.write_bytes(data)
        part.replace(target)
    return True


def _busy(work, *args):
    """``work(*args)`` under a busy cursor: painting a picture takes a moment."""
    from qgis.PyQt.QtGui import QGuiApplication
    QGuiApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
    try:
        return work(*args)
    finally:
        QGuiApplication.restoreOverrideCursor()


def _new_picture(project: QgsProject, path: Path, name: str, profile_id: str):
    from qgis.core import QgsTiledSceneLayer
    layer = QgsTiledSceneLayer(_picture_source(path), name, "cesiumtiles")
    layer.setCustomProperty(_FLAG, "picture")
    layer.setCustomProperty(_GIVEN_NAME, name)
    layer.setCustomProperty(_PROFILE, profile_id)
    # kept out of the 2D map, which would decode the picture on every redraw (QGIS's 3D
    # view does not look at scale ranges); the user may switch it on again, it stays theirs
    layer.setScaleBasedVisibility(True)
    layer.setMinimumScale(PICTURE_2D_SCALE)
    try:
        from qgis._3d import QgsTiledSceneLayer3DRenderer
        layer.setRenderer3D(QgsTiledSceneLayer3DRenderer())
    except ImportError:                             # a QGIS built without 3D
        pass
    project.addMapLayer(layer, False)
    _subgroup(project, PICTURES_GROUP).addLayer(layer)
    return layer


def _follow_name(layer, name: str) -> None:
    """The layer takes ``name`` (its profile's, renamed) unless the user renamed it: only a
    name the plugin gave follows (one made before it was noted counts as given)."""
    given = layer.customProperty(_GIVEN_NAME)
    if given is not None and layer.name() != given:
        return                                      # the user's own name
    if layer.name() != name:
        layer.setName(name)
    if given != name:
        layer.setCustomProperty(_GIVEN_NAME, name)


def _drop_picture(project, layer) -> None:
    path = _picture_file(layer)
    if path is not None:
        _let_go(path)
    project.removeMapLayer(layer.id())


def _interpretation(provider, profile_id: str):
    """(pieces, features, symbols) of the interpretation the section draws on the profile
    (the version it shows; a compared version and crossing marks stay out), or None."""
    try:
        snap = provider.snapshot(profile_id)
    except Exception as exc:
        _log(f"3D view: the interpretation of a section picture could not be gathered: {exc}")
        return None
    if not snap.interpretation:
        return None
    return snap.interpretation, snap.interp_features, snap.interp_symbols


def _section_order(provider, profile_id: str, layers: list) -> list:
    """``layers`` in the order the section draws them (bottom first)."""
    try:
        order = {la.dataset.id: i for i, la in enumerate(provider.layers(profile_id))}
    except Exception:
        return layers
    return sorted(layers, key=lambda la: order.get(la.dataset.id, len(order)))


def _sync_pictures(store, provider, project, chosen, interpretation: bool, may_create, retry,
                   topo_of, gaps: dict) -> dict:
    """One section picture per profile of the ``chosen`` models (shown ones), all of them in
    it as the section stacks them; with ``interpretation``, the profile's interpretation
    painted over them; ``gaps[profile id]`` back from the plane. By profile id."""
    from ..core.view3d import curtain_gap
    wanted: dict = {}
    for profile, _d, section_layer in chosen:
        if _shown(section_layer):
            wanted.setdefault(profile.id, (profile, []))[1].append(section_layer)
    existing = pictures_3d(project)
    for layer in _picture_layers(project):
        pid = layer.customProperty(_PROFILE)
        if pid not in wanted or existing.get(pid) is not layer:
            _drop_picture(project, layer)           # also one saved per model, before 0.14
    folder = cloud_folder(store)
    out = {}
    for pid, (profile, layers) in wanted.items():
        layer = existing.get(pid)
        allowed = may_create(f"picture:{pid}")
        if layer is None and not allowed:
            continue                            # e.g. the user removed it
        if layer is not None:
            _follow_name(layer, profile.name)
        topo = topo_of(pid)
        layers = _section_order(provider, pid, layers)
        failed = False
        try:
            interp = _interpretation(provider, pid) if interpretation else None
            gap = gaps.get(pid) or curtain_gap(profile.chainage.length)
            path = folder / f"{pid}-{_picture_signature(layers, profile, topo, interp, gap)}.json"
            if layer is not None and layer.isValid() and _picture_file(layer) == path \
                    and path.exists():
                out[pid] = layer
                continue
            # the same signature always gives the same files: ones already there are reused
            painted = (path.exists() and path.with_suffix(".glb").exists()) or \
                _busy(_write_picture, path, store, project, profile, layers, topo, interp, gap)
        except Exception as exc:
            _log(f"3D view: the section picture of '{profile.name}' could not be drawn: {exc}")
            painted, failed = False, True
        if not painted:
            if not failed:
                _log(f"3D view: the section picture of '{profile.name}' has nothing to show")
            if layer is not None:
                _drop_picture(project, layer)
            retry(f"picture:{pid}")
            continue
        _stale.difference_update(_companions(path))
        if layer is None:
            layer = _new_picture(project, path, profile.name, pid)
        else:
            old = _picture_file(layer)
            if old is not None:
                _let_go(old)
            layer.setDataSource(_picture_source(path), layer.name(), "cesiumtiles")
            layer.trigger3DUpdate()     # a new source alone leaves the 3D view's old content
        out[pid] = layer
    _drop_empty_group(project, PICTURES_GROUP)
    return out


def forget_shown(project: QgsProject) -> None:
    """Start afresh for a newly opened store: QGIS reuses its project object, so what the
    last project showed must not count as "before" (it would add layers by itself)."""
    project.setProperty(_NEEDS, None)


def _contour_features(layer, profile, dataset, section_layer, topo) -> list[QgsFeature]:
    from ..core.gridding import contour_levels
    from ..core.view3d import field_contours
    from ..section.display_render import CONTOUR_DARKER
    style = section_layer.style
    grid, scale = _field(section_layer, topo)
    levels = [v for v, _major in contour_levels(scale, style.contour_step,
                                                style.contour_major, style.contour_minor)]
    out = []
    for level, xyz in field_contours(grid, profile.chainage, scale, levels):
        r, g, b = (int(c) for c in scale.rgba([level])[0][:3])
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry(QgsLineString(xyz[:, 0].tolist(), xyz[:, 1].tolist(),
                                                xyz[:, 2].tolist())))
        f.setAttributes([profile.id, profile.name, dataset.id, dataset.name or dataset.id,
                         float(level), QColor(r, g, b).darker(CONTOUR_DARKER).name()])
        out.append(f)
    return out


def _sync_contours(store, project, chosen, may_create, topo_of):
    """The contour lines of ``chosen`` (shown models with the section's lines)."""
    # noted only while lines are needed: a model switched to contours later gets its layer
    layer = _layer(store, project, "contours", bool(chosen),
                   may_create("contours") if chosen else False)
    if layer is None:
        return None
    built = _fresh(layer)
    for profile, d, section_layer in chosen:
        style, topo = section_layer.style, topo_of(profile.id)
        signature = (_cloud_signature(section_layer, profile, topo), style.contour_step,
                     tuple(style.contour_major), tuple(style.contour_minor),
                     profile.name, d.name)
        if d.id in built and built[d.id][0] == signature:
            continue
        try:
            features = _contour_features(layer, profile, d, section_layer, topo)
        except Exception as exc:
            _log(f"3D view: contours of '{d.name or d.id}' could not be shown: {exc}")
            _drop(layer, built, d.id)
            continue
        old = built[d.id][1] if d.id in built else []
        built[d.id] = (signature, _edit(layer, old, features))
    wanted = {d.id for _p, d, _la in chosen}
    for gone in [i for i in built if i not in wanted]:
        _drop(layer, built, gone)
    return layer


# -- the ground line -------------------------------------------------------------------------
def _ground_rows(store, provider, profile_ids: set, topo_of) -> list[tuple]:
    """(profile, xyz) of the section's ground line of each of ``profile_ids`` with real
    heights."""
    rows = []
    for profile in store.profiles():
        if profile.id not in profile_ids or _is_local(provider, profile.id):
            continue
        line = topo_of(profile.id)
        if line is None:
            continue
        s, z = (np.asarray(a, dtype=float) for a in line)
        ok = np.isfinite(s) & np.isfinite(z)
        if ok.sum() < 2:
            continue
        try:
            xy = np.atleast_2d(profile.chainage.to_xy(s[ok])).reshape(-1, 2)
        except (ValueError, IndexError) as exc:
            _log(f"3D view: the ground line of '{profile.name}' could not be shown: {exc}")
            continue
        rows.append((profile, np.column_stack([xy, z[ok]])))
    return rows


def _sync_ground(store, project, rows, may_create):
    """The ground line of every profile in ``rows`` (``_ground_rows``: those with something
    ticked and real heights), in "Ground in 3D"."""
    layer = _layer(store, project, "ground", bool(rows),
                   may_create("ground") if rows else False)
    if layer is None:
        return None
    signature = [(profile.id, profile.name, xyz.tobytes()) for profile, xyz in rows]
    built = _fresh(layer)
    if built.get("rows") == signature:
        return layer
    features = []
    for profile, xyz in rows:
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry(QgsLineString(xyz[:, 0].tolist(), xyz[:, 1].tolist(),
                                                xyz[:, 2].tolist())))
        f.setAttributes([profile.id, profile.name])
        features.append(f)
    layer.dataProvider().truncate()
    _edit(layer, [], features)
    built["rows"] = signature
    return layer


# -- profile names --------------------------------------------------------------------------
def names_3d(project: QgsProject) -> dict:
    """The profile names in 3D (one annotation layer per profile) by profile id."""
    from qgis.core import QgsAnnotationLayer
    return {layer.customProperty(_PROFILE): layer for layer in project.mapLayers().values()
            if isinstance(layer, QgsAnnotationLayer) and layer.customProperty(_FLAG) == "name"
            and layer.customProperty(_PROFILE)}


def _name_format(store, project):
    """The text format of the map's profile labels (QGIS's default without labels)."""
    from qgis.core import QgsTextFormat

    from .project_actions import store_layers
    profiles = store_layers(store, project).get("profiles")
    try:
        if profiles is not None and profiles.labeling() is not None:
            return QgsTextFormat(profiles.labeling().settings().format())
    except Exception:                               # rule-based or odd labelling: defaults
        pass
    return QgsTextFormat()


def _new_name(store, project: QgsProject, profile_id: str, name: str, fmt,
              flag: str = "name", group: str = NAMES_GROUP):
    """An annotation layer for one profile's name (or, with ``flag`` and ``group``, other
    texts), drawn in 3D by QGIS's annotation 3D renderer in the map labels' format; kept out
    of the 2D map (the map labels them already)."""
    from qgis.core import QgsAnnotationLayer, QgsCoordinateReferenceSystem
    layer = QgsAnnotationLayer(name, QgsAnnotationLayer.LayerOptions(project.transformContext()))
    layer.setCrs(QgsCoordinateReferenceSystem(store.crs_authid))
    layer.setCustomProperty(_FLAG, flag)
    if profile_id:
        layer.setCustomProperty(_PROFILE, profile_id)
    layer.setScaleBasedVisibility(True)
    layer.setMinimumScale(PICTURE_2D_SCALE)
    try:
        from qgis._3d import QgsAnnotationLayer3DRenderer
        renderer = QgsAnnotationLayer3DRenderer()
        renderer.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
        renderer.setTextFormat(fmt)
        # no callout lines: with the terrain off they run down to height 0 (the user can
        # switch them on in the layer's 3D View properties)
        renderer.setShowCalloutLines(False)
        layer.setRenderer3D(renderer)
    except ImportError:                             # a QGIS built without 3D
        pass
    project.addMapLayer(layer, False)
    _subgroup(project, group).addLayer(layer)
    return layer


def _own_name_item(layer):
    """(id, item) of the plugin's text in a name layer, or (None, None): the item whose id
    the layer keeps (or the only item of a layer made before it kept one)."""
    from qgis.core import QgsAnnotationItem, QgsAnnotationPointTextItem
    items = layer.items()
    own = layer.customProperty(_NAME_ITEM)
    if own is None and len(items) == 1:
        own = next(iter(items))
    item = as_kind(items[own], "pointtext", QgsAnnotationItem,
                   QgsAnnotationPointTextItem) if own in items else None
    return (own, item) if item is not None else (None, None)


def _fill_name(layer, name: str, x: float, y: float, z: float, fmt) -> None:
    """The plugin's text item ``name`` at (x, y), drawn at height ``z``; items the user
    added to the layer stay, and nothing is set that is already so (a text format the user
    gave the 3D view stays)."""
    from qgis.core import QgsAnnotationPointTextItem, QgsPointXY
    own, item = _own_name_item(layer)
    changed = False
    if (item is None or item.text() != name
            or abs(item.point().x() - x) > 1e-6 or abs(item.point().y() - y) > 1e-6):
        new = QgsAnnotationPointTextItem(name, QgsPointXY(x, y))
        new.setFormat(fmt)
        if own is None:
            own = layer.addItem(new)
        else:
            layer.replaceItem(own, new)
        changed = True
    if layer.customProperty(_NAME_ITEM) != own:
        layer.setCustomProperty(_NAME_ITEM, own)
    if layer.name() != name:
        layer.setName(name)
    try:
        from qgis._3d import QgsAnnotationLayer3DRenderer
        from qgis.core import QgsAbstract3DRenderer
    except ImportError:                             # a QGIS built without 3D
        return
    renderer = as_kind(layer.renderer3D(), "annotation", QgsAbstract3DRenderer,
                       QgsAnnotationLayer3DRenderer)
    callouts_settled = bool(layer.customProperty(_CALLOUTS_SET))
    if renderer is not None and (abs(renderer.zOffset() - z) > 1e-6 or not callouts_settled):
        renderer = renderer.clone()
        renderer.setZOffset(z)
        if not callouts_settled:            # once (a layer made before they were off)
            renderer.setShowCalloutLines(False)
        layer.setRenderer3D(renderer)
        handed_over(renderer)
        changed = True
    if not callouts_settled:
        layer.setCustomProperty(_CALLOUTS_SET, True)
    if changed:
        layer.trigger3DUpdate()         # the 3D view reloads an annotation layer only on this


def _sync_names(store, project, rows, may_create) -> dict:
    """Each profile of ``rows`` (``_ground_rows``) with its name a little above the start
    of its ground line, as QGIS draws text annotations in 3D. An annotation layer draws all
    its items at one height, so each profile has its own, in "Profile names in 3D"."""
    replaced = False
    for layer in list(project.mapLayers().values()):
        if isinstance(layer, QgsVectorLayer) and layer.customProperty(_FLAG) == "names":
            _built.pop(layer.id(), None)            # made as lettering before 0.14
            project.removeMapLayer(layer.id())
            replaced = True
    wanted = {profile.id: (profile, xyz) for profile, xyz in rows}
    existing = names_3d(project)
    for pid, layer in existing.items():
        if pid not in wanted:
            project.removeMapLayer(layer.id())
    fmt = _name_format(store, project) if wanted else None
    out = {}
    for pid, (profile, xyz) in wanted.items():
        layer = existing.get(pid)
        allowed = may_create(f"names:{pid}")
        if layer is None and not (allowed or replaced):
            continue                                # e.g. the user removed it
        x, y, z = (float(v) for v in xyz[0])
        height = z + max(NAME_LIFT_M, NAME_LIFT_SHARE * profile.chainage.length)
        if layer is None:
            layer = _new_name(store, project, pid, profile.name, fmt)
        _fill_name(layer, profile.name, x, y, height, fmt)
        out[pid] = layer
    _drop_empty_group(project, NAMES_GROUP)
    return out


def borehole_names_3d(project: QgsProject) -> list:
    """The borehole name layers in 3D (one per collar height step)."""
    from qgis.core import QgsAnnotationLayer
    return [layer for layer in project.mapLayers().values()
            if isinstance(layer, QgsAnnotationLayer) and layer.customProperty(_FLAG) == "bhname"]


def _height_step(z: float) -> float:
    return round(round(z / BOREHOLE_NAME_STEP_M) * BOREHOLE_NAME_STEP_M, 3)


def _set_height(layer, z: float) -> bool:
    """The annotation layer's 3D height; True when it changed."""
    try:
        from qgis._3d import QgsAnnotationLayer3DRenderer
        from qgis.core import QgsAbstract3DRenderer
    except ImportError:                             # a QGIS built without 3D
        return False
    renderer = as_kind(layer.renderer3D(), "annotation", QgsAbstract3DRenderer,
                       QgsAnnotationLayer3DRenderer)
    if renderer is None or abs(renderer.zOffset() - z) <= 1e-6:
        return False
    renderer = renderer.clone()
    renderer.setZOffset(z)
    layer.setRenderer3D(renderer)
    handed_over(renderer)
    return True


def _sync_borehole_names(store, project, names, may_create) -> list:
    """``names`` ((label, x, y, collar height) of the boreholes shown) as texts a little above
    their columns: one annotation layer per collar height step (QGIS draws all of a layer's
    texts at one height), named after its boreholes, in "Borehole names in 3D". The plugin
    owns their texts; a layer the user removed is not made again by itself."""
    from qgis.core import QgsAnnotationPointTextItem, QgsPointXY
    steps: dict = {}
    for label, x, y, z in names:
        steps.setdefault(_height_step(z), []).append((str(label), float(x), float(y)))
    existing = {}
    for layer in borehole_names_3d(project):
        try:
            step = float(layer.customProperty(_HEIGHT))
        except (TypeError, ValueError):
            step = None
        if step not in steps or step in existing:
            project.removeMapLayer(layer.id())
        else:
            existing[step] = layer
    fmt = _name_format(store, project) if steps else None
    out = []
    for step, items in sorted(steps.items()):
        items = sorted(items)
        title = ", ".join(label for label, _x, _y in items)
        title = title if len(title) <= 40 else title[:39] + "…"
        layer = existing.get(step)
        allowed = may_create(f"bhnames:{step:g}")
        if layer is None:
            if not allowed:
                continue                            # e.g. the user removed it
            layer = _new_name(store, project, "", title, fmt, "bhname", BOREHOLE_NAMES_GROUP)
            layer.setCustomProperty(_HEIGHT, step)
        have = sorted((item.text(), item.point().x(), item.point().y())
                      for item in layer.items().values()
                      if isinstance(item, QgsAnnotationPointTextItem))
        changed = False
        if have != items:
            layer.clear()
            for label, x, y in items:
                item = QgsAnnotationPointTextItem(label, QgsPointXY(x, y))
                item.setFormat(fmt)
                layer.addItem(item)
            changed = True
        if layer.name() != title:
            layer.setName(title)
        changed = _set_height(layer, step + BOREHOLE_NAME_LIFT_M) or changed
        if changed:
            layer.trigger3DUpdate()     # the 3D view reloads an annotation layer only on this
        out.append(layer)
    _drop_empty_group(project, BOREHOLE_NAMES_GROUP)
    return out


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


def profiles_with_boreholes(store, provider) -> set:
    """The ids of the profiles whose section shows boreholes (a profile whose context cannot
    be gathered just now counts as one that may: it is not greyed out for a passing
    error)."""
    out = set()
    for profile in store.profiles():
        try:
            items = provider.drawn_context(profile.id)
        except Exception:
            out.add(profile.id)
            continue
        if items is not None and any(p.kind == "borehole" for p in items.points):
            out.add(profile.id)
    return out


def _disc(x: float, y: float, z: float, radius: float, sides: int = 16) -> QgsPolygon:
    """A flat round base at height ``z``: extruded upward, a borehole interval's column."""
    a = np.linspace(0.0, 2 * np.pi, sides + 1)
    a[-1] = 0.0                                     # closed exactly
    ring = QgsLineString((x + radius * np.cos(a)).tolist(), (y + radius * np.sin(a)).tolist(),
                         [float(z)] * (sides + 1))
    return QgsPolygon(ring)


def _collars(rows) -> list:
    """(label, x, y, collar height) of each borehole in ``_borehole_rows``' rows, once."""
    out = {}
    for _pid, label, _lid, iv in rows:
        key = (label, round(iv.x, 3), round(iv.y, 3))
        collar = iv.z_top + iv.top
        out[key] = max(out.get(key, collar), collar)
    return [(label, x, y, z) for (label, x, y), z in out.items()]


def _sync_boreholes(store, provider, project, choice: Choice, create: bool, may_create):
    """The columns of the ticked profiles' boreholes in "Boreholes in 3D", and their names
    above them."""
    known = {p.id for p in store.profiles()}
    wanted = bool(choice.boreholes & known)
    old = layers_3d(project).get("boreholes")
    if old is not None and old.geometryType() != QgsWkbTypes.GeometryType.PolygonGeometry:
        _built.pop(old.id(), None)                  # saved while boreholes were lines
        project.removeMapLayer(old.id())
        create = True
    layer = _layer(store, project, "boreholes", wanted, create)
    if layer is None:
        _sync_borehole_names(store, project, [], may_create)
        return None
    rows = _borehole_rows(store, provider, project, choice)
    _sync_borehole_names(store, project, _collars(rows), may_create)
    radius = (choice.borehole_width or auto_borehole_width(store)) / 2
    signature = [(pid, label, lid, iv) for pid, label, lid, iv in rows] + [radius]
    built = _fresh(layer)
    built["hidden"] = _hidden(store, choice)
    if built.get("rows") == signature:
        return layer
    features = []
    for pid, label, lid, iv in rows:
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry(_disc(iv.x, iv.y, iv.z_bottom, radius)))
        f.setAttributes([pid, label, lid, iv.top, iv.bottom, iv.text, QColor(*iv.rgb).name(),
                         float(iv.z_top - iv.z_bottom)])
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


def shown_summary(layers: dict) -> str:
    """What ``sync`` put into 3D, in words: "1 234 model cells, 2 point clouds, …"."""
    from qgis.PyQt.QtCore import QLocale
    loc, parts = QLocale(), []

    def count(n: int, one: str, many: str) -> None:
        if n:                                   # "0 borehole intervals" says nothing
            parts.append(f"{loc.toString(n)} {one if n == 1 else many}")
    if "models" in layers:
        count(layers["models"].featureCount(), "model cell", "model cells")
    count(len(layers.get("clouds") or ()), "point cloud", "point clouds")
    if "contours" in layers:
        count(layers["contours"].featureCount(), "contour line", "contour lines")
    count(len(layers.get("pictures") or ()), "section picture", "section pictures")
    if "boreholes" in layers:
        count(layers["boreholes"].featureCount(), "borehole interval", "borehole intervals")
    if "ground" in layers:
        count(layers["ground"].featureCount(), "ground line", "ground lines")
    if not parts:
        return "nothing that could be built"
    return ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]


def shown_box(store, provider, project: QgsProject) -> tuple | None:
    """(xmin, ymin, xmax, ymax, zmin, zmax) in the store's CRS of what the project's choice
    shows in 3D: the ticked models under their profile lines (in any look) and the borehole
    columns; ``None`` when nothing is shown. From the models themselves, as a section
    picture's own extent is in the earth frame and a fresh point cloud has no heights yet."""
    xs, ys, zs = [], [], []
    for profile, _d, section_layer in _gather(store, provider, read_choice(project)):
        if not _shown(section_layer):
            continue
        try:
            s0, s1, z0, z1 = section_layer.mesh.bounds()
            line = profile.chainage
            bends = line.xy
            along = line.project(bends)[0]
            xy = np.vstack([line.to_xy(np.linspace(s0, s1, 65)),
                            bends[(along > s0) & (along < s1)]])
        except (ValueError, IndexError, AttributeError):
            continue
        xs += [float(xy[:, 0].min()), float(xy[:, 0].max())]
        ys += [float(xy[:, 1].min()), float(xy[:, 1].max())]
        zs += [z0, z1]
    layer = layers_3d(project).get("boreholes")
    if layer is not None and layer.featureCount() > 0:
        box = layer.extent3D()
        x, y, z = ((box.xMinimum(), box.xMaximum()), (box.yMinimum(), box.yMaximum()),
                   (box.zMinimum(), box.zMaximum()))
        if np.isfinite(x + y + z).all():
            xs, ys, zs = xs + list(x), ys + list(y), zs + list(z)
    if not xs:
        return None
    return min(xs), min(ys), max(xs), max(ys), min(zs), max(zs)


def prune(store, project: QgsProject) -> None:
    """Take out what ``sync`` would take out because its model or profile is no longer
    chosen or no longer there, without building or writing anything: with no 3D view open,
    a deleted model's cloud (drawn in 2D too), picture and cells, or a deleted profile's
    name, ground line and boreholes, must not stay in the Layers panel and the saved project.
    Everything else waits for a 3D view (``sync``)."""
    choice = read_choice(project)
    chosen = _chosen_models(store, choice)
    profiles = {p.id for p in store.profiles()}
    models = {d.id for _p, d in chosen}
    pictured = {p.id for p, d in chosen if choice.look_of(d.id) == "picture"}
    columns = set(choice.boreholes) & profiles
    ticked = {p.id for p, _d in chosen} | columns
    for dataset_id, layer in clouds_3d(project).items():
        if dataset_id not in models or choice.look_of(dataset_id) == "picture":
            _drop_cloud(project, layer)
    for layer in _picture_layers(project):
        if layer.customProperty(_PROFILE) not in pictured:
            _drop_picture(project, layer)
    for profile_id, layer in names_3d(project).items():
        if profile_id not in ticked:
            project.removeMapLayer(layer.id())
    if not columns:                             # which ones stay waits for a sync
        for layer in borehole_names_3d(project):
            project.removeMapLayer(layer.id())
    shared = layers_3d(project)
    for kind, key, keep in (("models", "dataset_id", models), ("contours", "dataset_id", models),
                            ("ground", "profile_id", ticked), ("boreholes", "profile_id", columns)):
        if kind in shared:
            _prune_features(project, shared[kind], key, keep)
    for group in (SMOOTH_GROUP, PICTURES_GROUP, NAMES_GROUP, BOREHOLE_NAMES_GROUP,
                  VIEW3D_GROUP):
        _drop_empty_group(project, group)
    in_use = {Path(la.source()) for la in clouds_3d(project).values()}
    in_use |= {f for f in map(_picture_file, pictures_3d(project).values()) if f is not None}
    _delete_stale(set().union(*(_companions(f) for f in in_use)) if in_use else set())


def _prune_features(project, layer, key: str, keep: set) -> None:
    """``prune`` for a shared 3D layer: the features whose ``key`` is not in ``keep`` go
    (and the layer, when nothing is kept), and so does their part of the build record."""
    if not keep:
        _built.pop(layer.id(), None)
        project.removeMapLayer(layer.id())
        return
    gone = [f.id() for f in layer.dataProvider().getFeatures() if f[key] not in keep]
    if not gone:
        return
    _edit(layer, gone, [])
    built = _built.get(layer.id(), {})
    built.pop("rows", None)                     # the ground lines' or boreholes' rows
    for dataset_id in [k for k in built if k not in ("hidden",) and k not in keep]:
        built.pop(dataset_id)


def sync(store, provider, project: QgsProject, create: bool = False,
         boreholes: bool = True) -> dict:
    """Fill the 3D layers for the project's choice, each model in its representation: as
    its section draws it (cells in "Models in 3D", a smooth one as a point cloud of its own,
    contours in "Contours in 3D"), as a point cloud, or in its profile's section picture
    (``out["clouds"]``: dataset id -> cloud layer; ``out["pictures"]``: profile id ->
    picture layer), with the ground line of every profile that shows something. A layer is
    created when
    ``create`` (the user asked) or when a model's mode newly needs it, never just because the
    project was opened; it is removed when nothing needs it any more. Ids that no longer
    exist are ignored; a model that cannot be read is left out (and logged). Without
    ``boreholes`` (only a section style changed) the borehole layer is left as it is."""
    choice = read_choice(project)
    gathered = _gather(store, provider, choice)
    _settle_groups(project)
    before = project.property(_NEEDS)
    needs: set[str] = set()
    try:
        text = project.readEntry(SCOPE, ENTRY_MADE, "")[0]
        made = set(json.loads(text)) if text else None
    except (TypeError, ValueError):
        made = None
    known = (made or set()) | _made_now(project)

    def may_create(kind: str) -> bool:
        needs.add(kind)
        # a kind this project never had (one added by an update) comes by itself; a project
        # without the record (made before it) waits for OK, as it always did
        base = kind.split(":")[0]
        new_kind = made is not None and base in _MADE_KINDS and base not in known
        return create or new_kind or (before is not None and kind not in before.split("\n"))

    topos: dict = {}

    def topo_of(profile_id: str):
        if profile_id not in topos:
            topos[profile_id] = _surface_line(provider, profile_id)
        return topos[profile_id]

    out = {}
    look = {d.id: choice.look_of(d.id) for _p, d, _la in gathered}
    cells = [(p, d, la) for p, d, la in gathered
             if look[d.id] == "section" and (not _shown(la) or _as_cells(la))]
    smooth = [(p, d, la) for p, d, la in gathered if _shown(la) and (
        look[d.id] == "cloud" or (look[d.id] == "section" and la.style.mode in _SMOOTH))]
    lines = [(p, d, la) for p, d, la in gathered
             if _shown(la) and look[d.id] != "picture" and la.style.mode in _LINES]
    pictured = [(p, d, la) for p, d, la in gathered if look[d.id] == "picture"]
    cell_gaps, picture_gaps = _stack_gaps(provider, [c for c in cells if _shown(c[2])],
                                          [c for c in pictured if _shown(c[2])])
    models = _sync_models(store, project, cells, may_create("models") if cells else create,
                          cell_gaps)
    if models is not None:
        out["models"] = models
    clouds = _sync_clouds(store, provider, project, smooth, may_create, needs.discard,
                          topo_of)
    if clouds:
        out["clouds"] = clouds
    contours = _sync_contours(store, project, lines, may_create, topo_of)
    if contours is not None:
        out["contours"] = contours
    pictures = _sync_pictures(store, provider, project, pictured, choice.interpretation,
                              may_create, needs.discard, topo_of, picture_gaps)
    if pictures:
        out["pictures"] = pictures
    ticked = {p.id for p, _d, _la in gathered} | set(choice.boreholes)
    rows = _ground_rows(store, provider, ticked, topo_of)
    ground = _sync_ground(store, project, rows, may_create)
    if ground is not None:
        out["ground"] = ground
    names = _sync_names(store, project, rows, may_create)
    if names:
        out["names"] = names
    in_use = {Path(la.source()) for la in clouds_3d(project).values()}
    in_use |= {f for f in map(_picture_file, pictures_3d(project).values()) if f is not None}
    _delete_stale(set().union(*(_companions(f) for f in in_use)) if in_use else set())
    layer = layers_3d(project).get("boreholes")
    if not boreholes and layer is not None:
        # a redraw: of the boreholes, only hiding or showing one in a section can change
        boreholes = _built.get(layer.id(), {}).get("hidden") != _hidden(store, choice)
    if boreholes or layer is None:
        layer = _sync_boreholes(store, provider, project, choice, create, may_create)
    elif before is not None:    # a redraw: the borehole names stay as the last sync left them
        needs.update(k for k in before.split("\n") if k.startswith("bhnames:"))
    if layer is not None:
        out["boreholes"] = layer
    project.setProperty(_NEEDS, "\n".join(sorted(needs)))
    now = known | _made_now(project)
    # noted once Show in 3D was used (OK, or a layer of the plugin's): a project that never
    # used it stays unmodified
    if now != made and (create or now):
        project.writeEntry(SCOPE, ENTRY_MADE, json.dumps(sorted(now)))
    _drop_empty_group(project, VIEW3D_GROUP)
    return out


def _made_now(project: QgsProject) -> set:
    """The kinds of 3D layer the project holds now (for the "made" record)."""
    return (set(layers_3d(project)) | ({"names"} if names_3d(project) else set())
            | ({"bhnames"} if borehole_names_3d(project) else set()))
