"""Workbench project actions for QGIS, without widgets.

A workbench project is a GeoPackage (``ProjectStore``). The QGIS project remembers it in the
entry ``store_path`` in the legacy scope (ids.LEGACY_ID): relative to the project file's folder
when the project has a file name and the store is on the same drive, absolute otherwise. Its
``profiles`` and ``stations`` layers live in the layer-tree group "Groundwork"
and are read-only in QGIS: only the workbench writes them (ids, station sets, chainage).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from qgis.core import (QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings, QgsProject,
                       QgsProviderRegistry, QgsSingleSymbolRenderer, QgsTextFormat,
                       QgsVectorLayer, QgsVectorLayerSimpleLabeling)

from .. import readers
from ..core.dataset_types import READINGS_KINDS, model_kind
from ..core.model import (Dataset, Profile, StationSet, attach_positions, file_fingerprint,
                          profile_from_polyline, profile_from_positions)
from ..core.placement import Placement
from ..ids import LEGACY_ID, LEGACY_NAME, NAME
from ..readers.base import Z_CHOICES
from ..section.data import read_options, xy_to_distance_on
from ..store.gpkg_store import ProjectStore

SCOPE = LEGACY_ID
STORE_KEY = "store_path"
GROUP_NAME = NAME
LEGACY_GROUP_NAME = LEGACY_NAME
LAYER_NAMES = ("profiles", "stations")


def plugin_group(root):
    """The plugin's layer group: "Groundwork", else the group an old (0.9) project already has
    (never renamed), else a new "Groundwork" group on top. Searched like ``findGroup`` does."""
    return (root.findGroup(GROUP_NAME) or root.findGroup(LEGACY_GROUP_NAME)
            or root.insertGroup(0, GROUP_NAME))


def default_store_name(project: QgsProject) -> str:
    """Suggested store path ``<project>_groundwork.gpkg`` beside the project file, or ``""``."""
    name = project.fileName()
    if not name:
        return ""
    path = Path(name)
    return str(path.with_name(f"{path.stem}_groundwork.gpkg"))


# -- store path entry ----------------------------------------------------------------------
def _project_dir(project: QgsProject) -> Path | None:
    name = project.fileName()
    return Path(name).resolve().parent if name else None


def store_entry(store_path: Path, project: QgsProject) -> str:
    """How ``store_path`` is written into ``project``: relative when possible."""
    path = Path(store_path).resolve()
    folder = _project_dir(project)
    if folder is not None:
        try:
            return Path(os.path.relpath(path, folder)).as_posix()
        except ValueError:                      # other drive
            pass
    return str(path)


def write_store_entry(project: QgsProject, store_path: Path) -> None:
    entry = store_entry(store_path, project)
    if project.readEntry(SCOPE, STORE_KEY, "")[0] != entry:
        project.writeEntry(SCOPE, STORE_KEY, entry)


def resolve_entry(entry: str, project: QgsProject) -> Path:
    path = Path(entry)
    if not path.is_absolute():
        folder = _project_dir(project)
        path = (folder / path) if folder is not None else path.resolve()
    return Path(os.path.normpath(path))


def attach_store(project: QgsProject) -> ProjectStore | None:
    """The workbench store ``project`` refers to, or ``None`` when it refers to none.
    Raises ValueError (readable) when the file is missing or not a workbench project.
    A store with an interpretation gets its interpretation layers when the project lacks
    them, as when the store is opened (else they came only with the next edit)."""
    entry = project.readEntry(SCOPE, STORE_KEY, "")[0]
    if not entry:
        return None
    path = resolve_entry(entry, project)
    if not path.is_file():
        raise ValueError(f"Groundwork project file not found: {path}")
    store = ProjectStore.open(path)
    if store.has_interpretation():
        from .interp_layers import add_interp_layers
        add_interp_layers(store, project)
    protect_layers(store, project)
    return store


# -- layers --------------------------------------------------------------------------------
def _same_file(a: str, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(str(b)))


def store_layers(store: ProjectStore, project: QgsProject) -> dict[str, QgsVectorLayer]:
    """The project's layers showing ``store``'s ``profiles`` / ``stations`` tables."""
    return find_store_layers(store, project, LAYER_NAMES)


def repaint_store_layers(store: ProjectStore, project: QgsProject) -> None:
    """Repaint every layer showing a table of ``store``'s file. After a write QGIS sometimes
    lost the profile lines on the map until the next refresh (round 2, B3: not reproducible
    offscreen); repainting redoes a lost draw."""
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer) or layer.providerType() != "ogr":
            continue
        parts = QgsProviderRegistry.instance().decodeUri("ogr", layer.source())
        if _same_file(parts.get("path", ""), store.path):
            layer.triggerRepaint()


def find_store_layers(store: ProjectStore, project: QgsProject,
                      names) -> dict[str, QgsVectorLayer]:
    """The project's layers showing the tables ``names`` of ``store``."""
    out = {}
    for layer in project.mapLayers().values():
        if not isinstance(layer, QgsVectorLayer) or layer.providerType() != "ogr":
            continue
        parts = QgsProviderRegistry.instance().decodeUri("ogr", layer.source())
        name = parts.get("layerName")
        if name in names and _same_file(parts.get("path", ""), store.path):
            out.setdefault(name, layer)
    return out


