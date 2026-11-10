"""Per-profile section data: meshes in chainage/elevation, styles, topography, stations,
context items and profile ties.

QGIS-free. ``SectionDataProvider`` reads the project store and model files on the main
thread; ``SectionSnapshot`` is the plain-data copy handed to profile-generator threads.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np

from .. import readers
from ..core.colors import ColorScale
from ..core.context import ContextItems
from ..core.coverage import station_coverage
from ..core.model import Dataset, Profile, StationSet, data_to_chainage
from ..core.section_mesh import SectionMesh
from ..core.ties import Tie
from ..store.gpkg_store import ProjectStore
from .context_cache import GatheredContext
from .topography import TOPOGRAPHY_SOURCES, dem_line, station_line, station_marks

#: reader_options keys applied by the provider, not passed to the reader as such
WORKBENCH_KEYS = ("z_kind", "chainage_offset")


def read_options(reader_options: dict) -> dict:
    """Options for ``readers.read``: the reader's own options plus the user's ``z_kind``
    choice, which decides where a cell-centre model's top edge goes (depth 0 or not)."""
    options = {k: v for k, v in reader_options.items() if k not in WORKBENCH_KEYS}
    if reader_options.get("z_kind"):
        options["z_kind"] = reader_options["z_kind"]
    return options
DEPTH_NEEDS_TOPO = "depth model needs station elevations or a DEM"
#: one QPainterPath element as serialised by QDataStream: int32 type, double x, double y
PATH_ELEMENT = np.dtype([("t", ">i4"), ("x", ">f8"), ("y", ">f8")])
_RING = [0, 1, 2, 3, 0]                     # closed cell outline; triangles repeat vertex 0
_RING_TYPES = [0, 1, 1, 1, 1]               # MoveTo, LineTo x 4


DISPLAY_MODES = ("cells", "smooth", "contours", "smooth+contours")
#: readings layers (measured / misfit pseudosections) also draw one marker per reading
READINGS_MODES = ("points",) + DISPLAY_MODES
#: misfit colour map: diverging, centred on 0 (from the existing COLORMAPS)
MISFIT_CMAP = "RdYlBu_r"


@dataclass
class LayerStyle:
    visible: bool = True
    opacity: float = 1.0
    scale: ColorScale | None = None         # None = auto on first successful load
    #: how the model is drawn: one of DISPLAY_MODES (a display choice; readouts use the mesh)
    mode: str = "cells"
    #: contour spacing: decades on a log scale (0.25 = 4 per decade), units otherwise;
    #: None = automatic (1-2-5 per decade / nice steps)
    contour_step: float | None = None
    #: grid cell of the smooth field in metres; None = automatic
    grid_cell: float | None = None
    #: fade (or blank) the model where its coverage is below ``coverage_threshold``
    fade_coverage: bool = False
    coverage_threshold: float | None = None     # None = 10th percentile of the coverage
    fade_mode: str = "fade"                     # "fade" or "blank"
    #: readings layers: "misfit", "measured" or "calculated"; None = misfit when the file
    #: has calculated values, else measured
    shown: str | None = None


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
    #: (min, max) station chainage over all station sets; None without stations
    coverage: tuple[float, float] | None = None
    #: gathered context with the profile ties merged in; mirrored with the rest
    context: ContextItems | None = None
    #: measured station elevations aligned with ``stations`` (nan where missing)
    station_heights: np.ndarray | None = None
    #: True when ``topo`` is the DEM line, not the station elevations
    dem_topo: bool = False
    #: interpretation pieces of the shown version on this profile (mirrored with the rest),
    #: their features by id and their cloned layer symbols by piece id
    interpretation: list = field(default_factory=list)
    interp_features: dict = field(default_factory=dict)
    interp_symbols: dict = field(default_factory=dict)
    #: (tie chainage, [CrossMark]) where a crossing profile carries interpretation; the
    #: marks' symbols and features are in ``interp_symbols`` / ``interp_features``
    interp_crossings: list = field(default_factory=list)
    #: pieces of a frozen version drawn faintly behind, for comparison (mirrored too)
    interp_compare: list = field(default_factory=list)


