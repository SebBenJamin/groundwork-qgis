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

MODELS_NAME = "Models in 3D"
BOREHOLES_NAME = "Boreholes in 3D"
CONTOURS_NAME = "Contours in 3D"
SMOOTH_GROUP = "Smooth models in 3D"
PICTURES_GROUP = "Section pictures in 3D"
#: how ticked models are shown: as layers (cells, point clouds, contour lines) or as
#: pictures of their section (3D Tiles)
LOOKS = ("layers", "pictures")
ENTRY = "view3d"
_FLAG = f"{LEGACY_ID}/view3d"              # custom property: "models", "boreholes", ... "cloud"
_DATASET = f"{LEGACY_ID}/view3d_dataset"   # a cloud's dataset id
_NEEDS = "groundwork3dNeeds"            # Qt property on the project: what the last sync showed
#: points of a smooth curtain are at least this far apart (m), along and across
CLOUD_SPACING = 0.05
_SMOOTH, _LINES = ("smooth", "smooth+contours"), ("contours", "smooth+contours")
#: features one 3D chunk may hold: QGIS shows a layer split into chunks in pieces when
#: zoomed out, so a curtain layer is kept in one chunk
MAX_CHUNK = 5_000_000
_MODEL_FIELDS = ("&field=profile_id:string&field=profile:string&field=dataset_id:string"
                 "&field=dataset:string&field=value:double&field=coverage:double"
                 "&field=resolved:integer&field=color:string")
_BOREHOLE_FIELDS = ("&field=profile_id:string&field=borehole:string&field=layer:string"
                    "&field=top:double&field=bottom:double&field=text:string"
                    "&field=color:string&field=height:double")
_CONTOUR_FIELDS = ("&field=profile_id:string&field=profile:string&field=dataset_id:string"
                   "&field=dataset:string&field=level:double&field=color:string")
#: layer id -> {dataset id: (signature of what its cells were made from, their feature ids)}
_built: dict[str, dict] = {}
_FILLED = "groundworkFilled"            # Qt property: this layer object was filled


@dataclass(frozen=True)
class Choice:
    models: frozenset = field(default_factory=frozenset)       # dataset ids
    boreholes: frozenset = field(default_factory=frozenset)    # profile ids
    look: str = "layers"                                        # one of LOOKS


def read_choice(project: QgsProject) -> Choice:
    text = project.readEntry(SCOPE, ENTRY, "")[0]
    try:
        data = json.loads(text) if text else {}
        look = str(data.get("look", LOOKS[0]))
        return Choice(frozenset(str(i) for i in data.get("models", [])),
                      frozenset(str(i) for i in data.get("boreholes", [])),
                      look if look in LOOKS else LOOKS[0])
    except (ValueError, AttributeError, TypeError):
        return Choice()


def write_choice(project: QgsProject, choice: Choice) -> None:
    project.writeEntry(SCOPE, ENTRY, json.dumps({"models": sorted(choice.models),
                                                 "boreholes": sorted(choice.boreholes),
                                                 "look": choice.look}))


def layers_3d(project: QgsProject) -> dict[str, QgsVectorLayer]:
    """The 3D vector layers in the project by kind ("models", "boreholes", "contours")."""
    out = {}
    for layer in project.mapLayers().values():
        kind = layer.customProperty(_FLAG) if isinstance(layer, QgsVectorLayer) else None
        if kind in ("models", "boreholes", "contours"):
            out[kind] = layer
    return out


def clouds_3d(project: QgsProject) -> dict:
    """The point-cloud curtains in the project by dataset id."""
    from qgis.core import QgsPointCloudLayer
    return {layer.customProperty(_DATASET): layer for layer in project.mapLayers().values()
            if isinstance(layer, QgsPointCloudLayer) and layer.customProperty(_FLAG) == "cloud"}


