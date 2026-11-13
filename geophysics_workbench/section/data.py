"""Per-profile section data: meshes in chainage/elevation, styles, topography, stations,
context items and profile ties.

QGIS-free except for the coordinate transform of map-coordinate files (imported when one is
read). ``SectionDataProvider`` reads the project store and model files on the main thread
and places each dataset on its profile (``placement_resolve``) once, until the profile's
line, station sets, datasets, files or metadata change; ``SectionSnapshot`` is the
plain-data copy handed to profile-generator threads.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np

from .. import readers
from ..readers.errors import plain_error
from ..core.colors import ColorScale
from ..core.context import ContextItems, borehole_key
from ..core.coverage import station_coverage
from ..core.layout import Electrodes, derived_electrodes, guess_electrodes
from ..core.model import Dataset, Profile, StationSet
from ..core.placement import DistanceMap, FitReport
from ..core.section_mesh import SectionMesh
from ..core.ties import Tie
from ..store.gpkg_store import ProjectStore
from .context_cache import GatheredContext
from .placement_resolve import NO_ELECTRODES_NOTE, ProfileLayout, Resolution, resolve
from .topography import (TOPOGRAPHY_SOURCES, Surface, dem_line, flat_line, local_surface,
                         station_line, station_marks, topo_set)

#: reader_options keys applied by the provider, not passed to the reader as such
WORKBENCH_KEYS = ("z_kind", "chainage_offset", "placement")


def read_options(reader_options: dict) -> dict:
    """Options for ``readers.read``: the reader's own options plus the user's ``z_kind``
    choice, which decides where a cell-centre model's top edge goes (depth 0 or not)."""
    options = {k: v for k, v in reader_options.items() if k not in WORKBENCH_KEYS}
    if reader_options.get("z_kind"):
        options["z_kind"] = reader_options["z_kind"]
    return options


def is_map_dataset(d: Dataset) -> bool:
    """True for a free-text dataset positioned by map coordinates (easting, northing)."""
    columns = d.reader_options.get("columns")
    return isinstance(columns, dict) and columns.get("position") == "map"


def _past_ends(xy: np.ndarray, line: np.ndarray, tol: float = 1e-6) -> np.ndarray:
    """True for points lying past the line's first or last vertex along the end segment's
    direction."""
    out = np.zeros(len(xy), dtype=bool)
    for end, inner in ((line[0], line[1]), (line[-1], line[-2])):
        u = (end - inner) / np.hypot(*(end - inner))
        out |= (xy - end) @ u > tol
    return out


def xy_to_distance_on(profile: Profile, file_crs: str, store_crs: str) -> Callable:
    """``xy_to_distance(easting, northing) -> (chainage, offset, beyond)`` for the free-text
    reader: map coordinates in ``file_crs`` ("" = the store's) projected onto ``profile``'s
    line in ``store_crs``. Never stored."""
    chainage = profile.chainage
    line = chainage.xy
    transform = None
    if file_crs and file_crs != store_crs:
        from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
        source = QgsCoordinateReferenceSystem(file_crs)
        if not source.isValid():
            raise ValueError(f"unknown coordinate reference system {file_crs!r}")
        transform = QgsCoordinateTransform(source, QgsCoordinateReferenceSystem(store_crs),
                                           QgsProject.instance())

    def xy_to_distance(easting, northing):
        xy = np.column_stack([np.asarray(easting, float), np.asarray(northing, float)])
        if transform is not None:
            from qgis.core import QgsPointXY
            xy = np.array([[q.x(), q.y()] for q in
                           (transform.transform(QgsPointXY(e, n)) for e, n in xy)],
                          dtype=float).reshape(-1, 2)
        s, offset = chainage.project(xy)
        at_end = (s <= 1e-9) | (s >= chainage.length - 1e-9)
        return s, offset, at_end & _past_ends(xy, line)

    return xy_to_distance