def _copy_style(style: LayerStyle) -> LayerStyle:
    return replace(style, scale=None if style.scale is None else replace(style.scale))


def _layers_for_look(layers: list, look) -> list:
    """The frame's models only, styled as the frame says (a bad stored scale: the layer's)."""
    by_id = {m.dataset_id: m for m in look.models}
    out = []
    for la in layers:
        m = by_id.get(la.dataset.id)
        if m is None or not m.visible:
            continue
        style = _copy_style(la.style)
        scale = style.scale
        if m.scale:
            try:
                scale = ColorScale(**m.scale)
            except (TypeError, ValueError):
                pass
        out.append(SectionLayer(la.dataset, la.mesh, replace(
            style, visible=True, opacity=m.opacity, mode=m.mode, scale=scale,
            contour_step=m.contour_step, grid_cell=m.grid_cell, fade_coverage=m.fade_coverage,
            coverage_threshold=m.coverage_threshold, fade_mode=m.fade_mode,
            shown=m.shown if m.shown is not None else style.shown), la.error))
    return out


def _context_for_look(context, look):
    points = [p for p in context.points
              if (p.kind == "borehole" and look.boreholes) or (p.kind != "borehole" and look.context)]
    if not look.context:
        context = replace(context, crossings=[], band=[], ties=[])
    return replace(context, points=points,
                   field_notes=context.field_notes if look.field_notes else [])


def _polyline_length(xy: np.ndarray) -> float:
    return float(np.hypot(*np.diff(xy, axis=0).T).sum()) if len(xy) > 1 else 0.0


def layer_name(dataset: Dataset) -> str:
    return dataset.name or os.path.basename(dataset.source_path)


def _companion_mtime(path: str, options: dict) -> float | None:
    """Modification time of a file read together with the data file (a model response):
    re-inverting rewrites it, and the misfit must follow."""
    response = (options or {}).get("response")
    if not response:
        return None
    resp = response if os.path.isabs(response) else os.path.join(os.path.dirname(path),
                                                                  response)
    return os.stat(resp).st_mtime if os.path.isfile(resp) else -1.0


def _auto_scale(mesh: SectionMesh, d: Dataset) -> ColorScale:
    """Misfit: diverging, symmetric about 0 (98th percentile of |misfit|); readings'
    resistivities: log; models: as before."""
    if mesh.readings is not None:
        v = np.asarray(mesh.point_values, float)
        v = v[np.isfinite(v)]
        if mesh.quantity == "misfit":
            m = float(np.percentile(np.abs(v), 98)) if v.size else 1.0
            m = m if m > 0 else 1.0
            return ColorScale(MISFIT_CMAP, -m, m, False)
        return ColorScale.auto(v[v > 0] if v.size else np.array([1.0, 10.0]), log=True)
    return ColorScale.auto(mesh.values, log=(d.quantity == "resistivity"))


def _reading_hit(layer: SectionLayer, s: float, z: float) -> dict | None:
    """The reading nearest to (s, z) when the point lies on the pseudosection or close to a
    reading (1.5 x the median distance between readings)."""
    mesh = layer.mesh
    pts = mesh.vertices
    d2 = (pts[:, 0] - s) ** 2 + (pts[:, 1] - z) ** 2
    i = int(np.argmin(d2))
    tri = mesh.cells[:, :3]
    edges = np.hypot(*(pts[tri[:, 0]] - pts[tri[:, 1]]).T)
    near = np.sqrt(d2[i]) <= 1.5 * float(np.median(edges)) if len(edges) else False
    if not near and not np.isfinite(mesh.value_at(s, z)):
        return None
    r = mesh.readings
    value = float(mesh.point_values[i])
    if not np.isfinite(value):
        return None
    mis = r.misfit_percent()
    d = layer.dataset
    return {"name": layer_name(d), "value": value, "unit": mesh.unit, "version": d.version,
            "quantity": mesh.quantity, "dataset_id": d.id, "s": float(s), "z": float(z),
            "reading": {k: float(np.asarray(getattr(r, k))[i]) for k in
                        ("a", "b", "m", "n", "measured", "calculated")}
            | {"misfit": float(mis[i]),
               "error": None if r.error is None else float(r.error[i])}}