def pictures_3d(project: QgsProject) -> dict:
    """The section pictures (3D Tiles) in the project by dataset id."""
    from qgis.core import QgsTiledSceneLayer
    return {layer.customProperty(_DATASET): layer for layer in project.mapLayers().values()
            if isinstance(layer, QgsTiledSceneLayer)
            and layer.customProperty(_FLAG) == "picture"}


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
    try:
        from qgis._3d import Qgs3DTypes, QgsPolygon3DSymbol, QgsVectorLayer3DRenderer
    except ImportError:                         # a QGIS built without 3D
        return
    symbol = QgsPolygon3DSymbol()
    symbol.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
    symbol.setExtrusionHeight(0.0)
    # each cell is two faces a little behind the plane on either side; hiding back faces
    # leaves the one behind, so an interpretation drawn in the plane is always in front
    symbol.setAddBackFaces(False)
    symbol.setCullingMode(Qgs3DTypes.CullingMode.Back)
    symbol.setMaterialSettings(_colour_material())
    renderer = QgsVectorLayer3DRenderer(symbol)
    _one_chunk(renderer)
    layer.setRenderer3D(renderer)


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


def _style_lines(layer: QgsVectorLayer, width: float) -> None:
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
    symbol.setWidth(width)                     # pixels
    material = QgsSimpleLineMaterialSettings()
    props = material.dataDefinedProperties()
    props.setProperty(QgsAbstractMaterialSettings.Property.Ambient, QgsProperty.fromField("color"))
    material.setDataDefinedProperties(props)
    symbol.setMaterialSettings(material)
    renderer = QgsVectorLayer3DRenderer(symbol)
    _one_chunk(renderer)
    layer.setRenderer3D(renderer)


_KINDS = {"models": ("MultiPolygonZ", _MODEL_FIELDS, MODELS_NAME, _style_models),
          "boreholes": ("PolygonZ", _BOREHOLE_FIELDS, BOREHOLES_NAME, _style_boreholes),
          "contours": ("LineStringZ", _CONTOUR_FIELDS, CONTOURS_NAME, _style_contours)}


def _create(store, project: QgsProject, kind: str) -> QgsVectorLayer:
    geometry, fields, name, style = _KINDS[kind]
    layer = QgsVectorLayer(f"{geometry}?crs={store.crs_authid}{fields}", name, "memory")
    layer.setCustomProperty(_FLAG, kind)
    layer.setCustomProperty("skipMemoryLayersCheck", 1)     # no "scratch layer" warning
    layer.setReadOnly(True)
    style(layer)
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
    from qgis.core import QgsMultiPolygon

    from ..core.colors import ColorScale
    from ..core.view3d import curtain_cells, curtain_gap
    mesh = section_layer.mesh
    scale = section_layer.style.scale or ColorScale.auto(mesh.values)
    cells = curtain_cells(mesh, profile.chainage, scale.rgba(mesh.values),
                          _threshold(section_layer), curtain_gap(profile.chainage.length))
    out = []
    for cell in cells:
        f = QgsFeature(layer.fields())
        both = QgsMultiPolygon()
        for face in cell.faces:
            both.addGeometry(QgsPolygon(QgsLineString([QgsPoint(*p) for p in face])))
        f.setGeometry(QgsGeometry(both))
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


def _sync_models(store, project, gathered, create: bool):
    chosen = [(p, d, la) for p, d, la in gathered if not _shown(la) or _as_cells(la)]
    old = layers_3d(project).get("models")
    if old is not None and not QgsWkbTypes.isMultiType(old.wkbType()):
        _built.pop(old.id(), None)                  # saved while cells were one face
        project.removeMapLayer(old.id())
        create = True
    layer = _layer(store, project, "models", bool(chosen), create)
    if layer is None:
        return None
    built = _fresh(layer)
    for profile, d, section_layer in chosen:
        if not _shown(section_layer):
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
    group = plugin_group(project.layerTreeRoot())
    return group.findGroup(SMOOTH_GROUP) or group.addGroup(SMOOTH_GROUP)


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


def _sync_clouds(store, provider, project, gathered, may_create, retry, topo_of) -> dict:
    wanted = {d.id: (p, d, la) for p, d, la in gathered
              if _shown(la) and la.style.mode in _SMOOTH}
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


def _picture_signature(section_layer, profile, topo) -> str:
    """A short stable fingerprint of what a picture shows: everything the section draws."""
    from ..section import picture
    style = section_layer.style
    h = hashlib.sha1(_cloud_signature(section_layer, profile, topo).encode())
    h.update(repr((style.mode, style.contour_step, tuple(style.contour_major),
                   tuple(style.contour_minor), style.opacity, picture.PX_PER_M,
                   picture.MAX_PIXELS, picture.LABEL_SHARE, 1)).encode())
    return h.hexdigest()[:10]


