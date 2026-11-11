"""Workbench project actions for QGIS, without widgets.

A workbench project is a GeoPackage (``ProjectStore``). The QGIS project remembers it in the
entry ``geophysics_workbench/store_path``: relative to the project file's folder when the
project has a file name and the store is on the same drive, absolute otherwise. Its
``profiles`` and ``stations`` layers live in the layer-tree group "Geophysics Workbench"
and are read-only in QGIS: only the workbench writes them (ids, station sets, chainage).
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import numpy as np
from qgis.core import (QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings, QgsProject,
                       QgsProviderRegistry, QgsSingleSymbolRenderer, QgsTextFormat,
                       QgsVectorLayer, QgsVectorLayerSimpleLabeling)

from .. import readers
from ..core.model import Dataset, Profile, StationSet, file_fingerprint
from ..section.data import read_options
from ..store.gpkg_store import ProjectStore

SCOPE = "geophysics_workbench"
STORE_KEY = "store_path"
GROUP_NAME = "Geophysics Workbench"
LAYER_NAMES = ("profiles", "stations")
Z_CHOICES = ("elevation", "depth")


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
    Raises ValueError (readable) when the file is missing or not a workbench project."""
    entry = project.readEntry(SCOPE, STORE_KEY, "")[0]
    if not entry:
        return None
    path = resolve_entry(entry, project)
    if not path.is_file():
        raise ValueError(f"Workbench project file not found: {path}")
    store = ProjectStore.open(path)
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


def _labels(field: str, size: float, enabled: bool, placement=None) -> tuple:
    settings = QgsPalLayerSettings()
    settings.fieldName = field
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
        labeling, enabled = _labels("number", 7.0, False)
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.setLabeling(labeling)
    layer.setLabelsEnabled(enabled)


def add_store_layers(store: ProjectStore, project: QgsProject) -> dict[str, QgsVectorLayer]:
    """Add the store's layers to the "Geophysics Workbench" group unless already there."""
    have = store_layers(store, project)
    root = project.layerTreeRoot()
    group = root.findGroup(GROUP_NAME) or root.insertGroup(0, GROUP_NAME)
    for name in LAYER_NAMES:                    # profiles drawn above stations
        if name in have:
            continue
        layer = QgsVectorLayer(store.layer_uri(name), name, "ogr")
        if not layer.isValid():
            raise ValueError(f"QGIS cannot load layer {name!r} from {store.path}")
        style_layer(layer, name)
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        have[name] = layer
    protect_layers(store, project)
    return have


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


def _has_elevations(store: ProjectStore, profile_id: str) -> bool:
    return any(len(s.xyz) and np.isfinite(s.xyz[:, 2]).any()
               for s in store.station_sets(profile_id))


def add_model(store: ProjectStore, profile_id: str, station_set_id: str, path: Path,
              reader: str, options: dict, name: str, provider=None) -> Dataset:
    """Validate ``path`` by reading it once, then save it as a model dataset.

    ``options`` may hold ``z_kind`` and ``chainage_offset`` (default 0) plus reader options;
    a missing ``z_kind`` comes from the reader. Raises the reader's ValueError for unusable
    files, and ValueError when it is still unknown whether Z is elevation or depth or when
    a depth model meets a profile whose stations have no elevations."""
    path = Path(path)
    opts = dict(options)
    opts["chainage_offset"] = float(opts.get("chainage_offset") or 0.0)
    result = readers.read(path, reader=reader or None, **read_options(opts))
    z_kind = opts.get("z_kind") or result.z_kind
    if z_kind not in Z_CHOICES:
        raise ValueError(f"Choose whether Z is elevation or depth for {path.name}")
    if z_kind == "depth" and not _has_elevations(store, profile_id):
        raise ValueError(f"{path.name}: a depth model is hung from the station elevations, "
                         "but this profile's stations have none. Create the profile from "
                         "a station file with a Z column, or choose Z means Elevation.")
    opts["z_kind"] = z_kind
    mtime, sha1 = file_fingerprint(str(path))
    dataset = Dataset(uuid.uuid4().hex, profile_id, station_set_id,
                      result.provenance.get("kind", "ert_model"),
                      model_source_path(store, path),
                      mtime, sha1, reader or result.provenance.get("reader", ""), opts,
                      dict(result.provenance), name=name or path.stem,
                      quantity=result.mesh.quantity, unit=result.mesh.unit)
    store.save_dataset(dataset)
    if provider is not None:
        provider.notify_changed()
    return dataset