def protect_layers(store: ProjectStore, project: QgsProject) -> None:
    """Make the store's layers in ``project`` read-only, so QGIS editing cannot bypass the
    store's rules."""
    for layer in store_layers(store, project).values():
        layer.setReadOnly(True)


#: a station's map label: its point name, else its number
STATION_LABEL = "coalesce(nullif(\"name\", ''), to_string(\"number\"))"


def _labels(field: str, size: float, enabled: bool, placement=None,
            expression: bool = False) -> tuple:
    settings = QgsPalLayerSettings()
    settings.fieldName = field
    settings.isExpression = expression
    if placement is not None:
        settings.placement = placement
    fmt = QgsTextFormat()
    fmt.setSize(size)
    buffer = fmt.buffer()
    buffer.setEnabled(True)
    buffer.setSize(0.8)
    fmt.setBuffer(buffer)
    settings.setFormat(fmt)
    return QgsVectorLayerSimpleLabeling(settings), enabled


def style_layer(layer: QgsVectorLayer, name: str) -> None:
    """Code-defined default styles: thick labelled profile lines, small station points."""
    if name == "profiles":
        symbol = QgsLineSymbol.createSimple({"color": "20,60,160", "width": "0.9",
                                             "capstyle": "round"})
        labeling, enabled = _labels("name", 10.0, True, QgsPalLayerSettings.Placement.Line)
    else:
        symbol = QgsMarkerSymbol.createSimple({"name": "circle", "color": "255,255,255",
                                               "outline_color": "20,60,160", "size": "1.4"})
        labeling, enabled = _labels(STATION_LABEL, 7.0, False, expression=True)
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(enabled)


#: the stations' 3D style leaves out stations without a surveyed height (z is NaN)
HAS_HEIGHT = "z($geometry) IS NOT NULL"
STATION_RADIUS = "groundwork/station_radius"   # the radius the plugin gave the spheres


def station_radius(store: ProjectStore) -> float:
    """Sphere radius for the stations in 3D: 0.3 x the median distance between neighbouring
    stations (so 0.5 m electrodes and 5 m geophones both stay apart), within 0.05-2 m;
    0.4 m without stations."""
    import numpy as np
    gaps = []
    try:
        for profile in store.profiles():
            for s in store.station_sets(profile.id):
                xy = np.asarray(s.xyz, float)[:, :2]
                if len(xy) > 1:
                    gaps.append(np.hypot(*np.diff(xy, axis=0).T))
    except Exception:                           # e.g. a store not yet updated: the default
        return 0.4
    gaps = np.concatenate(gaps) if gaps else np.array([])
    gaps = gaps[gaps > 0]
    if not gaps.size:
        return 0.4
    return float(np.clip(0.3 * np.median(gaps), 0.05, 2.0))