def identify_layers(layers: list[SectionLayer], s: float, z: float) -> list[dict]:
    """Values under (s, z), topmost (last drawn) layer first. Hidden layers, layers
    with errors and cells without a value are skipped."""
    out = []
    for layer in reversed(layers):
        if not layer.style.visible or layer.error is not None or layer.mesh is None:
            continue
        if layer.mesh.readings is not None:
            hit = _reading_hit(layer, s, z)
            if hit is not None:
                out.append(hit)
            continue
        value = layer.mesh.value_at(s, z)
        if not np.isfinite(value):
            continue
        d = layer.dataset
        out.append({"name": layer_name(d), "value": value, "unit": d.unit, "version": d.version,
                    "quantity": d.quantity, "dataset_id": d.id, "s": float(s), "z": float(z)})
    return out


def cell_path_groups(mesh: SectionMesh, scale: ColorScale,
                     alpha: np.ndarray | None = None) -> list[tuple[np.ndarray, np.ndarray]]:
    """Cells grouped by colour as ``[(rgba uint8 (4,), PATH_ELEMENT array), ...]``.

    Each cell becomes a closed ring of 5 path elements (MoveTo + 4 LineTo), so a group's
    array serialises straight into one QPainterPath. Transparent (nan) cells are dropped.
    Fully vectorised: the only Python loop is over the (<= ~256) distinct colours."""
    rgba = scale.rgba(mesh.values)
    if alpha is not None:                       # coverage fade: per-cell alpha factor
        rgba[:, 3] = (rgba[:, 3] * np.asarray(alpha, float)).astype(np.uint8)
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