#: why a local section leaves out context (shown when something was left out)
LOCAL_REASON = "No heights on this profile yet: the DEM line and boreholes are not drawn"
#: what the ties panel and the interpretation export say for a profile left out
NO_HEIGHTS = ("Profile {name} has no heights yet: set a reference height to compare and "
              "export it.")
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
    #: typed contour levels in the model's unit; both empty = automatic (``contour_step``).
    #: Major levels are labelled, minor ones drawn thinner without a label
    contour_major: tuple = ()
    contour_minor: tuple = ()
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
    #: where ``stations`` come from: "imported" (a station set), "readings", "spacing",
    #: "guessed" (derived, never stored) or "none"
    electrode_kind: str = "imported"
    #: no real heights (``topography.Surface.local``): drawn in depth below ``topo``, without
    #: the DEM line and the boreholes; ``local_reason`` says so when either was left out
    local: bool = False
    #: what ``topo`` comes from, one of ``topography.SURFACE_KINDS``
    surface_kind: str = "stations"
    local_reason: str = ""


def starts_hidden(d, datasets) -> bool:
    """Measured data start hidden when the profile has a model: the readings' dots would
    cover the model (a misfit layer is added on purpose and shows)."""
    return d.kind == "ert_measured" and any(o.kind == "ert_model" for o in datasets)


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
            contour_step=m.contour_step, contour_major=tuple(m.contour_major),
            contour_minor=tuple(m.contour_minor), grid_cell=m.grid_cell, fade_coverage=m.fade_coverage,
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


def without_heights(context: ContextItems) -> tuple[ContextItems, bool]:
    """``context`` without what needs real elevations (the DEM line, the boreholes) for a
    local section, and whether anything drawable was left out."""
    boreholes = any(p.kind == "borehole" for p in context.points)
    dem = context.dem is not None and bool(np.isfinite(np.asarray(context.dem[1], float)).any())
    return (replace(context, dem=None,
                    points=[p for p in context.points if p.kind != "borehole"]),
            boreholes or dem)


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


@dataclass(frozen=True)
class _Failed:
    """A dataset that could not be read or placed: the message its layer shows.
    ``transient``: an OSError (e.g. a file another program holds for a moment), so the
    build that holds it is not kept (the next build reads the file again). A missing file
    is not: the build key changes when it appears."""
    message: str
    transient: bool = False


@dataclass
class _Built:
    """A profile's placement and surface, kept while ``key`` (``_inputs_key``) still
    matches the store; each is worked out when first needed. ``profile``, ``sets`` and
    ``datasets`` are the copies last read from the store (same content as ``key``)."""
    key: tuple
    profile: Profile | None = None
    sets: list = field(default_factory=list)
    datasets: list = field(default_factory=list)
    placed: dict | None = None
    surface: Surface | None = None
    has_surface: bool = False

    def transient(self) -> bool:
        """True when a dataset failed in a way that may pass (see ``_Failed``)."""
        return self.placed is not None and any(
            isinstance(v, _Failed) and v.transient for v in self.placed.values())


def _transient(exc: BaseException) -> bool:
    return isinstance(exc, OSError) and not isinstance(exc, FileNotFoundError)


def _array_key(a) -> bytes | None:
    return None if a is None else np.ascontiguousarray(a).tobytes()


@dataclass
class _LayoutSources:
    """A profile's layout and the datasets it came from: the readings dataset that gave
    ``readings_x`` and the model that gave the guess, with that model's upper file x."""
    layout: ProfileLayout
    readings: Dataset | None = None
    model: Dataset | None = None
    model_x_max: float | None = None


def _coverage(sets: list[StationSet], electrodes: Electrodes | None
              ) -> tuple[float, float] | None:
    """Station coverage; for derived electrodes their span, None when they are guessed."""
    if sets:
        return station_coverage(sets)
    if electrodes is None or electrodes.kind == "guessed":
        return None
    s = np.asarray(electrodes.chainage, dtype=float)
    s = s[np.isfinite(s)]
    return (float(s.min()), float(s.max())) if s.size else None


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


def _first_top(datasets: list[Dataset], placed: dict, z_kind: str
               ) -> tuple[np.ndarray, np.ndarray] | None:
    """Top edge ``(s, z)`` of the first model of ``z_kind`` placed in ``placed``
    (``SectionDataProvider._placed``); None when there is none. A dataset that could not be
    read, a readings dataset and a mesh without a usable top are skipped."""
    for d in datasets:
        item = placed.get(d.id)
        if not isinstance(item, tuple) or item[1] != z_kind or item[0].readings is not None:
            continue
        try:
            s, z = item[0].top_edge()
        except Exception:                       # an odd mesh just gives no surface
            continue
        if len(s) >= 2:
            return s, z
    return None


