"""Per-layer drawables of the section for the display modes: cells, a smooth colour field,
contour lines with labels, and the coverage fade.

``build_drawing`` runs in the profile generator (worker thread) and touches plain data and
value-type Qt classes only (QColor, QPainterPath, QImage). The smooth field and contours are
cached, so redraws while panning or zooming reuse them. Readouts never use these: they ask
the mesh (``identify_layers``)."""
from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from dataclasses import field as dc_field

import numpy as np
from qgis.PyQt.QtCore import QPointF, QRectF
from qgis.PyQt.QtGui import QColor, QImage, QPainterPath, QPolygonF

from ..core.gridding import (contour_lines, coverage_alpha, default_levels, default_threshold,
                             grid_model, grid_shape)

CONTOUR_PEN_MM = 0.25
CONTOUR_DARKER = 167            # QColor.darker factor: about 40 % darker than the scale colour
LABEL_MM = 2.6
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
            (sc.cmap, sc.vmin, sc.vmax, sc.log), st.mode, st.contour_step,
            st.fade_coverage, st.coverage_threshold, st.fade_mode)


def _field_image(grid, rgba) -> tuple[QImage, QRectF]:
    nz, nx = grid.values.shape
    img = QImage(np.ascontiguousarray(rgba).tobytes(), nx, nz, nx * 4,
                 QImage.Format.Format_RGBA8888).copy()
    ds = (grid.s[-1] - grid.s[0]) / max(nx - 1, 1)
    dz = (grid.z[-1] - grid.z[0]) / max(nz - 1, 1)
    # image row 0 is the lowest z: under the section's world transform (z up) it lands
    # at the bottom, so no flip is needed
    return img, QRectF(grid.s[0] - ds / 2, grid.z[0] - dz / 2, nx * ds, nz * dz)


def _contours(grid, scale, step) -> list:
    out = []
    for level, lines in contour_lines(grid, default_levels(scale, step), scale.log):
        if not lines:
            continue
        r, g, b, _a = (int(c) for c in scale.rgba([level])[0])
        path = QPainterPath()
        for line in lines:
            path.moveTo(QPointF(*line[0]))
            for p in line[1:]:
                path.lineTo(QPointF(*p))
        out.append((QColor(r, g, b).darker(CONTOUR_DARKER), path, lines, f"{level:g}"))
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
    grid = grid_model(mesh, topo, shape, scale.log)
    image = None
    if st.mode in ("smooth", "smooth+contours"):
        nz, nx = grid.values.shape
        rgba = scale.rgba(grid.values.ravel()).reshape(nz, nx, 4).copy()
        if threshold is not None:
            cov = grid_model(mesh, topo, shape, False, values=mesh.coverage)
            a = coverage_alpha(cov.values, threshold, st.fade_mode)
            rgba[..., 3] = (rgba[..., 3] * a).astype(np.uint8)
        image = _field_image(grid, rgba)
    contours = (_contours(grid, scale, st.contour_step)
                if st.mode in ("contours", "smooth+contours") else [])
    entry = (image, contours)
    with _lock:
        _cache[key] = entry
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return entry


def build_drawing(layer, topo) -> LayerDrawing:
    """What to draw for one visible layer with a mesh and a colour scale."""
    from .data import cell_path_groups
    from .profile_source import _path_from_elements
    st = layer.style
    threshold = _fade(layer)
    drawing = LayerDrawing(float(st.opacity))
    if st.mode == "cells" or st.mode not in ("smooth", "contours", "smooth+contours"):
        alpha = (None if threshold is None
                 else coverage_alpha(layer.mesh.coverage, threshold, st.fade_mode))
        drawing.groups = [(QColor(*(int(c) for c in rgba)), _path_from_elements(elems))
                          for rgba, elems in cell_path_groups(layer.mesh, st.scale, alpha)]
        return drawing
    drawing.field, drawing.contours = _gridded(layer, topo, threshold)
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