def style_stations_3d(layer: QgsVectorLayer, radius: float = 0.4) -> bool:
    """Small spheres (``radius`` m) at the stations' surveyed heights, in the outline colour
    of their 2D symbol (a white fill would vanish against the 3D view's light sky);
    stations without a height are left out. Marks the layer so the style is given once.
    False without 3D."""
    try:
        from qgis._3d import (QgsPhongMaterialSettings, QgsPoint3DSymbol,
                              QgsRuleBased3DRenderer)
    except ImportError:                         # a QGIS built without 3D
        return False
    from qgis.core import Qgis, QgsRenderContext

    from .interp_layers import STYLED_3D
    symbols = layer.renderer().symbols(QgsRenderContext()) if layer.renderer() else []
    colour = symbols[0].color() if symbols else None
    first = symbols[0].symbolLayer(0) if symbols and symbols[0].symbolLayerCount() else None
    if first is not None and hasattr(first, "strokeColor"):
        colour = first.strokeColor()
    symbol = QgsPoint3DSymbol()
    symbol.setShape(Qgis.Point3DShape.Sphere)
    symbol.setShapeProperties({"radius": float(radius)})
    symbol.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
    material = QgsPhongMaterialSettings()
    if colour is not None:
        material.setDiffuse(colour)
        material.setAmbient(colour)
    symbol.setMaterialSettings(material)
    root = QgsRuleBased3DRenderer.Rule(None)
    root.appendChild(QgsRuleBased3DRenderer.Rule(symbol, HAS_HEIGHT, "Stations with a height"))
    layer.setRenderer3D(QgsRuleBased3DRenderer(root))
    layer.setCustomProperty(STYLED_3D, True)
    layer.setCustomProperty(STATION_RADIUS, float(radius))
    return True


def _sphere_radius(layer: QgsVectorLayer) -> float | None:
    """The radius of the stations' 3D spheres when the 3D style is the plugin's own."""
    renderer = layer.renderer3D()
    if renderer is None or renderer.type() != "rulebased":
        return None
    from qgis._3d import QgsPoint3DSymbol, QgsRuleBased3DRenderer
    from qgis.PyQt import sip
    children = sip.cast(renderer, QgsRuleBased3DRenderer).rootRule().children()
    if len(children) != 1 or children[0].symbol() is None:
        return None
    symbol = sip.cast(children[0].symbol(), QgsPoint3DSymbol)
    try:
        return float(symbol.shapeProperties()["radius"])
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def fit_station_spheres(store: ProjectStore, project: QgsProject,
                        radius: float | None = None) -> bool:
    """Size the stations' spheres to ``radius`` (m; the size chosen in Show in 3D), or to
    the stations there are now (a new project's layer was styled before any were imported);
    only while the 3D style is still the plugin's, never a radius the user set. Only the
    radius changes: a colour or rule of the user's stays. True when it changed them; never
    raises."""
    layer = store_layers(store, project).get("stations")
    if layer is None:
        return False
    given = layer.customProperty(STATION_RADIUS)
    try:
        current = _sphere_radius(layer)
        if given is None or current is None or abs(current - float(given)) > 1e-9:
            return False
        wanted = float(radius) if radius else station_radius(store)
        if abs(wanted - current) <= 1e-9:
            return False
        _set_sphere_radius(layer, wanted)
    except Exception:                           # no 3D in this QGIS, or an odd style: leave it
        return False
    layer.setCustomProperty(STATION_RADIUS, float(wanted))
    return True


def _set_sphere_radius(layer: QgsVectorLayer, radius: float) -> None:
    """The stations' one-rule sphere style with only its radius changed."""
    from qgis._3d import QgsPoint3DSymbol, QgsRuleBased3DRenderer
    from qgis.PyQt import sip
    rule = sip.cast(layer.renderer3D(), QgsRuleBased3DRenderer).rootRule().children()[0]
    old = sip.cast(rule.symbol(), QgsPoint3DSymbol)
    symbol = QgsPoint3DSymbol()
    symbol.setShape(old.shape())
    props = dict(old.shapeProperties())
    props["radius"] = float(radius)
    symbol.setShapeProperties(props)
    symbol.setAltitudeClamping(old.altitudeClamping())
    symbol.setMaterialSettings(old.materialSettings().clone())
    root = QgsRuleBased3DRenderer.Rule(None)
    root.appendChild(QgsRuleBased3DRenderer.Rule(symbol, rule.filterExpression(),
                                                 rule.description()))
    layer.setRenderer3D(QgsRuleBased3DRenderer(root))


