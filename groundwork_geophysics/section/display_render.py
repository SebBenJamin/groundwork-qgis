"""Per-layer drawables of the section for the display modes: cells, a smooth colour field,
contour lines with labels, and the coverage fade; for a reflection section, its picture at
three sizes.

``build_drawing`` runs in the profile generator (worker thread) and touches plain data and
value-type Qt classes only (QColor, QPainterPath, QImage). The smooth field and contours are
cached, so redraws while panning or zooming reuse them. Readouts never use these: they ask
the mesh (``identify_layers``)."""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from dataclasses import field as dc_field
from pathlib import Path

import numpy as np
from qgis.PyQt.QtCore import QPointF, QRectF
from qgis.PyQt.QtGui import QColor, QImage, QPainterPath, QPolygonF

from ..core.gridding import (FADE_ALPHA, contour_levels, contour_lines, coverage_alpha,
                             default_threshold, fade_band, grid_model, grid_shape,
                             next_to_empty, soft_coverage_alpha)
from ..core.trace_section import _sample, display_values, reduce_image

CONTOUR_PEN_MM = 0.25
CONTOUR_MINOR_PEN_MM = 0.13          # typed minor levels: thinner, no label
CONTOUR_DARKER = 167            # QColor.darker factor: about 40 % darker than the scale colour
LABEL_MM = 2.6
MARKER_MM = 1.2                 # reading markers (Points mode)
_CACHE_SIZE = 8
_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()
#: a reflection section's finest picture: at most this many pixels each way
LEVEL_CAP = 4096
#: the picture levels are kept on disk only when making them took longer than this
LEVEL_CACHE_MIN_SECONDS = 0.2
#: changes when what a level file holds changes
LEVEL_FORMAT = 1
_RAMP_STEPS = 1024               # colours of a section's ramp table (one more: no value)
_TRACE_CACHE_SIZE = 4
_traces: OrderedDict = OrderedDict()


@dataclass
class LayerDrawing:
    opacity: float
    groups: list = dc_field(default_factory=list)      # [(QColor, QPainterPath)] cells
    field: tuple | None = None                      # (QImage, QRectF in s/z) smooth field
    clip: QPainterPath | None = None                # below the topography, in s/z
    contours: list = dc_field(default_factory=list)    # [(QColor, QPainterPath, [lines], text)]
    markers: list = dc_field(default_factory=list)     # [(QColor, (k, 2) s/z points)]
    #: a trace section: [(QImage, QRectF in s/z)] finest first, then half and quarter size
    levels: list = dc_field(default_factory=list)


def clear_cache() -> None:
    """Forget every kept field, contour set and section picture (in memory; not on disk)."""
    with _lock:
        _cache.clear()
        _traces.clear()


def _fade(layer):
    """Per-cell alpha factor of the coverage fade, or None."""
    st, mesh = layer.style, layer.mesh
    if not st.fade_coverage or getattr(mesh, "coverage", None) is None:
        return None
    thr = st.coverage_threshold
    if thr is None:
        thr = default_threshold(mesh.coverage, getattr(mesh, "coverage_cut", None))
    return thr


def _key(layer, topo, shape):
    st, mesh = layer.style, layer.mesh
    sc = st.scale
    topo_key = None if topo is None else (np.asarray(topo[0]).tobytes(),
                                          np.asarray(topo[1]).tobytes())
    cov = getattr(mesh, "coverage", None)
    return (layer.dataset.id, hash(mesh.vertices.tobytes()), hash(mesh.values.tobytes()),
            None if cov is None else hash(cov.tobytes()), topo_key, shape,
            (sc.cmap, sc.vmin, sc.vmax, sc.log, sc.ramp), st.mode, st.contour_step,
            tuple(st.contour_major), tuple(st.contour_minor),
            st.fade_coverage, st.coverage_threshold, st.fade_mode, st.interpolation.key())


_next_to_empty = next_to_empty            # the section and the 3D view share it


def _field_image(grid, rgba) -> tuple[QImage, QRectF]:
    nz, nx = grid.values.shape
    img = QImage(np.ascontiguousarray(rgba).tobytes(), nx, nz, nx * 4,
                 QImage.Format.Format_RGBA8888).copy()
    ds = (grid.s[-1] - grid.s[0]) / max(nx - 1, 1)
    dz = (grid.z[-1] - grid.z[0]) / max(nz - 1, 1)
    # image row 0 is the lowest z: under the section's world transform (z up) it lands
    # at the bottom, so no flip is needed
    return img, QRectF(grid.s[0] - ds / 2, grid.z[0] - dz / 2, nx * ds, nz * dz)