class SectionDataProvider:
    """Assembles the section layers of each profile from a ``ProjectStore``."""

    def __init__(self, store: ProjectStore):
        self.store = store
        self.on_change: list[Callable[[], None]] = []
        #: profile shown in the section panel; wins when several profiles share a curve.
        #: Set and read on the main thread only (snapshots stay plain data).
        self.active_profile_id: str | None = None
        self._styles: dict[str, LayerStyle] = {}
        self._shown_meshes: dict = {}      # (dataset, read, shown) -> (read mesh, shown mesh)
        self._readings_seen: set[str] = set()
        self._cache: dict[str, tuple[tuple, readers.ReaderResult]] = {}
        self._gathered = GatheredContext()
        self._ties: dict[str, tuple[float, list[Tie]]] = {}     # id -> (near_miss, ties)
        #: without a true crossing, profiles closer than this (metres) still tie
        self.near_miss: float = 10.0
        #: profile id -> last ``context_source`` error ("Type: message"); cleared on success
        self.context_errors: dict[str, str] = self._gathered.errors
        #: called as (profile_id, message) when ``context_source`` raises
        self.on_context_error: Callable[[str, str], None] | None = None
        #: interpretation version shown on the section; None = the current one
        self.interp_version_id: str | None = None
        #: draw the profiles' field notes (the section's "Show field notes" switch)
        self.show_field_notes: bool = True
        #: frozen version drawn faintly behind the shown one; None = no comparison
        self.interp_compare_version_id: str | None = None
        #: returns the derived interpretation layers (name -> layer) whose styles are used
        self.interp_layers: Callable[[], dict] | None = None

    @property
    def context_source(self) -> Callable[[Profile], ContextItems] | None:
        """Gathers a profile's context in forward chainage; called on the main thread.
        Setting it drops the cached context and its errors."""
        return self._gathered.source

    @context_source.setter
    def context_source(self, source: Callable[[Profile], ContextItems] | None) -> None:
        self._gathered.source = source
        self._gathered.clear()
        self._gathered.errors.clear()
        self._ties.clear()

    def notify_changed(self) -> None:
        """Store, styles or context layers changed: drop the cached context and ties (they
        depend on all three, and on the topography choice), then tell the listeners."""
        self._gathered.clear()
        self._ties.clear()
        for callback in list(self.on_change):
            callback()

    def set_borehole_views(self, views: dict) -> None:
        """Only the boreholes' look changed (the viewer): patch the cached context and
        redraw, without gathering every profile again."""
        self._gathered.set_borehole_views(views)
        self.notify_redraw()

    def notify_redraw(self, ties: bool = False) -> None:
        """Only what is drawn changed (a style, the interpretation): keep the gathered
        context (DEM, boreholes, crossings), drop the ties only when ``ties`` (they depend
        on visible layers), then tell the listeners."""
        if ties:
            self._ties.clear()
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
        self.notify_redraw(ties=True)

    def remove_dataset(self, dataset_id: str) -> None:
        """Delete ``dataset_id`` from the store (the model file stays), forget its style
        and cached read, and tell the listeners."""
        self.store.delete_dataset(dataset_id)
        self._styles.pop(dataset_id, None)
        self._cache.pop(dataset_id, None)
        self.notify_changed()

    # -- topography and stations -----------------------------------------------------------
    def _profile(self, profile_id: str) -> Profile | None:
        try:
            return self.store.profile(profile_id)
        except KeyError:
            return None

    def _chosen_topography(self, profile: Profile | None, sets: list[StationSet]):
        """(surface line or None, True when that line is the DEM)."""
        stations = station_line(sets)
        if profile is not None and (stations is None
                                    or profile.metadata.get("topography") == "dem"):
            # the chosen DEM, or the only surface there is when the stations have no heights
            line = dem_line(self._items(profile).dem, stations)
            if line is not None:
                return line, True
        return stations, False

    def topography(self, profile_id: str) -> tuple[np.ndarray, np.ndarray] | None:
        """The surface depth models hang from: the DEM line when the profile's choice is
        "dem" and the DEM has data along it, otherwise the station elevations."""
        return self._chosen_topography(self._profile(profile_id),
                                       self.store.station_sets(profile_id))[0]

    def set_topography_source(self, profile_id: str, source: str) -> None:
        if source not in TOPOGRAPHY_SOURCES:
            raise ValueError(f"topography source must be one of {TOPOGRAPHY_SOURCES}, "
                             f"got {source!r}")
        profile = self.store.profile(profile_id)
        profile.metadata["topography"] = source
        self.store.save_profile(profile)
        self.notify_changed()

    def coverage(self, profile_id: str) -> tuple[float, float] | None:
        """(min, max) station chainage over the profile's station sets; beyond it a
        model has no stations (and a depth model no measured surface)."""
        return station_coverage(self.store.station_sets(profile_id))

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
               path, d.reader, _companion_mtime(path, d.reader_options))
        hit = self._cache.get(d.id)
        if hit is not None and hit[0] == key:
            return hit[1]
        result = readers.read(path, reader=d.reader or None, **read_options(d.reader_options))
        self._cache[d.id] = (key, result)
        return result

    def _load_mesh(self, d: Dataset, station_set: StationSet | None,
                   topo: tuple[np.ndarray, np.ndarray] | None) -> SectionMesh:
        if station_set is None:
            raise ValueError(f"station set {d.station_set_id} not found")
        result = self._read(d)
        base = result.mesh
        if base.readings is not None:
            base = self._shown_mesh(d, base)
        mesh = base.with_x(lambda x: data_to_chainage(x, station_set, d))
        if d.reader_options.get("z_kind", result.z_kind) == "depth":
            if topo is None:
                raise ValueError(DEPTH_NEEDS_TOPO)
            mesh = mesh.depth_to_elevation(*topo)
        return mesh

    def shown_value(self, d: Dataset, readings) -> str:
        """What a readings layer shows: the style's choice when the file has it, else misfit
        when it has calculated values, else measured."""
        wanted = self.style(d.id).shown
        if wanted in ("misfit", "calculated") and not readings.has_calculated:
            wanted = None
        if wanted in ("misfit", "measured", "calculated"):
            return wanted
        return "misfit" if readings.has_calculated else "measured"

    def _shown_mesh(self, d: Dataset, base: SectionMesh) -> SectionMesh:
        """The readings' pseudosection with the chosen value (cached per read result)."""
        from ..core.readings import readings_mesh
        shown = self.shown_value(d, base.readings)
        key = (d.id, id(base), shown)
        hit = self._shown_meshes.get(key)
        if hit is None:
            for k in [k for k in self._shown_meshes if k[0] == d.id and k[1] != id(base)]:
                del self._shown_meshes[k]              # an older read of this dataset
            hit = self._shown_meshes[key] = (base, readings_mesh(base.readings, shown))
        return hit[1]

    def _layer(self, d: Dataset, sets: dict[str, StationSet], topo) -> SectionLayer:
        style = self.style(d.id)
        try:
            mesh = self._load_mesh(d, sets.get(d.station_set_id), topo)
            if mesh.readings is not None and d.id not in self._readings_seen:
                self._readings_seen.add(d.id)
                style.mode = "points"              # a pseudosection: one marker per reading
            if style.scale is None:
                style.scale = _auto_scale(mesh, d)
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
        topo, dem_topo = self._chosen_topography(self._profile(profile_id), sets)
        by_id = {s.id: s for s in sets}
        layers = [self._layer(d, by_id, topo) for d in self.store.datasets(profile_id)]
        return layers, sets, topo, dem_topo

    def layers(self, profile_id: str) -> list[SectionLayer]:
        return self._assemble(profile_id)[0]

    # -- context and ties ------------------------------------------------------------------
    def _items(self, profile: Profile) -> ContextItems:
        """What ``context_source`` gathers for ``profile`` (no ties); cached until
        ``notify_changed()``, failures recorded in ``context_errors``."""
        return self._gathered.items(profile, self.on_context_error)

    def ties(self, profile_id: str) -> list[Tie]:
        """Ties with every other profile in the store, columns from that profile's visible
        layers. Cached until ``notify_changed()`` or a new ``near_miss``."""
        from .ties_data import build_ties       # ties_data imports this module
        hit = self._ties.get(profile_id)
        if hit is not None and hit[0] == self.near_miss:
            return hit[1]
        ties = build_ties(profile_id, self.store.profiles(), self.near_miss,
                          lambda pid: self._assemble(pid)[0])
        self._ties[profile_id] = (self.near_miss, ties)
        return ties

    def has_dem(self, profile_id: str) -> bool:
        """True when the gathered context has a DEM; cheap (cached, no ties)."""
        profile = self._profile(profile_id)
        return profile is not None and self._items(profile).dem is not None

    def context(self, profile_id: str) -> ContextItems | None:
        """Gathered context with the ties, in forward chainage; None for an unknown
        profile. Shares the cached data: read-only."""
        profile = self._profile(profile_id)
        if profile is None:
            return None
        notes = [n for n in self.store.field_notes(profile_id) if n.shown] \
            if self.show_field_notes else []
        return replace(self._items(profile), ties=self.ties(profile_id), field_notes=notes)

    def snapshot(self, profile_id: str, reverse: bool = False, look=None) -> SectionSnapshot:
        """Detached plain-data copy for a generator thread. ``reverse`` mirrors chainage
        (s -> length - s) for a profile curve drawn end-to-start. ``look`` (a plate frame's
        ``core.plates.FrameLook``) replaces the panel's look: only its models, with its scale,
        mode and opacity; its interpretation version; boreholes, notes, context as it says."""
        layers, sets, topo, dem_topo = self._assemble(profile_id)
        if look is not None:
            layers = _layers_for_look(layers, look)
        stations, heights = station_marks(sets)     # heights: plain z, unchanged by mirroring
        if topo is not None:
            topo = (topo[0].copy(), topo[1].copy())
        layers = [SectionLayer(la.dataset, la.mesh, _copy_style(la.style), la.error)
                  for la in layers]
        coverage = station_coverage(sets)
        context = copy.deepcopy(self.context(profile_id))
        if look is not None and context is not None:
            # the plate's own notes switch, not the panel's
            notes = [n for n in self.store.field_notes(profile_id) if n.shown]
            context = _context_for_look(replace(context, field_notes=notes), look)
        if reverse:
            length = self.store.profile(profile_id).chainage.length
            for la in layers:
                if la.mesh is not None:
                    la.mesh = la.mesh.with_x(lambda x: length - x)
            if topo is not None:
                topo = (length - topo[0][::-1], topo[1][::-1].copy())
            stations = [(length - s, label) for s, label in stations]
            if coverage is not None:
                coverage = (length - coverage[1], length - coverage[0])
            if context is not None:
                context = context.mirrored(length)
        snap = SectionSnapshot(profile_id, layers, topo, stations, coverage, context, heights,
                               dem_topo)
        version = None if look is None else (look.interp_version or self._latest_version())
        self._add_interpretation(snap, profile_id, reverse, version, compare=look is None)
        return snap

    def _latest_version(self) -> str | None:
        return self.store.current_version().id if self.store.has_interpretation() else None

    def store_has_profile(self, profile_id: str) -> bool:
        return self._profile(profile_id) is not None

    def shown_interp_version(self) -> str | None:
        if not self.store.has_interpretation():
            return None
        return self.interp_version_id or self.store.current_version().id

    def _add_interpretation(self, snap: SectionSnapshot, profile_id: str, reverse: bool,
                            version: str | None = None, compare: bool = True) -> None:
        version = version or self.shown_interp_version()
        if version is None:
            return
        from ..core.interp_cross import crossing_marks
        pieces = self.store.pieces(version, profile_id)
        crossings, others = [], {}
        try:
            ties = self.ties(profile_id)
        except Exception:                       # ties must never block the section
            ties = []
        for tie in ties:
            if tie.other_id not in others:
                others[tie.other_id] = self.store.pieces(version, tie.other_id)
            marks = crossing_marks(others[tie.other_id], tie.s_other, self.near_miss)
            if marks:
                crossings.append((tie.s, marks))
        compare_id = self.interp_compare_version_id if compare else None
        compare = []
        if compare_id and compare_id != version and any(
                v.id == compare_id for v in self.store.versions()):
            compare = self.store.pieces(compare_id, profile_id)
        if not pieces and not crossings and not compare:
            return
        marked = {m.piece_id for _s, marks in crossings for m in marks}
        other_pieces = [p for ps in others.values() for p in ps if p.id in marked]
        from .interp_render import piece_symbols, twin_features
        features = {f.id: f for f in self.store.features(version)}
        if compare:
            features.update({f.id: f for f in self.store.features(compare_id)})
        layers = self.interp_layers() if self.interp_layers is not None else {}
        current_id = self.store.current_version().id
        twins = twin_features([f for f in features.values() if f.version_id != current_id],
                              self.store.features(current_id))
        snap.interp_symbols = piece_symbols(pieces + other_pieces + compare, features, layers,
                                            twins)
        if reverse:
            length = self.store.profile(profile_id).chainage.length
            for p in pieces + compare:
                p.vertices = [(length - s, z) for s, z in p.vertices]
            crossings = [(length - s, marks) for s, marks in crossings]
        snap.interpretation, snap.interp_features = pieces, features
        snap.interp_crossings, snap.interp_compare = crossings, compare

    def identify(self, profile_id: str, s: float, z: float) -> list[dict]:
        """Values at forward profile chainage ``s`` (0 at the profile's first vertex) and
        elevation ``z``. The profile source's ``results.identify`` takes *canvas*
        distance instead, which is mirrored (length - s) for a reversed curve."""
        return identify_layers(self.layers(profile_id), s, z)