def ensure_station_3d(store: ProjectStore, project: QgsProject) -> int:
    """Give an older project's stations their 3D style, once (not when the user removed
    it or set their own). Returns 1 when it did."""
    from .interp_layers import STYLED_3D
    layer = store_layers(store, project).get("stations")
    if layer is None or layer.renderer3D() is not None or layer.customProperty(STYLED_3D):
        return 0
    return int(style_stations_3d(layer, station_radius(store)))


def add_store_layers(store: ProjectStore, project: QgsProject) -> dict[str, QgsVectorLayer]:
    """Add the store's layers to the "Groundwork" group unless already there."""
    have = store_layers(store, project)
    root = project.layerTreeRoot()
    group = plugin_group(root)
    for name in LAYER_NAMES:                    # profiles drawn above stations
        if name in have:
            continue
        layer = QgsVectorLayer(store.layer_uri(name), name, "ogr")
        if not layer.isValid():
            raise ValueError(f"QGIS cannot load layer {name!r} from {store.path}")
        style_layer(layer, name)
        if name == "stations":
            style_stations_3d(layer, station_radius(store))
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        have[name] = layer
    protect_layers(store, project)
    return have


def reload_stale_layers(store: ProjectStore, project: QgsProject) -> int:
    """0.9 gave stations an ``inline`` field (store schema 3), 0.12 a ``name`` field (schema
    4). A project's stations layer loaded from the file before the store was updated still
    lists the old fields: reload it. Idempotent; returns the number of layers reloaded."""
    layer = store_layers(store, project).get("stations")
    if layer is None or all(layer.fields().indexOf(f) >= 0 for f in ("inline", "name")):
        return 0
    layer.dataProvider().reloadData()
    layer.reload()
    layer.updateFields()
    return 1


#: shown when the store write committed but what follows it (layers, panel) failed
NOT_REFRESHED = "Saved, but the view could not be refreshed: {error}"


class NotRefreshed(Exception):
    """The data were saved, but refreshing the layers or the panel afterwards raised.
    ``saved`` is what the call returns otherwise; ``error`` is what was raised."""

    def __init__(self, saved, error: BaseException):
        super().__init__(NOT_REFRESHED.format(error=error))
        self.saved, self.error = saved, error


def after_save(saved, *steps) -> None:
    """Run each refresh step after a committed save (all of them, even when one fails);
    raise ``NotRefreshed(saved, first error)`` when any failed."""
    failed = None
    for step in steps:
        try:
            step()
        except Exception as exc:                # noqa: BLE001 - the data are saved anyway
            failed = failed or exc
    if failed is not None:
        raise NotRefreshed(saved, failed)


def refresh_layers(store: ProjectStore, project: QgsProject) -> None:
    """Make the store's layers show what was just written to the GeoPackage."""
    for layer in store_layers(store, project).values():
        layer.dataProvider().reloadData()
        layer.updateExtents()
        layer.triggerRepaint()


# -- projects ------------------------------------------------------------------------------
def use_store(store: ProjectStore, project: QgsProject) -> ProjectStore:
    add_store_layers(store, project)
    if store.has_interpretation():
        from .interp_layers import add_interp_layers
        add_interp_layers(store, project)
    write_store_entry(project, store.path)
    return store


def new_store(path: Path, crs_authid: str, project: QgsProject) -> ProjectStore:
    """Create a workbench project, show its layers and remember it in ``project``."""
    return use_store(ProjectStore.create(Path(path), crs_authid), project)


def open_store(path: Path, project: QgsProject) -> ProjectStore:
    """Open an existing workbench project, show its layers and remember it in ``project``."""
    return use_store(ProjectStore.open(Path(path)), project)


# -- content -------------------------------------------------------------------------------
def add_profile(store: ProjectStore, profile: Profile, station_set: StationSet,
                project: QgsProject, provider=None) -> None:
    store.save_profile(profile)
    store.save_station_set(station_set)
    refresh_layers(store, project)
    if provider is not None:
        provider.notify_changed()


def model_source_path(store: ProjectStore, path: Path) -> str:
    """``path`` as saved in the store: relative (POSIX) to the store's folder when the file
    lies under it, so the folder can be moved as a whole; absolute otherwise."""
    path = Path(path).resolve()
    try:
        return path.relative_to(Path(store.path).resolve().parent).as_posix()
    except ValueError:
        return str(path)