def contour_pen_mm(major: bool) -> float:
    return CONTOUR_PEN_MM if major else CONTOUR_MINOR_PEN_MM


def _contours(grid, scale, st) -> list:
    """(colour, path, lines, label text, major) per level with lines; minor: no label."""
    from ..core.numbers import fmt_trim
    out = []
    levels = contour_levels(scale, st.contour_step, st.contour_major, st.contour_minor)
    is_major = dict(levels)
    for level, lines in contour_lines(grid, [v for v, _ in levels], scale.log):
        if not lines:
            continue
        major = is_major.get(level, True)
        r, g, b, _a = (int(c) for c in scale.rgba([level])[0])
        path = QPainterPath()
        for line in lines:
            path.moveTo(QPointF(*line[0]))
            for p in line[1:]:
                path.lineTo(QPointF(*p))
        out.append((QColor(r, g, b).darker(CONTOUR_DARKER), path, lines,
                    fmt_trim(level, 3) if major else "", major))
    return out


def _gridded(layer, topo, threshold):
    st, mesh, scale = layer.style, layer.mesh, layer.style.scale
    shape = grid_shape(mesh, st.grid_cell)
    key = _key(layer, topo, shape)
    with _lock:
        hit = _cache.get(key)
        if hit is not None:
            _cache.move_to_end(key)
            return hit
    grid = grid_model(mesh, topo, shape, scale.log, fill_to_ground=True,
                      interp=st.interpolation)
    if grid.note:                       # once per drawing: the result is cached under key
        from qgis.core import Qgis, QgsMessageLog
        QgsMessageLog.logMessage(f"{layer.dataset.name or layer.dataset.id}: {grid.note}",
                                 "Groundwork", Qgis.MessageLevel.Warning)
    low = alpha = None
    if threshold is not None:
        cov = grid_model(mesh, topo, shape, False, values=mesh.coverage,
                         fill_to_ground=True)
        # soft: follows the smoothed coverage over a band, no blocky edge (round 2, F2)
        alpha = soft_coverage_alpha(cov.values, threshold, st.fade_mode,
                                    fade_band(mesh.coverage))
        floor = 0.0 if st.fade_mode == "blank" else FADE_ALPHA
        low = alpha < (floor + 1.0) / 2                 # where contours turn faint
    image = None
    if st.mode in ("smooth", "smooth+contours"):
        nz, nx = grid.values.shape
        rgba = scale.rgba(grid.values.ravel()).reshape(nz, nx, 4).copy()
        if alpha is not None:
            rgba[..., 3] = np.round(rgba[..., 3] * alpha).astype(np.uint8)
        rgba[..., 3] = np.where(_next_to_empty(grid, mesh), 0, rgba[..., 3])
        image = _field_image(grid, rgba)
    contours = []
    if st.mode in ("contours", "smooth+contours"):
        if low is None:
            contours = _contours(grid, scale, st)
        else:                           # the low-coverage part blanked, or faded
            good = replace(grid, values=np.where(low, np.nan, grid.values))
            contours = _contours(good, scale, st)
            if st.fade_mode != "blank":
                faint = replace(grid, values=np.where(low, grid.values, np.nan))
                for colour, path, lines, _text, major in _contours(faint, scale, st):
                    colour = QColor(colour)
                    colour.setAlphaF(FADE_ALPHA)
                    contours.append((colour, path, lines, "", major))  # no labels in the fade
    entry = (image, contours)
    with _lock:
        _cache[key] = entry
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return entry


def _cell_groups(layer, threshold, cell_path_groups, path_from_elements) -> list:
    """The cells as one path per colour, kept on the mesh for its last look (colour scale
    and fade): every pan or zoom draws them again, and grouping a big model's cells took
    seconds."""
    st, mesh = layer.style, layer.mesh
    sc = st.scale
    look = (sc, threshold, st.fade_mode if threshold is not None else None)
    memo = getattr(mesh, "_memo", {})
    hit = memo.get("cell_groups")
    if hit is not None and hit[0] == look:
        return hit[1]
    alpha = None if threshold is None else coverage_alpha(mesh.coverage, threshold,
                                                          st.fade_mode)
    groups = [(QColor(*(int(c) for c in rgba)), path_from_elements(elems))
              for rgba, elems in cell_path_groups(mesh, sc, alpha)]
    memo["cell_groups"] = (look, groups)
    return groups