def _png(image) -> bytes:
    from qgis.PyQt.QtCore import QBuffer, QByteArray, QIODevice
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG", 50)              # quicker than the default, about as small
    buffer.close()
    return bytes(data)


def _write_picture(path: Path, store, project, profile, section_layer, topo) -> bool:
    """The model's section picture as a tileset at ``path`` (and its glTF beside it); False
    when nothing is painted."""
    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                           QgsVector3D)

    from ..core.tiles3d import enu_axes, glb, tileset
    from ..core.view3d import bend_chainages, curtain_gap, left_normals, picture_strip
    from ..section.picture import section_pictures
    bends = bend_chainages(profile.chainage)
    gap = curtain_gap(profile.chainage.length)
    raw = []
    for pic in section_pictures(section_layer, topo):
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


def _new_picture(project: QgsProject, path: Path, name: str, dataset_id: str):
    from qgis.core import QgsTiledSceneLayer
    layer = QgsTiledSceneLayer(_picture_source(path), name, "cesiumtiles")
    layer.setCustomProperty(_FLAG, "picture")
    layer.setCustomProperty(_DATASET, dataset_id)
    try:
        from qgis._3d import QgsTiledSceneLayer3DRenderer
        layer.setRenderer3D(QgsTiledSceneLayer3DRenderer())
    except ImportError:                             # a QGIS built without 3D
        pass
    project.addMapLayer(layer, False)
    group = plugin_group(project.layerTreeRoot())
    (group.findGroup(PICTURES_GROUP) or group.addGroup(PICTURES_GROUP)).addLayer(layer)
    return layer


def _drop_picture(project, layer) -> None:
    path = _picture_file(layer)
    if path is not None:
        _let_go(path)
    project.removeMapLayer(layer.id())


def _sync_pictures(store, project, gathered, may_create, retry, topo_of) -> dict:
    wanted = {d.id: (p, d, la) for p, d, la in gathered if _shown(la)}
    existing = pictures_3d(project)
    for did, layer in existing.items():
        if did not in wanted:
            _drop_picture(project, layer)
    folder = cloud_folder(store)
    out = {}
    for did, (profile, d, section_layer) in wanted.items():
        layer = existing.get(did)
        allowed = may_create(f"picture:{did}")
        if layer is None and not allowed:
            continue                            # e.g. the user removed it
        topo = topo_of(profile.id)
        failed = False
        try:
            path = folder / f"{did}-{_picture_signature(section_layer, profile, topo)}.json"
            if layer is not None and layer.isValid() and _picture_file(layer) == path \
                    and path.exists():
                out[did] = layer
                continue
            # the same signature always gives the same files: ones already there are reused
            painted = (path.exists() and path.with_suffix(".glb").exists()) or \
                _busy(_write_picture, path, store, project, profile, section_layer, topo)
        except Exception as exc:
            _log(f"3D view: '{d.name or d.id}' could not be shown as a picture: {exc}")
            painted, failed = False, True
        if not painted:
            if not failed:
                _log(f"3D view: '{d.name or d.id}' has nothing to show as a picture")
            if layer is not None:
                _drop_picture(project, layer)
            retry(f"picture:{did}")
            continue
        _stale.difference_update(_companions(path))
        if layer is None:
            layer = _new_picture(project, path, d.name or d.id, did)
        else:
            old = _picture_file(layer)
            if old is not None:
                _let_go(old)
            layer.setDataSource(_picture_source(path), layer.name(), "cesiumtiles")
        out[did] = layer
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


def _sync_contours(store, project, gathered, may_create, topo_of):
    chosen = [(p, d, la) for p, d, la in gathered if _shown(la) and la.style.mode in _LINES]
    layer = _layer(store, project, "contours", bool(chosen), may_create("contours"))
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


def _disc(x: float, y: float, z: float, radius: float, sides: int = 16) -> QgsPolygon:
    """A flat round base at height ``z``: extruded upward, a borehole interval's column."""
    a = np.linspace(0.0, 2 * np.pi, sides + 1)
    a[-1] = 0.0                                     # closed exactly
    ring = QgsLineString((x + radius * np.cos(a)).tolist(), (y + radius * np.sin(a)).tolist(),
                         [float(z)] * (sides + 1))
    return QgsPolygon(ring)


