"""Per-layer drawables of the section for the display modes: cells, a smooth colour field,
contour lines with labels, and the coverage fade.

``build_drawing`` runs in the profile generator (worker thread) and touches plain data and
value-type Qt classes only (QColor, QPainterPath, QImage). The smooth field and contours are
cached, so redraws while panning or zooming reuse them. Readouts never use these: they ask
the mesh (``identify_layers``)."""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, replace
from dataclasses import field as dc_field

import numpy as np
from qgis.PyQt.QtCore import QPointF, QRectF
from qgis.PyQt.QtGui import QColor, QImage, QPainterPath, QPolygonF

from ..core.gridding import (FADE_ALPHA, contour_levels, contour_lines, coverage_alpha,
                             default_threshold, fade_band, grid_model, grid_shape,
                             soft_coverage_alpha)

CONTOUR_PEN_MM = 0.25
CONTOUR_MINOR_PEN_MM = 0.13          # typed minor levels: thinner, no label
CONTOUR_DARKER = 167            # QColor.darker factor: about 40 % darker than the scale colour
LABEL_MM = 2.6
MARKER_MM = 1.2                 # reading markers (Points mode)
_CACHE_SIZE = 8
_cache: OrderedDict = OrderedDict()
_lock = threading.Lock()


@dataclass
class LayerDrawing:
    opacity: float
    groups: list = dc_field(default_factory=list)      # [(QColor, QPainterPath)] cells
    field: tuple | None = None                      # (QImage, QRectF in s/z) smooth field
    clip: QPainterPath | None = None                # below the topography, in s/z
    contours: list = dc_field(default_factory=list)    # [(QColor, QPainterPath, [lines], text)]
    markers: list = dc_field(default_factory=list)     # [(QColor, (k, 2) s/z points)]


def _fade(layer):
    """Per-cell alpha factor of the coverage fade, or None."""
    st, mesh = layer.style, layer.mesh
    if not st.fade_coverage or getattr(mesh, "coverage", None) is None:
        return None
    thr = st.coverage_threshold
    if thr is None:
        thr = default_threshold(mesh.coverage)
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
            st.fade_coverage, st.coverage_threshold, st.fade_mode)


def _next_to_empty(grid, mesh) -> np.ndarray:
    """Nodes next to a node outside the mesh or in a cell without a value: their pixel
    would reach half a grid cell into it, so they are left out (the field stops just short
    of empty space instead of overshooting into it). The ground is handled by the clip."""
    cell = grid.cell
    empty = (cell == -1) | ((cell >= 0) & ~np.isfinite(mesh.values[np.maximum(cell, 0)]))
    pad = np.pad(empty, 1, constant_values=True)
    near = pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
    return near & ~empty


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
    grid = grid_model(mesh, topo, shape, scale.log, fill_to_ground=True)
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


def _as_cells(layer):
    from dataclasses import replace
    return replace(layer, style=replace(layer.style, mode="cells"))


def build_drawing(layer, topo) -> LayerDrawing:
    """What to draw for one visible layer with a mesh and a colour scale."""
    from .data import cell_path_groups
    from .profile_source import _path_from_elements
    st = layer.style
    threshold = _fade(layer)
    drawing = LayerDrawing(float(st.opacity))
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
        alpha = (None if threshold is None
                 else coverage_alpha(layer.mesh.coverage, threshold, st.fade_mode))
        drawing.groups = [(QColor(*(int(c) for c in rgba)), _path_from_elements(elems))
                          for rgba, elems in cell_path_groups(layer.mesh, st.scale, alpha)]
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