def _on_map(options: dict) -> bool:
    columns = options.get("columns")
    return isinstance(columns, dict) and columns.get("position") == "map"


def read_for(store: ProjectStore, profile: Profile | None, path: Path, reader: str,
             options: dict, max_rows: int | None = None) -> readers.ReaderResult:
    """Read ``path`` as the section will: a file in map coordinates is projected onto
    ``profile``'s line (which need not be saved yet). ``max_rows``: only the first rows of a
    text table, for a preview."""
    opts = read_options(options)
    if max_rows is not None:
        opts["max_rows"] = max_rows
    if _on_map(options):
        opts["xy_to_distance"] = xy_to_distance_on(
            profile, str(options["columns"].get("crs") or ""), store.crs_authid)
    return readers.read(Path(path), reader=reader or None, **opts)


def checked_z_kind(options: dict, result: readers.ReaderResult, path: Path) -> str:
    """The vertical meaning to store: the user's, else the reader's. ValueError while it is
    still unknown."""
    z_kind = options.get("z_kind") or result.z_kind
    if z_kind not in Z_CHOICES:
        raise ValueError(f"Choose whether Z is elevation or depth for {Path(path).name}")
    return z_kind


def add_model(store: ProjectStore, profile_id: str, station_set_id: str, path: Path,
              reader: str, options: dict, name: str, provider=None,
              result: readers.ReaderResult | None = None, profile: Profile | None = None,
              station_set: StationSet | None = None, kind: str | None = None) -> Dataset:
    """Validate ``path`` by reading it once, then save it as a model dataset.

    ``kind``: the dataset type the user chose (e.g. "srt_model"); a readings file keeps its
    reader's kind (measured ERT data or misfit), and without a choice the reader's kind
    counts, else "ert_model".

    ``options`` may hold ``z_kind`` and ``chainage_offset`` (default 0) plus reader options;
    a missing ``z_kind`` comes from the reader. Raises the reader's ValueError for unusable
    files, and ValueError when it is still unknown what Z means. A depth or local-height
    model hangs from the profile's surface, whatever heights the profile has. ``result``: the
    file already read that way (it is then not read again). ``profile`` and ``station_set``
    are saved with the dataset in one transaction (nothing is saved when one write fails).
    A failure of ``provider``'s listeners after the save raises ``NotRefreshed``."""
    path = Path(path)
    opts = dict(options)
    opts["chainage_offset"] = float(opts.get("chainage_offset") or 0.0)
    if result is None:
        result = read_for(store, store.profile(profile_id), path, reader, opts)
    opts["z_kind"] = checked_z_kind(opts, result, path)
    mtime, sha1 = file_fingerprint(str(path))
    read_kind = result.provenance.get("kind")
    if read_kind not in READINGS_KINDS and kind:
        read_kind = kind
    dataset = Dataset(uuid.uuid4().hex, profile_id, station_set_id,
                      read_kind or "ert_model",
                      model_source_path(store, path),
                      mtime, sha1, reader or result.provenance.get("reader", ""), opts,
                      dict(result.provenance), name=name or path.stem,
                      quantity=result.mesh.quantity, unit=result.mesh.unit)
    if profile is None and station_set is None:
        store.save_dataset(dataset)
    else:
        store.save_import(profile, station_set, dataset)
    if provider is not None:
        after_save(dataset, provider.notify_changed)
    return dataset


def draft_profile(store: ProjectStore, placement: Placement, name: str, method: str
                  ) -> tuple[Profile, list[StationSet], StationSet | None]:
    """What ``placement`` gives, nothing saved: (the profile, its station sets after the
    import, the new station set or None). A new profile is made from the positions (with a
    station set) or from the line (without one); positions for an existing profile become a
    station set on its line, which is kept."""
    if placement.profile_id is None:
        if placement.positions is not None:
            profile, new_set = profile_from_positions(name, store.crs_authid,
                                                      placement.positions, method=method)
            return profile, [new_set], new_set
        if placement.line_xy is None:
            raise ValueError("Choose where the line runs")
        return profile_from_polyline(name, store.crs_authid, placement.line_xy), [], None
    profile = store.profile(placement.profile_id)
    sets = store.station_sets(profile.id)
    if placement.positions is None:
        return profile, sets, None
    new_set = attach_positions(profile, name, method, placement.positions)
    return profile, [new_set] + sets, new_set