def _sync_boreholes(store, provider, project, choice: Choice, create: bool):
    known = {p.id for p in store.profiles()}
    wanted = bool(choice.boreholes & known)
    old = layers_3d(project).get("boreholes")
    if old is not None and old.geometryType() != QgsWkbTypes.GeometryType.PolygonGeometry:
        _built.pop(old.id(), None)                  # saved while boreholes were lines
        project.removeMapLayer(old.id())
        create = True
    layer = _layer(store, project, "boreholes", wanted, create)
    if layer is None:
        return None
    rows = _borehole_rows(store, provider, project, choice)
    radius = 2 * station_radius(store)
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
    """What ``sync`` put into 3D, in words: "1 234 model cells, 2 smooth models, …"."""
    from qgis.PyQt.QtCore import QLocale
    loc, parts = QLocale(), []
    if "models" in layers:
        parts.append(f"{loc.toString(layers['models'].featureCount())} model cells")
    if layers.get("clouds"):
        n = len(layers["clouds"])
        parts.append(f"{loc.toString(n)} smooth model{'' if n == 1 else 's'}")
    if "contours" in layers:
        parts.append(f"{loc.toString(layers['contours'].featureCount())} contour lines")
    if layers.get("pictures"):
        n = len(layers["pictures"])
        parts.append(f"{loc.toString(n)} section picture{'' if n == 1 else 's'}")
    if "boreholes" in layers:
        parts.append(f"{loc.toString(layers['boreholes'].featureCount())} borehole intervals")
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


def sync(store, provider, project: QgsProject, create: bool = False,
         boreholes: bool = True) -> dict:
    """Fill the 3D layers for the project's choice, each model as its section draws it:
    cells in "Models in 3D", a smooth one as a point cloud of its own, contours in
    "Contours in 3D" (``out["clouds"]``: dataset id -> cloud layer). A layer is created when
    ``create`` (the user asked) or when a model's mode newly needs it, never just because the
    project was opened; it is removed when nothing needs it any more. Ids that no longer
    exist are ignored; a model that cannot be read is left out (and logged). Without
    ``boreholes`` (only a section style changed) the borehole layer is left as it is."""
    choice = read_choice(project)
    gathered = _gather(store, provider, choice)
    before = project.property(_NEEDS)
    needs: set[str] = set()

    def may_create(kind: str) -> bool:
        needs.add(kind)
        return create or (before is not None and kind not in before.split("\n"))

    topos: dict = {}

    def topo_of(profile_id: str):
        if profile_id not in topos:
            topos[profile_id] = _surface_line(provider, profile_id)
        return topos[profile_id]

    out = {}
    pictures_look = choice.look == "pictures"
    as_layers = [] if pictures_look else gathered
    models = _sync_models(store, project, as_layers,
                          may_create("models") if any(not _shown(la) or _as_cells(la)
                                                      for _p, _d, la in as_layers) else create)
    if models is not None:
        out["models"] = models
    clouds = _sync_clouds(store, provider, project, as_layers, may_create, needs.discard,
                          topo_of)
    if clouds:
        out["clouds"] = clouds
    contours = _sync_contours(store, project, as_layers, may_create, topo_of)
    if contours is not None:
        out["contours"] = contours
    pictures = _sync_pictures(store, project, gathered if pictures_look else [], may_create,
                              needs.discard, topo_of)
    if pictures:
        out["pictures"] = pictures
    in_use = {Path(la.source()) for la in clouds_3d(project).values()}
    in_use |= {f for f in map(_picture_file, pictures_3d(project).values()) if f is not None}
    _delete_stale(set().union(*(_companions(f) for f in in_use)) if in_use else set())
    project.setProperty(_NEEDS, "\n".join(sorted(needs)))
    layer = layers_3d(project).get("boreholes")
    if not boreholes and layer is not None:
        # a redraw: of the boreholes, only hiding or showing one in a section can change
        boreholes = _built.get(layer.id(), {}).get("hidden") != _hidden(store, choice)
    if boreholes or layer is None:
        layer = _sync_boreholes(store, provider, project, choice, create)
    if layer is not None:
        out["boreholes"] = layer
    return out