def _as_cells(layer):
    from dataclasses import replace
    return replace(layer, style=replace(layer.style, mode="cells"))


# -- reflection sections ---------------------------------------------------------------------
@dataclass(eq=False)
class _TraceEntry:
    """One trace layer's kept picture: the value grids of its levels (before colouring) and the
    last colouring of them."""
    #: the gained copy the grids were made from; None: the file's own array (no display
    #: option), or grids read back from disk
    shown: np.ndarray | None
    #: the values shown, sampled as ``color_limits`` samples them (the limits come from it)
    sample: np.ndarray
    grids: list                      # [(values (h, w) float32, row 0 at zmax, extent)]
    limits: dict = dc_field(default_factory=dict)      # clip percent -> (lo, hi)
    look: tuple | None = None        # the colours ``levels`` were made with
    levels: list = dc_field(default_factory=list)


def _array_key(a: np.ndarray) -> tuple:
    """Which samples ``a`` holds: its buffer and layout (a view of the same samples, such as
    a snapshot's copy of the layer, gives the same key)."""
    return (a.__array_interface__["data"][0], a.shape, a.strides, a.dtype.str)


def _digest(*parts) -> str:
    h = hashlib.sha1()
    for part in parts:
        h.update(part if isinstance(part, bytes) else repr(part).encode("utf-8", "replace"))
    return h.hexdigest()[:16]


def _placement(placed) -> str:
    return _digest(placed.section.x.tobytes(), np.asarray(placed.z_top, float).tobytes(),
                   np.asarray(placed.depths, float).tobytes())


def _values_key(layer) -> tuple:
    read = None if layer.level_cache is None else layer.level_cache[1]
    return (layer.dataset.id, _array_key(layer.traces.section.amplitudes), read,
            layer.style.gain)


def _trace_key(layer) -> tuple:
    return _values_key(layer) + (_placement(layer.traces),)


def _trace_entry(layer) -> _TraceEntry | None:
    with _lock:
        return _traces.get(_trace_key(layer))


def shown_values(layer):
    """The values a trace layer's drawing shows, sampled for its colour limits
    (``trace_limits`` takes them as ``values``), when a drawing with the layer's gain is
    kept; else None."""
    key = _values_key(layer)
    with _lock:
        for k, entry in _traces.items():
            if k[:4] == key:
                return entry.sample
    return None


def _level_path(layer) -> Path | None:
    """``<dataset id>.<key hash>.levels.npz`` in the layer's cache folder, keyed by the read,
    the placement and the gain; None when the layer has no folder."""
    if layer.level_cache is None:
        return None
    folder, read = layer.level_cache
    gain = json.dumps(layer.style.gain.to_dict(), sort_keys=True)
    digest = _digest(read, _placement(layer.traces), gain, LEVEL_CAP, LEVEL_FORMAT)
    return Path(folder) / f"{layer.dataset.id}.{digest}.levels.npz"


def _load_levels(path: Path | None):
    """(grids, sample) kept at ``path``, or None (missing, unreadable or not a level file)."""
    if path is None or not path.is_file():
        return None
    try:
        with np.load(path, allow_pickle=False) as f:
            extents = np.asarray(f["extents"], float).reshape(-1, 4)
            grids = [(np.asarray(f[f"v{i}"], np.float32), tuple(float(v) for v in extents[i]))
                     for i in range(len(extents))]
            sample = np.asarray(f["sample"])
    except Exception:                           # noqa: BLE001 - any bad file is no file
        return None
    if not grids or any(g.ndim != 2 or 0 in g.shape for g, _e in grids):
        return None
    return grids, sample