def _state_spacing(profile: Profile, placement: Placement) -> None:
    """A stated station spacing goes with the profile (a guessed one never reaches here)."""
    if placement.spacing is not None:
        profile.metadata["electrode_spacing"] = float(placement.spacing)


def build_profile(store: ProjectStore, placement: Placement, name: str, method: str
                  ) -> tuple[Profile, StationSet | None]:
    """The new profile ``placement`` makes, nothing saved: (the profile, its station set or
    None). A line or two points give a profile without stations; positions give one through
    them with a station set. A stated spacing is kept in the profile's metadata."""
    if placement.profile_id is not None:
        raise ValueError("The placement chooses an existing profile; no profile is made")
    profile, _sets, new_set = draft_profile(store, placement, name, method)
    _state_spacing(profile, placement)
    return profile, new_set


def create_profile(store: ProjectStore, placement: Placement, name: str, method: str,
                   project: QgsProject, provider=None) -> Profile:
    """Make and save the profile ``placement`` says, with its station set when positions
    give one, in one transaction (a failure saves nothing). The layers are refreshed and
    ``provider`` is told only after the save."""
    profile, new_set = build_profile(store, placement, name, method)
    store.save_import(profile, new_set, None)
    refresh_layers(store, project)
    if provider is not None:
        provider.notify_changed()
    return profile


def dataset_options(placement: Placement, profile: Profile, sets: list[StationSet],
                    options: dict, station_set_id: str | None = None) -> tuple[str, dict]:
    """(station set id, reader options) a dataset placed by ``placement`` is saved with: the
    chosen station set (``station_set_id`` when it is one of ``sets``, else the first, else
    ""); the offset as ``chainage_offset``; ``"placement"`` (where file distance 0 lies)
    unless the file is in map coordinates or station 1 of the profile's stations places it."""
    opts = dict(options)
    ids = [s.id for s in sets]
    station_set_id = station_set_id if station_set_id in ids else (ids[0] if ids else "")
    if _on_map(opts):                               # placed by its own coordinates
        return station_set_id, opts
    opts["chainage_offset"] = float(placement.offset or 0.0)
    if placement.zero == "end":
        opts["placement"] = {"zero": float(profile.chainage.length), "direction": -1}
    elif placement.zero != "station1" or not sets:
        opts["placement"] = {"zero": 0.0, "direction": 1}
    return station_set_id, opts


def add_data(store: ProjectStore, placement: Placement, path: Path, reader: str,
             options: dict, name: str, method: str, project: QgsProject,
             provider=None, station_set_id: str | None = None) -> tuple[Profile, Dataset]:
    """Add the data file ``path`` where ``placement`` says: on an existing profile (with the
    positions given, as a new station set), or on a profile made here from the line or the
    positions. A stated station spacing is stored with the profile (a guessed one never).
    ``station_set_id`` chooses among an existing profile's station sets (default the first).
    The whole file is read before anything is saved; the profile, station set and dataset
    are then saved in one transaction, so a failure saves nothing. A failure of what follows
    the save (layers, ``provider``'s listeners) raises ``NotRefreshed`` with
    ``(profile, dataset)``."""
    path = Path(path)
    created = placement.profile_id is None
    if created:                             # made exactly as New Profile makes it
        profile, new_set = build_profile(store, placement, name or path.stem, method)
        sets = [new_set] if new_set is not None else []
    else:
        profile, sets, new_set = draft_profile(store, placement, name or path.stem, method)
        _state_spacing(profile, placement)
    if new_set is not None:
        station_set_id = new_set.id
    station_set_id, opts = dataset_options(placement, profile, sets, options, station_set_id)
    result = read_for(store, profile, path, reader, opts)
    changed = profile if created or placement.spacing is not None else None
    dataset = add_model(store, profile.id, station_set_id, path, reader, opts, name,
                        result=result, profile=changed, station_set=new_set,
                        kind=model_kind(method) if method else None)
    steps = []
    if created or new_set is not None:
        steps.append(lambda: refresh_layers(store, project))
    if provider is not None:
        steps.append(provider.notify_changed)
    after_save((profile, dataset), *steps)
    return profile, dataset