class SectionDataProvider:
    """Assembles the section layers of each profile from a ``ProjectStore``."""

    def __init__(self, store: ProjectStore):
        self.store = store
        self.on_change: list[Callable[[], None]] = []
        self.on_data_change: list[Callable[[], None]] = []   # notify_changed only
        #: profile shown in the section panel; wins when several profiles share a curve.
        #: Set and read on the main thread only (snapshots stay plain data).
        self.active_profile_id: str | None = None
        self._styles: dict[str, LayerStyle] = {}
        self._shown_meshes: dict = {}      # (dataset, read, shown) -> (read mesh, shown mesh)
        self._readings_seen: set[str] = set()
        self._cache: dict[str, tuple[tuple, readers.ReaderResult]] = {}
        self._guesses: dict[str, tuple] = {}   # dataset -> (read result, z_kind, guess)
        self._gathered = GatheredContext()
        self._ties: dict[str, tuple[float, list[Tie]]] = {}     # id -> (near_miss, ties)
        self._builds: dict[str, _Built] = {}    # profile id -> its placement and surface
        #: without a true crossing, profiles closer than this (metres) still tie
        self.near_miss: float = 10.0
        #: profile id -> last ``context_source`` error ("Type: message"); cleared on success
        self.context_errors: dict[str, str] = self._gathered.errors
        #: called as (profile_id, message) when ``context_source`` raises
        self.on_context_error: Callable[[str, str], None] | None = None
        #: interpretation version shown on the section; None = the current one
        self.interp_version_id: str | None = None
        #: draw the profiles' field notes (the section's "Show Field Notes" switch)
        self.show_field_notes: bool = True
        #: frozen version drawn faintly behind the shown one; None = no comparison
        self.interp_compare_version_id: str | None = None
        #: returns the derived interpretation layers (name -> layer) whose styles are used
        self.interp_layers: Callable[[], dict] | None = None
        #: note id -> NoteLook from the field-note layers (main thread); None: default look
        self.note_looks: Callable[[], dict] | None = None

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
        self._builds.clear()                    # a surface may come from the DEM

    def notify_changed(self) -> None:
        """Store, styles or context layers changed: drop the cached context, ties, placements
        and surfaces (they depend on all three, and on the topography choice), then tell
        the listeners."""
        self._gathered.clear()
        self._ties.clear()
        self._builds.clear()
        for callback in list(self.on_change):
            callback()
        for callback in list(self.on_data_change):
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
        self._guesses.pop(dataset_id, None)
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

    def _surface(self, profile: Profile | None, sets: list[StationSet],
                 datasets: list[Dataset], place: Callable[[], dict]) -> Surface | None:
        """The profile's one surface: station elevations or the DEM as chosen; else, from
        the datasets placed in chainage (``place()`` gives ``_placed``'s result, asked for
        only here), the top edge of the first elevation model; else that of the first
        local-height model, its highest point at 0; else a flat line at 0 over the profile.
        A dataset that could not be read is skipped. None for an unknown profile."""
        if profile is None:
            return None
        line, is_dem = self._chosen_topography(profile, sets)
        if line is not None:
            return Surface(line, "dem" if is_dem else "stations")
        placed = place()
        top = _first_top(datasets, placed, "elevation")
        if top is not None:
            return Surface(top, "model")
        return self._local_kind_surface(profile, datasets, placed)

    @staticmethod
    def _local_kind_surface(profile: Profile, datasets: list[Dataset],
                            placed: dict) -> Surface:
        """The surface ``profile`` has without real heights: the top edge of its first
        local-height model, its highest point at 0, else a flat line at 0; shifted to the
        reference height when it has one."""
        top = _first_top(datasets, placed, "local")
        if top is not None:
            s, z = top
            return local_surface((s, z - z.max()), "local_model", profile.metadata)
        return local_surface(flat_line(profile.chainage.length), "flat", profile.metadata)

    # -- the placement and surface of a profile, worked out once ------------------------------
    def _file_times(self, d: Dataset) -> tuple:
        path = self.source_path(d)
        try:
            return os.stat(path).st_mtime, _companion_mtime(path, d.reader_options)
        except OSError:
            return None, None

    def _inputs_key(self, profile: Profile | None, sets: list[StationSet],
                    datasets: list[Dataset]) -> tuple:
        """What a profile's placement and surface depend on in the store and on disk: its
        line and metadata, its station sets, its datasets with their files' times and the
        value a readings layer shows. (The DEM is the gathered context's: dropped with it.)"""
        if profile is None:
            return (None,)
        return (_array_key(np.asarray(profile.xy, float)),
                json.dumps(profile.metadata, sort_keys=True, default=str),
                tuple((s.id, _array_key(s.numbers), _array_key(s.xyz), _array_key(s.chainage),
                       _array_key(s.offset), _array_key(s.inline), float(s.metre0))
                      for s in sets),
                tuple((d.id, d.station_set_id, d.kind, d.source_path, d.reader,
                       json.dumps(d.reader_options, sort_keys=True, default=str),
                       self._file_times(d), getattr(self._styles.get(d.id), "shown", None))
                      for d in datasets))

    def _build(self, profile_id: str) -> _Built:
        """The profile's ``_Built``, its inputs read from the store; the placement and
        surface worked out before are kept only while those inputs are unchanged, and not
        after a dataset failed with an OSError (it may read next time)."""
        profile = self._profile(profile_id)
        sets = self.store.station_sets(profile_id)
        datasets = self.store.datasets(profile_id)
        key = self._inputs_key(profile, sets, datasets)
        built = self._builds.get(profile_id)
        if built is None or built.key != key or built.transient():
            built = self._builds[profile_id] = _Built(key)
        built.profile, built.sets, built.datasets = profile, sets, datasets
        return built

    def _placed_of(self, built: _Built) -> dict:
        if built.placed is None:
            built.placed = self._placed(built.profile, built.sets, built.datasets)
        return built.placed

    def _surface_of(self, built: _Built) -> Surface | None:
        if not built.has_surface:
            built.surface = self._surface(built.profile, built.sets, built.datasets,
                                          lambda: self._placed_of(built))
            built.has_surface = True
        return built.surface

    def surface(self, profile_id: str) -> Surface | None:
        """The surface the profile's depth and local-height models hang from (see
        ``_surface``); None only for an unknown profile. Worked out once while the
        profile's line, station sets, datasets and metadata stay as they are."""
        return self._surface_of(self._build(profile_id))

    def is_local(self, profile_id: str) -> bool:
        """True when the profile has no real heights: its section is drawn in depth."""
        surface = self.surface(profile_id)
        return surface is not None and surface.local

    def topography(self, profile_id: str) -> tuple[np.ndarray, np.ndarray] | None:
        """The line of ``surface(profile_id)``; None only for an unknown profile."""
        surface = self.surface(profile_id)
        return None if surface is None else surface.line

    def set_topography_source(self, profile_id: str, source: str) -> None:
        if source not in TOPOGRAPHY_SOURCES:
            raise ValueError(f"topography source must be one of {TOPOGRAPHY_SOURCES}, "
                             f"got {source!r}")
        profile = self.store.profile(profile_id)
        profile.metadata["topography"] = source
        self.store.save_profile(profile)
        self.notify_changed()

    # -- reference height and the interpretation on a local section ------------------------
    def _current_version(self) -> str | None:
        return self.store.current_version().id if self.store.has_interpretation() else None

    def _chainages(self) -> dict:
        return {p.id: p.chainage for p in self.store.profiles()}

    def set_reference_height(self, profile_id: str, s: float | None,
                             z: float | None) -> float:
        """Save the profile's reference height (chainage ``s``, height ``z``) or, with
        ``None``, clear it; the current version's pieces on the profile move by the change
        of the surface's shift (stored as elevations, they stay where they were drawn
        relative to the surface). Returns that change; 0 when nothing moved."""
        built = self._build(profile_id)
        profile = built.profile
        if profile is None:
            raise KeyError(profile_id)
        old = self._surface_of(built)
        if s is None or z is None:
            profile.metadata.pop("reference_height", None)
        else:
            profile.metadata["reference_height"] = {"s": float(s), "z": float(z)}
        new = self._surface(profile, built.sets, built.datasets,
                            lambda: self._placed_of(built))
        dz = float(new.shift - old.shift)
        version = self._current_version()
        if dz != 0.0 and version is not None and self.store.pieces(version, profile_id):
            # shifted pieces hang from the local surface (whenever they were drawn): settle
            # them once real heights arrive
            profile.metadata["local_pieces"] = True
            if self.store.shift_pieces(version, profile_id, dz, profile=profile):
                self.store.rebuild_derived(version, self._chainages())
        else:
            self.store.save_profile(profile)
        self.notify_changed()
        return dz

    def settle_local_interpretation(self, profile_id: str) -> bool:
        """Pieces drawn while the profile had no real heights (``metadata["local_pieces"]``)
        are re-hung once, keeping their depth, from the local surface the profile would have
        without real heights (with its reference shift) onto the real one, now that it has
        station, DEM or model heights. Clears the key; True when it settled. Not undoable."""
        built = self._build(profile_id)
        profile = built.profile
        if profile is None or not profile.metadata.get("local_pieces"):
            return False
        real = self._surface_of(built)
        if real.kind not in ("stations", "dem", "model"):
            return False
        old = self._local_kind_surface(profile, built.datasets, self._placed_of(built))
        del profile.metadata["local_pieces"]
        version = self._current_version()
        if version is None:
            self.store.save_profile(profile)
        elif self.store.rehang_pieces(version, profile_id, old.line, real.line,
                                      profile=profile):
            self.store.rebuild_derived(version, self._chainages())
        self.notify_redraw()
        return True

    def coverage(self, profile_id: str) -> tuple[float, float] | None:
        """(min, max) station chainage over the profile's station sets; beyond it a
        model has no stations (and a depth model no measured surface). Without a station
        set, the span of the derived electrodes; None when they are guessed."""
        sets = self.store.station_sets(profile_id)
        return _coverage(sets, None if sets else self.electrodes(profile_id))

    # -- placement -------------------------------------------------------------------------
    def _model_guess(self, d: Dataset, result: readers.ReaderResult, z_kind: str) -> np.ndarray:
        """``guess_electrodes`` of a read, cached with it (the top edge walk is not free)."""
        hit = self._guesses.get(d.id)
        if hit is None or hit[0] is not result or hit[1] != z_kind:
            hit = self._guesses[d.id] = (result, z_kind, guess_electrodes(result.mesh, z_kind))
        return hit[2]

    def _layout_sources(self, profile: Profile | None, datasets: list[Dataset]
                        ) -> _LayoutSources:
        """The readings x from the first readings dataset that reads and has an electrode
        block, the guess from the first distance-based model that reads, the spacing from
        the profile's metadata. Datasets that cannot be read, or whose electrode block or
        mesh gives nothing usable, are skipped."""
        out = _LayoutSources(ProfileLayout())
        spacing = (profile.metadata.get("electrode_spacing") if profile is not None else None)
        try:
            out.layout.spacing = None if spacing is None else float(spacing)
        except (TypeError, ValueError):
            pass
        for d in datasets:
            if out.readings is not None and out.model is not None:
                break
            if is_map_dataset(d):
                continue
            try:                                # one odd dataset just gives no layout
                result = self._read(d)
                if result.mesh.readings is not None:
                    electrode_x = result.provenance.get("electrode_x")
                    if out.readings is None and electrode_x is not None:
                        readings_x = np.array(
                            [np.nan if v is None else v for v in electrode_x], dtype=float)
                        out.readings, out.layout.readings_x = d, readings_x
                elif out.model is None:
                    guess = self._model_guess(d, result,
                                              d.reader_options.get("z_kind") or result.z_kind)
                    x_max = float(result.mesh.bounds()[1])
                    out.model, out.model_x_max = d, x_max
                    if guess.size >= 2:
                        out.layout.guess = guess
                        out.layout.guessed_spacing = float(np.median(np.diff(guess)))
            except Exception:
                continue
        return out

    def _resolved(self, profile: Profile, sets: list[StationSet], datasets: list[Dataset],
                  sources: _LayoutSources | None = None) -> dict[str, Resolution]:
        """Resolution of every distance-based dataset by id (one that cannot be resolved is
        left out; its layer shows the error)."""
        if sources is None:
            sources = self._layout_sources(profile, datasets)
        out = {}
        for d in datasets:
            if is_map_dataset(d):
                continue
            try:
                out[d.id] = resolve(profile, sets, d, sources.layout)
            except Exception:
                continue
        return out

    def layout(self, profile_id: str) -> ProfileLayout:
        """What the profile's in-line layout is resolved from (see ``ProfileLayout``)."""
        return self._layout_sources(self._profile(profile_id),
                                    self.store.datasets(profile_id)).layout

    def electrodes(self, profile_id: str) -> Electrodes | None:
        """The profile's first station set ("imported"); without one, electrodes derived
        from the readings file, the typed spacing or the model's top (never stored); None
        when there is nothing to go on."""
        sets = self.store.station_sets(profile_id)
        if sets:
            first = topo_set(sets) or sets[0]        # the set the section's ticks use
            return Electrodes(np.asarray(first.numbers), np.asarray(first.chainage, float),
                              "imported")
        profile = self._profile(profile_id)
        if profile is None:
            return None
        datasets = self.store.datasets(profile_id)
        src = self._layout_sources(profile, datasets)
        lay = src.layout
        if src.readings is not None:
            dmap = resolve(profile, sets, src.readings, lay).map
            found = derived_electrodes(dmap, (0.0, 0.0), readings_x=lay.readings_x)
            if found is not None:
                return found
        if src.model is None:
            return None
        # a stated spacing starts at file distance 0, where inline_distances puts station 1
        return derived_electrodes(resolve(profile, sets, src.model, lay).map,
                                  (0.0, src.model_x_max), spacing=lay.spacing, guess=lay.guess)

    def fit(self, profile_id: str, dataset_id: str) -> FitReport | None:
        """How the pins of ``dataset_id`` fit (station numbers as labels); None when that
        dataset is not pinned."""
        profile = self._profile(profile_id)
        if profile is None:
            return None
        datasets = self.store.datasets(profile_id)
        d = next((d for d in datasets if d.id == dataset_id), None)
        if d is None or is_map_dataset(d):
            return None
        return resolve(profile, self.store.station_sets(profile_id), d,
                       self._layout_sources(profile, datasets).layout).fit

    def placement_note(self, profile_id: str) -> str:
        """Why the profile's known points are not used, or that it has no electrode
        positions at all; "" normally."""
        profile = self._profile(profile_id)
        datasets = self.store.datasets(profile_id)
        if profile is None or not datasets:
            return ""
        sets = self.store.station_sets(profile_id)
        for r in self._resolved(profile, sets, datasets).values():
            if r.note:
                return r.note
        if not sets and self.electrodes(profile_id) is None:
            return NO_ELECTRODES_NOTE
        return ""

    # -- layers ----------------------------------------------------------------------------
    def source_path(self, d: Dataset) -> str:
        """Absolute path of ``d``'s model file; a relative ``source_path`` is resolved
        against the store's folder, so a project folder can be moved as a whole."""
        if os.path.isabs(d.source_path):
            return d.source_path
        return os.path.normpath(os.path.join(str(self.store.path.parent), d.source_path))

    def _read(self, d: Dataset, profile: Profile | None = None) -> readers.ReaderResult:
        """Reader result in data coordinates (map-coordinate files: in ``profile``'s
        chainage), cached per dataset until the file, the options or, for a map file, the
        profile's line change. Raises FileNotFoundError / ValueError / OSError."""
        path = self.source_path(d)
        if not os.path.isfile(path):
            raise FileNotFoundError(path)
        on_map = is_map_dataset(d)
        if on_map and profile is None:
            raise ValueError("a file with map coordinates needs its profile line")
        line = (np.asarray(profile.xy, float).tobytes(), self.store.crs_authid) if on_map \
            else None
        key = (d.id, os.stat(path).st_mtime, json.dumps(d.reader_options, sort_keys=True),
               path, d.reader, _companion_mtime(path, d.reader_options), line)
        hit = self._cache.get(d.id)
        if hit is not None and hit[0] == key:
            return hit[1]
        options = read_options(d.reader_options)
        if on_map:
            options["xy_to_distance"] = xy_to_distance_on(
                profile, str(d.reader_options["columns"].get("crs") or ""),
                self.store.crs_authid)
        result = readers.read(path, reader=d.reader or None, **options)
        self._cache[d.id] = (key, result)
        return result

    def _place(self, d: Dataset, dmap: DistanceMap | None,
               profile: Profile | None = None) -> tuple[SectionMesh, str]:
        """(``d``'s mesh in chainage, its z kind): file x through ``dmap`` (None for a
        map-coordinate file, whose x is already chainage), z as read."""
        result = self._read(d, profile)
        base = result.mesh
        if base.readings is not None:
            base = self._shown_mesh(d, base)
        mesh = base if dmap is None else base.with_x(dmap)
        return mesh, d.reader_options.get("z_kind") or result.z_kind

    def _placed(self, profile: Profile | None, sets: list[StationSet],
                datasets: list[Dataset]) -> dict:
        """Every dataset placed in chainage by id: ``_place``'s (mesh, z kind), or a
        ``_Failed`` with the message of what reading or placing it raised (that layer's
        error). Resolved once."""
        layout = None if profile is None else self._layout_sources(profile, datasets).layout
        out = {}
        for d in datasets:
            try:
                dmap = None
                if profile is not None and not is_map_dataset(d):
                    dmap = resolve(profile, sets, d, layout).map
                out[d.id] = self._place(d, dmap, profile)
            except Exception as exc:            # shown as the layer's error
                # only the message: the exception (its traceback, or a chained one's) holds
                # this frame and so ``out``, a cycle that keeps the meshes alive until the
                # garbage collector runs
                out[d.id] = _Failed(self._error_text(d, exc), _transient(exc))
        return out

    def _load_mesh(self, d: Dataset, placed: tuple[SectionMesh, str],
                   surface: Surface | None) -> SectionMesh:
        """``d``'s placed mesh hung from ``surface``: a depth model directly, a local-height
        model as its depth below its own top; an elevation model is drawn as it is."""
        mesh, z_kind = placed
        if surface is None or z_kind not in ("depth", "local"):
            return mesh
        if z_kind == "local":
            mesh = mesh.below_top()
        return mesh.depth_to_elevation(*surface.line)

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

    def _layer(self, d: Dataset, placed, surface: Surface | None) -> SectionLayer:
        """``d``'s layer from its ``_placed`` entry (a placed mesh, or ``_Failed``)."""
        style = self.style(d.id)
        if isinstance(placed, _Failed):
            return SectionLayer(d, None, style, placed.message)
        try:
            mesh = self._load_mesh(d, placed, surface)
            if mesh.readings is not None and d.id not in self._readings_seen:
                self._readings_seen.add(d.id)
                style.mode = "points"              # a pseudosection: one marker per reading
                if starts_hidden(d, self.store.datasets(d.profile_id)):
                    style.visible = False          # don't cover the model; tick to show
            if style.scale is None:
                style.scale = _auto_scale(mesh, d)
        except Exception as exc:                # never raise from layers()
            return SectionLayer(d, None, style, self._error_text(d, exc))
        return SectionLayer(d, mesh, style, None)

    def _error_text(self, d: Dataset, exc: BaseException) -> str:
        """The plain message a layer shows for what reading, placing or hanging raised."""
        src = self.source_path(d)
        if isinstance(exc, FileNotFoundError):
            return plain_error(FileNotFoundError(2, "No such file", src), src)
        if isinstance(exc, OSError) and not isinstance(exc, ValueError):
            return plain_error(OSError(f"cannot read the file ({exc.strerror or exc})"), src)
        return plain_error(exc, src)

    def _assemble(self, profile_id: str):
        """(layers, station sets, surface): every dataset placed in chainage first, then the
        surface worked out from the placed meshes, then depth and local models hung from it.
        The placement and the surface are the profile's cached ones (``_build``)."""
        built = self._build(profile_id)
        placed = self._placed_of(built)
        surface = self._surface_of(built)
        layers = [self._layer(d, placed[d.id], surface) for d in built.datasets]
        return layers, built.sets, surface

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
        # a profile without heights is not compared: its z means nothing next to another's
        ties = [] if self.is_local(profile_id) else [
            t for t in build_ties(profile_id, self.store.profiles(), self.near_miss,
                                  lambda pid: self._assemble(pid)[0])
            if not self.is_local(t.other_id)]
        self._ties[profile_id] = (self.near_miss, ties)
        return ties

    def has_dem(self, profile_id: str) -> bool:
        """True when the gathered context has a DEM; cheap (cached, no ties)."""
        profile = self._profile(profile_id)
        return profile is not None and self._items(profile).dem is not None

    def context(self, profile_id: str, include_hidden: bool = False) -> ContextItems | None:
        """Gathered context with the ties, in forward chainage; None for an unknown
        profile. Boreholes hidden in this profile are left out unless ``include_hidden``
        (the borehole viewer shows them faded). Shares the cached data: read-only."""
        profile = self._profile(profile_id)
        if profile is None:
            return None
        notes = [n for n in self.store.field_notes(profile_id) if n.shown] \
            if self.show_field_notes else []
        items = replace(self._items(profile), ties=self.ties(profile_id), field_notes=notes)
        if self.note_looks is not None and notes:
            try:
                items = replace(items, note_looks=self.note_looks())
            except Exception:                   # a broken layer: the default look
                pass
        hidden = set() if include_hidden else self.hidden_keys(profile_id)
        if hidden:
            items = replace(items, points=[p for p in items.points
                                           if borehole_key(p) not in hidden])
        return items

    def drawn_context(self, profile_id: str, include_hidden: bool = False
                      ) -> ContextItems | None:
        """``context`` as the section draws it: a local section (``is_local``) leaves out
        the DEM line and the boreholes (``without_heights``); otherwise unchanged. Used
        wherever the context is hovered, snapped to, picked or listed."""
        items = self.context(profile_id, include_hidden)
        if items is not None and self.is_local(profile_id):
            items = without_heights(items)[0]
        return items

    def hidden_keys(self, profile_id: str) -> set[tuple[str, str]]:
        """(layer id, borehole id) of the boreholes hidden in ``profile_id``'s section."""
        return self.store.hidden_boreholes(profile_id)

    def set_boreholes_hidden(self, profile_id: str, keys, hidden: bool) -> None:
        """Hide or show boreholes in one profile's section (and its plates), then redraw."""
        self.store.set_boreholes_hidden(profile_id, keys, hidden)
        self.notify_redraw()

    def snapshot(self, profile_id: str, reverse: bool = False, look=None) -> SectionSnapshot:
        """Detached plain-data copy for a generator thread. ``reverse`` mirrors chainage
        (s -> length - s) for a profile curve drawn end-to-start. ``look`` (a plate frame's
        ``core.plates.FrameLook``) replaces the panel's look: only its models, with its scale,
        mode and opacity; its interpretation version; boreholes, notes, context as it says."""
        layers, sets, surface = self._assemble(profile_id)
        topo = None if surface is None else surface.line
        local = surface is not None and surface.local
        if look is not None:
            layers = _layers_for_look(layers, look)
        electrodes = self.electrodes(profile_id)
        # heights: plain z, unchanged by mirroring; NaN for derived electrodes
        stations, heights = station_marks(sets, electrodes)
        if topo is not None:
            topo = (topo[0].copy(), topo[1].copy())
        layers = [SectionLayer(la.dataset, la.mesh, _copy_style(la.style), la.error)
                  for la in layers]
        coverage = _coverage(sets, electrodes)
        context = copy.deepcopy(self.context(profile_id))
        if look is not None and context is not None:
            # the plate's own notes switch, not the panel's
            notes = [n for n in self.store.field_notes(profile_id) if n.shown]
            context = _context_for_look(replace(context, field_notes=notes), look)
            if context.field_notes and not context.note_looks and self.note_looks:
                try:                            # the panel's notes are off: no looks yet
                    context = replace(context, note_looks=self.note_looks())
                except Exception:
                    pass
        local_reason = ""
        if local and context is not None:
            context, left_out = without_heights(context)
            local_reason = LOCAL_REASON if left_out else ""
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
                               surface is not None and surface.kind == "dem",
                               electrode_kind="none" if electrodes is None else electrodes.kind,
                               local=local,
                               surface_kind="stations" if surface is None else surface.kind,
                               local_reason=local_reason)
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