def _save_levels(path: Path, dataset_id: str, grids: list, sample: np.ndarray) -> None:
    """Write the grids (whole or not at all) and delete the dataset's older level files; a
    folder that cannot be written is ignored."""
    tmp = path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.part")
    arrays = {f"v{i}": g for i, (g, _e) in enumerate(grids)}
    arrays["extents"] = np.array([e for _g, e in grids], float)
    arrays["sample"] = sample
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as f:
            np.savez(f, **arrays)
        os.replace(tmp, path)
        for old in path.parent.glob(f"{dataset_id}.*.levels.npz"):
            if old != path:
                old.unlink(missing_ok=True)
    except (OSError, ValueError):
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _make_grids(placed, values) -> list:
    """The finest picture (at most ``LEVEL_CAP`` each way) and those at half and a quarter of
    its size, each reduced from the samples (so each keeps the strongest)."""
    finest = reduce_image(placed, LEVEL_CAP, LEVEL_CAP, amplitudes=values)
    h, w = finest[0].shape
    out = [finest]
    for f in (2, 4):
        out.append(reduce_image(placed, max(1, -(-w // f)), max(1, -(-h // f)),
                                amplitudes=values))
    return out


def _entry(layer) -> _TraceEntry:
    """The layer's kept entry: from memory, else from its level file, else made (and kept on
    disk when that took long). One entry per dataset and samples: a new gain or placement
    replaces the old one, and its gained copy with it."""
    key = _trace_key(layer)
    with _lock:
        hit = _traces.get(key)
        if hit is not None:
            _traces.move_to_end(key)
            return hit
    path = _level_path(layer)
    kept = _load_levels(path)
    if kept is not None:
        entry = _TraceEntry(None, kept[1], kept[0])
    else:
        started = time.perf_counter()
        section = layer.traces.section
        values = display_values(section, layer.style.gain)
        grids = _make_grids(layer.traces, values)
        sample = np.array(_sample(values))
        entry = _TraceEntry(None if values is section.amplitudes else values, sample, grids)
        if path is not None and time.perf_counter() - started > LEVEL_CACHE_MIN_SECONDS:
            _save_levels(path, layer.dataset.id, grids, sample)
    with _lock:
        for k in [k for k in _traces if k[:2] == key[:2] and k != key]:
            del _traces[k]
        _traces[key] = entry
        while len(_traces) > _TRACE_CACHE_SIZE:
            _traces.popitem(last=False)
    return entry


def _premultiplied(rgba: np.ndarray) -> np.ndarray:
    """(n, 4) uint8 RGBA as ARGB32 premultiplied words."""
    c = rgba.astype(np.uint32)
    a = c[:, 3]
    rgb = (c[:, :3] * a[:, None] + 127) // 255
    return (a << 24) | (rgb[:, 0] << 16) | (rgb[:, 1] << 8) | rgb[:, 2]


def _coloured(grid: np.ndarray, extent, scale):
    """(QImage, QRectF) of ``grid`` (row 0 at zmax) over ``extent``, or None when the image
    cannot be made. The image's row 0 is the lowest z (under the section's world transform it
    lands at the bottom), NaN transparent; the image holds its own pixels."""
    h, w = grid.shape
    image = QImage(w, h, QImage.Format.Format_ARGB32_Premultiplied)
    if image.isNull():
        return None
    ptr = image.bits()
    ptr.setsize(image.sizeInBytes())
    out = np.frombuffer(ptr, np.uint32).reshape(h, image.bytesPerLine() // 4)[:, :w]
    lo, hi = float(scale.vmin), float(scale.vmax)
    table = None
    if not scale.log:
        n = _RAMP_STEPS
        table = np.zeros(n + 1, np.uint32)          # the last entry: no value, transparent
        table[:n] = _premultiplied(scale.rgba(np.linspace(lo, hi, n)))
        k = (n - 1) / (hi - lo)
    upright = grid[::-1]
    step = max(1, (1 << 20) // max(1, w))
    for r0 in range(0, h, step):
        rows = upright[r0:r0 + step]
        if table is None:
            words = _premultiplied(scale.rgba(rows)).reshape(rows.shape)
        else:
            with np.errstate(invalid="ignore"):
                t = np.clip(np.rint((rows - lo) * k), 0, _RAMP_STEPS - 1)
            words = table[np.where(np.isfinite(rows), t, _RAMP_STEPS).astype(np.intp)]
        out[r0:r0 + step] = words
    s0, s1, z0, z1 = extent
    return image, QRectF(s0, z0, s1 - s0, z1 - z0)


def _trace_levels(layer) -> list:
    """The trace layer's picture levels in its colours, clipped as its style says."""
    from .data import trace_limits
    st = layer.style
    entry = _entry(layer)
    if st.clip_percent is None:
        lo, hi = trace_limits(layer, st)
    else:
        lo, hi = entry.limits.get(st.clip_percent) or trace_limits(layer, st,
                                                                   values=entry.sample)
        entry.limits[st.clip_percent] = (lo, hi)
    sc = st.scale
    look = (sc.cmap, lo, hi, sc.log, sc.ramp, sc.lut)
    if entry.look == look:
        return entry.levels
    scale = replace(sc, vmin=lo, vmax=hi) if hi > lo and (not sc.log or lo > 0) else sc
    levels = [c for c in (_coloured(g, e, scale) for g, e in entry.grids) if c is not None]
    entry.look, entry.levels = look, levels
    return levels


def level_for(levels: list, transform) -> int:
    """Index of the level to draw through ``transform`` (s/z to device pixels): the coarsest
    whose pixels are no larger than one device pixel, else the finest; worked out along s and
    along z, the finer of the two."""
    sx = math.hypot(transform.m11(), transform.m12())
    sz = math.hypot(transform.m21(), transform.m22())

    def coarsest(scale, size):
        for i in range(len(levels) - 1, -1, -1):
            if size(*levels[i]) * scale <= 1.0 + 1e-9:
                return i
        return 0
    along_s = coarsest(sx, lambda img, rect: rect.width() / max(1, img.width()))
    along_z = coarsest(sz, lambda img, rect: rect.height() / max(1, img.height()))
    return min(along_s, along_z)


def build_drawing(layer, topo) -> LayerDrawing:
    """What to draw for one visible layer with a mesh (or a trace section) and a colour
    scale."""
    from .data import cell_path_groups
    from .profile_source import _path_from_elements
    st = layer.style
    drawing = LayerDrawing(float(st.opacity))
    if layer.mesh is None:
        # a trace section: its picture levels; nothing above the ground is cut off (a datum
        # can lie above it, and the muted top of the section belongs to the data)
        if layer.traces is not None and st.scale is not None:
            try:
                drawing.levels = _trace_levels(layer)
            except (ValueError, MemoryError) as exc:
                from .profile_source import _log_failure
                _log_failure(f"picture of {layer.dataset.id}", exc)
        return drawing
    threshold = _fade(layer)
    pv = getattr(layer.mesh, "point_values", None)
    if st.mode == "points" and pv is not None:          # one marker per reading
        rgba = st.scale.rgba(pv)
        keep = rgba[:, 3] > 0
        packed = rgba[keep].astype(np.uint32) @ np.array([1 << 24, 1 << 16, 1 << 8, 1],
                                                         dtype=np.uint32)
        pts = layer.mesh.vertices[keep]
        for code in np.unique(packed):
            c = [(int(code) >> sh) & 255 for sh in (24, 16, 8, 0)]
            drawing.markers.append((QColor(*c), pts[packed == code]))
        return drawing
    if st.mode == "cells" or st.mode not in ("smooth", "contours", "smooth+contours"):
        drawing.groups = _cell_groups(layer, threshold, cell_path_groups, _path_from_elements)
        return drawing
    try:
        drawing.field, drawing.contours = _gridded(layer, topo, threshold)
    except ValueError as exc:                   # a mesh that cannot be gridded: show cells
        from .profile_source import _log_failure
        _log_failure(f"{st.mode} display of {layer.dataset.id}", exc)
        return build_drawing(_as_cells(layer), topo)
    if drawing.field is not None and topo is not None and len(topo[0]) >= 2:
        # the grid masks above-ground nodes; the clip makes the edge follow the ground exactly
        smin, smax, zmin, _zmax = layer.mesh.bounds()
        ts, tz = (np.asarray(a, float) for a in topo)
        ring = [QPointF(smin - 1.0, float(np.interp(smin - 1.0, ts, tz)))]
        ring += [QPointF(float(s), float(z)) for s, z in zip(ts, tz) if smin - 1 < s < smax + 1]
        ring += [QPointF(smax + 1.0, float(np.interp(smax + 1.0, ts, tz))),
                 QPointF(smax + 1.0, zmin - 1.0), QPointF(smin - 1.0, zmin - 1.0)]
        clip = QPainterPath()
        clip.addPolygon(QPolygonF(ring))
        clip.closeSubpath()
        drawing.clip = clip
    return drawing
