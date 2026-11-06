"""Boreholes and plain points (glyphs only; labels are placed by ``context_render``) drawn on the section (see ``context_render``)."""
from __future__ import annotations

import numpy as np
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF

from ..core.borehole_curves import data_range
from ..core.context import collar_height
from .borehole_draw import FLAG_RGB, ColumnOptions, column_depth, draw_borehole
from .context_render import line_pen, mm

COLUMN_WIDTH = 2.5          # mm: boreholes without a Context layers entry (older callers)
SECTION_TRACK_PX = 30       # a curve track on the section
FLAG_MM = 1.4
DIAMOND_HALF = 1.2          # mm
STICK_RGB = (60, 60, 60)    # point with a depth field: a stick down to that depth
STICK_WIDTH = 0.6           # mm


def _diamond(painter, x: float, y: float, half: float) -> None:
    painter.setPen(QPen(QColor(0, 0, 0), 1))
    painter.setBrush(QBrush(QColor(0, 0, 0)))
    painter.drawPolygon(QPolygonF([QPointF(x, y - half), QPointF(x + half, y),
                                   QPointF(x, y + half), QPointF(x - half, y)]))


def column_px(rc, items, p) -> float:
    """The drawn width of borehole ``p``'s column, in pixels."""
    view = items.borehole_views.get(p.entry)
    return float(view.column_px) if view is not None else mm(rc, COLUMN_WIDTH)


def section_options(rc, items, p) -> ColumnOptions:
    view = items.borehole_views.get(p.entry)
    if view is None:
        return ColumnOptions(width_px=mm(rc, COLUMN_WIDTH))
    return ColumnOptions(width_px=float(view.column_px), opacity=view.opacity,
                         layer_text=view.layer_text, curve_keys=tuple(view.curve_keys),
                         track_px=SECTION_TRACK_PX)


def section_ranges(items) -> dict:
    """Each curve key's scale over the profile's boreholes (the style's min/max win later)."""
    out = {}
    keys = {k for v in items.borehole_views.values() for k in v.curve_keys}
    for key in keys:
        style = items.curve_styles.get(key)
        rng = data_range([c for p in items.points for c in p.curves if c.key == key],
                         bool(style and style.log))
        if rng is not None:
            out[key] = rng
    return out


def _flag(painter, x: float, y: float, size: float) -> None:
    """A small red triangle above the collar: field height and DEM disagree."""
    painter.setPen(QPen(QColor(*FLAG_RGB), 1))
    painter.setBrush(QBrush(QColor(*FLAG_RGB)))
    painter.drawPolygon(QPolygonF([QPointF(x - size, y - 2 * size - 1),
                                   QPointF(x + size, y - 2 * size - 1), QPointF(x, y - 1)]))


def draw_points(painter, rc, wt, items, surface) -> None:
    if not items.points or surface is None or len(surface[0]) < 1:
        return
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    half = mm(rc, DIAMOND_HALF)
    ranges = section_ranges(items)
    for p in items.points:
        z_surf = float(np.interp(p.s, *surface))
        z_top = collar_height(p.z_top, None, z_surf)[0]
        top = wt.map(QPointF(p.s, z_top))
        x = top.x()
        if p.kind == "borehole" and column_depth(p) > 0:
            draw_borehole(painter, rc, x, lambda d, s=p.s, z=z_top: wt.map(QPointF(s, z - d)).y(),
                          p, section_options(rc, items, p), items.curve_styles, ranges)
            if p.flagged:
                _flag(painter, x, top.y(), mm(rc, FLAG_MM))
        else:
            y = wt.map(QPointF(p.s, z_surf)).y()
            if p.depth:
                painter.setPen(line_pen(rc, STICK_RGB, STICK_WIDTH))
                bottom = wt.map(QPointF(p.s, z_surf - p.depth)).y()
                painter.drawLine(QPointF(x, y), QPointF(x, bottom))
            _diamond(painter, x, y, half)
