"""Per-profile section data: meshes in chainage/elevation, styles, topography and stations.

QGIS-free. ``SectionDataProvider`` reads the project store and model files on the main
thread; ``SectionSnapshot`` is the plain-data copy handed to profile-generator threads.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from typing import Callable

import numpy as np

from .. import readers
from ..core.colors import ColorScale
from ..core.model import Dataset, Profile, StationSet, data_to_chainage
from ..core.section_mesh import SectionMesh
from ..store.gpkg_store import ProjectStore

#: reader_options keys applied by the provider, not passed to the reader
WORKBENCH_KEYS = ("z_kind", "chainage_offset")
DEPTH_NEEDS_TOPO = "depth model needs station elevations or a DEM"
#: one QPainterPath element as serialised by QDataStream: int32 type, double x, double y
PATH_ELEMENT = np.dtype([("t", ">i4"), ("x", ">f8"), ("y", ">f8")])
_RING = [0, 1, 2, 3, 0]                     # closed cell outline; triangles repeat vertex 0
_RING_TYPES = [0, 1, 1, 1, 1]               # MoveTo, LineTo x 4


@dataclass
class LayerStyle:
    visible: bool = True
    opacity: float = 1.0
    scale: ColorScale | None = None         # None = auto on first successful load


@dataclass
class SectionLayer:
    dataset: Dataset
    mesh: SectionMesh | None                # chainage/elevation; None when error is set
    style: LayerStyle
    error: str | None


@dataclass
class SectionSnapshot:
    profile_id: str
    layers: list[SectionLayer]
    topo: tuple[np.ndarray, np.ndarray] | None
    stations: list[tuple[float, str]]       # (chainage, label); label "" = tick only


def _copy_style(style: LayerStyle) -> LayerStyle:
    return replace(style, scale=None if style.scale is None else replace(style.scale))


def _polyline_length(xy: np.ndarray) -> float:
    return float(np.hypot(*np.diff(xy, axis=0).T).sum()) if len(xy) > 1 else 0.0


def layer_name(dataset: Dataset) -> str:
    return dataset.name or os.path.basename(dataset.source_path)


def identify_layers(layers: list[SectionLayer], s: float, z: float) -> list[dict]:
    """Values under (s, z), topmost (last drawn) layer first. Hidden layers, layers
    with errors and cells without a value are skipped."""
    out = []
    for layer in reversed(layers):
        if not layer.style.visible or layer.error is not None or layer.mesh is None:
            continue
        value = layer.mesh.value_at(s, z)
        if not np.isfinite(value):
            continue
        d = layer.dataset
        out.append({"name": layer_name(d), "value": value, "unit": d.unit, "version": d.version,
                    "quantity": d.quantity, "dataset_id": d.id, "s": float(s), "z": float(z)})
    return out


def cell_path_groups(mesh: SectionMesh, scale: ColorScale) -> list[tuple[np.ndarray, np.ndarray]]:
    """Cells grouped by colour as ``[(rgba uint8 (4,), PATH_ELEMENT array), ...]``.

    Each cell becomes a closed ring of 5 path elements (MoveTo + 4 LineTo), so a group's
    array serialises straight into one QPainterPath. Transparent (nan) cells are dropped.
    Fully vectorised: the only Python loop is over the (<= ~256) distinct colours."""
    rgba = scale.rgba(mesh.values)
    keep = rgba[:, 3] > 0
    if not keep.any():
        return []
    rgba = rgba[keep]
    cells = mesh.cells[keep]
    cells = np.where(cells >= 0, cells, cells[:, :1])
    pts = mesh.vertices[cells[:, _RING]]                        # (k, 5, 2)
    elems = np.empty(pts.shape[:2], PATH_ELEMENT)
    elems["t"] = _RING_TYPES
    elems["x"] = pts[..., 0]
    elems["y"] = pts[..., 1]
    packed = rgba.astype(np.uint64) @ np.array([1 << 24, 1 << 16, 1 << 8, 1], dtype=np.uint64)
    colours, inverse = np.unique(packed, return_inverse=True)
    inverse = inverse.ravel()
    elems = elems[np.argsort(inverse, kind="stable")]
    splits = np.cumsum(np.bincount(inverse, minlength=len(colours)))[:-1]
    rgba_u = ((colours[:, None] >> np.array([24, 16, 8, 0], dtype=np.uint64)) & 255).astype(np.uint8)
    return [(c, g.reshape(-1)) for c, g in zip(rgba_u, np.split(elems, splits))]


def matching_profiles(profiles: list[Profile], xy: np.ndarray,
                      tol: float = 1.0) -> list[tuple[float, Profile, bool]]:
    """``[(error, profile, reversed), ...]``, best first, of the profiles whose end points
    and length match the polyline ``xy`` within ``tol`` (either direction)."""
    xy = np.asarray(xy, dtype=float)[:, :2]
    if len(xy) < 2:
        return []
    length = _polyline_length(xy)
    out = []
    for p in profiles:
        pxy = np.asarray(p.xy, dtype=float)
        if len(pxy) < 2 or abs(_polyline_length(pxy) - length) > tol:
            continue
        best = None
        for rev, (a, b) in ((False, (pxy[0], pxy[-1])), (True, (pxy[-1], pxy[0]))):
            err = max(np.hypot(*(xy[0] - a)), np.hypot(*(xy[-1] - b)))
            if err <= tol and (best is None or err < best[0]):
                best = (float(err), p, rev)
        if best is not None:
            out.append(best)
    out.sort(key=lambda m: m[0])                # stable: (name, id) order on ties
    return out


def station_labels(numbers: np.ndarray) -> list[str]:
    """Label the first station and every station whose number is a multiple of 10."""
    numbers = np.asarray(numbers, dtype=int)
    first = int(numbers.min()) if len(numbers) else None
    return [str(n) if (n % 10 == 0 or n == first) else "" for n in numbers.tolist()]


class SectionDataProvider:
    """Assembles the section layers of each profile from a ``ProjectStore``."""

    def __init__(self, store: ProjectStore):
        self.store = store
        self.on_change: list[Callable[[], None]] = []
        #: profile shown in the section panel; wins when several profiles share a curve.
        #: Set and read on the main thread only (snapshots stay plain data).
        self.active_profile_id: str | None = None
        self._styles: dict[str, LayerStyle] = {}
        self._cache: dict[str, tuple[tuple, readers.ReaderResult]] = {}

    def notify_changed(self) -> None:
        for callback in list(self.on_change):
            callback()

    # -- profiles --------------------------------------------------------------------------
    def match_curve(self, xy: np.ndarray, tol: float = 1.0) -> tuple[Profile, bool] | None:
        """(profile, reversed) whose end points and length match ``xy`` within ``tol``.
        When several profiles match (e.g. two profiles on the same line), the active
        profile wins; otherwise the closest match."""
        matches = matching_profiles(self.store.profiles(), xy, tol)
        if not matches:
            return None
        active = [m for m in matches if m[1].id == self.active_profile_id]
        _err, profile, rev = (active or matches)[0]
        return profile, rev

    def profile_for_curve(self, xy: np.ndarray, tol: float = 1.0) -> Profile | None:
        match = self.match_curve(xy, tol)
        return None if match is None else match[0]

    # -- styles ----------------------------------------------------------------------------
    def style(self, dataset_id: str) -> LayerStyle:
        return self._styles.setdefault(dataset_id, LayerStyle())

    def set_style(self, dataset_id: str, style: LayerStyle) -> None:
        self._styles[dataset_id] = style
        self.notify_changed()

    # -- topography and stations -----------------------------------------------------------
    @staticmethod
    def _topo_set(sets: list[StationSet]) -> StationSet | None:
        for s in sets:
            if len(s.xyz) and np.isfinite(s.xyz[:, 2]).any():
                return s
        return None

    @classmethod
    def _topography_of(cls, sets: list[StationSet]) -> tuple[np.ndarray, np.ndarray] | None:
        s = cls._topo_set(sets)
        if s is None:
            return None
        ok = np.isfinite(s.xyz[:, 2]) & np.isfinite(s.chainage)
        order = np.argsort(s.chainage[ok], kind="stable")
        return s.chainage[ok][order].astype(float), s.xyz[ok, 2][order].astype(float)

    def topography(self, profile_id: str) -> tuple[np.ndarray, np.ndarray] | None:
        return self._topography_of(self.store.station_sets(profile_id))

    # -- layers ----------------------------------------------------------------------------
    def source_path(self, d: Dataset) -> str:
        """Absolute path of ``d``'s model file; a relative ``source_path`` is resolved
        against the store's folder, so a project folder can be moved as a whole."""
        if os.path.isabs(d.source_path):
            return d.source_path
        return os.path.normpath(os.path.join(str(self.store.path.parent), d.source_path))

    def _read(self, d: Dataset) -> readers.ReaderResult:
        """Reader result in data coordinates, cached per dataset until the file or the
        options change. Raises FileNotFoundError / ValueError / OSError."""
        path = self.source_path(d)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        key = (d.id, os.stat(path).st_mtime, json.dumps(d.reader_options, sort_keys=True),
               path, d.reader)
        hit = self._cache.get(d.id)
        if hit is not None and hit[0] == key:
            return hit[1]
        options = {k: v for k, v in d.reader_options.items() if k not in WORKBENCH_KEYS}
        result = readers.read(path, reader=d.reader or None, **options)
        self._cache[d.id] = (key, result)
        return result

    def _load_mesh(self, d: Dataset, station_set: StationSet | None,
                   topo: tuple[np.ndarray, np.ndarray] | None) -> SectionMesh:
        if station_set is None:
            raise ValueError(f"station set {d.station_set_id} not found")
        result = self._read(d)
        mesh = result.mesh.with_x(lambda x: data_to_chainage(x, station_set, d))
        if d.reader_options.get("z_kind", result.z_kind) == "depth":
            if topo is None:
                raise ValueError(DEPTH_NEEDS_TOPO)
            mesh = mesh.depth_to_elevation(*topo)
        return mesh

    def _layer(self, d: Dataset, sets: dict[str, StationSet], topo) -> SectionLayer:
        style = self.style(d.id)
        try:
            mesh = self._load_mesh(d, sets.get(d.station_set_id), topo)
            if style.scale is None:
                style.scale = ColorScale.auto(mesh.values, log=(d.quantity == "resistivity"))
        except FileNotFoundError:
            return SectionLayer(d, None, style, f"source missing: {self.source_path(d)}")
        except ValueError as exc:
            return SectionLayer(d, None, style, str(exc))
        except OSError as exc:
            return SectionLayer(d, None, style,
                                f"cannot read {self.source_path(d)}: {exc.strerror or exc}")
        except Exception as exc:                # never raise from layers()
            return SectionLayer(d, None, style, f"{type(exc).__name__}: {exc}")
        return SectionLayer(d, mesh, style, None)

    def _assemble(self, profile_id: str):
        sets = self.store.station_sets(profile_id)
        topo = self._topography_of(sets)
        by_id = {s.id: s for s in sets}
        layers = [self._layer(d, by_id, topo) for d in self.store.datasets(profile_id)]
        return layers, sets, topo

    def layers(self, profile_id: str) -> list[SectionLayer]:
        return self._assemble(profile_id)[0]

    def snapshot(self, profile_id: str, reverse: bool = False) -> SectionSnapshot:
        """Detached plain-data copy for a generator thread. ``reverse`` mirrors chainage
        (s -> length - s) for a profile curve drawn end-to-start."""
        layers, sets, topo = self._assemble(profile_id)
        station_set = self._topo_set(sets) or (sets[0] if sets else None)
        stations = []
        if station_set is not None:
            stations = list(zip(station_set.chainage.astype(float).tolist(),
                                station_labels(station_set.numbers)))
        if topo is not None:
            topo = (topo[0].copy(), topo[1].copy())
        layers = [SectionLayer(la.dataset, la.mesh, _copy_style(la.style), la.error)
                  for la in layers]
        if reverse:
            length = self.store.profile(profile_id).chainage.length
            for la in layers:
                if la.mesh is not None:
                    la.mesh = la.mesh.with_x(lambda x: length - x)
            if topo is not None:
                topo = (length - topo[0][::-1], topo[1][::-1].copy())
            stations = [(length - s, label) for s, label in stations]
        return SectionSnapshot(profile_id, layers, topo, stations)

    def identify(self, profile_id: str, s: float, z: float) -> list[dict]:
        """Values at forward profile chainage ``s`` (0 at the profile's first vertex) and
        elevation ``z``. The profile source's ``results.identify`` takes *canvas*
        distance instead, which is mirrored (length - s) for a reversed curve."""
        return identify_layers(self.layers(profile_id), s, z)
