"""Boreholes and plain points drawn on the section (see ``context_render``)."""
from __future__ import annotations

import numpy as np
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QPainter, QPen, QPolygonF

from ..core.lithology import lithology_colour
from .context_render import draw_label, line_pen, mm, set_label_font

COLUMN_WIDTH = 2.5          # mm
DIAMOND_HALF = 1.2          # mm


def offset_text(offset: float) -> str:
    return f"({'+' if offset >= 0 else '−'}{abs(round(offset))} m)"


def _diamond(painter, x: float, y: float, half: float) -> None:
    painter.setPen(QPen(QColor(0, 0, 0), 1))
    painter.setBrush(QBrush(QColor(0, 0, 0)))
    painter.drawPolygon(QPolygonF([QPointF(x, y - half), QPointF(x + half, y),
                                   QPointF(x, y + half), QPointF(x - half, y)]))


def draw_points(painter, rc, wt, items, surface) -> None:
    if not items.points or surface is None or len(surface[0]) < 1:
        return
    set_label_font(painter, rc)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    width, half = mm(rc, COLUMN_WIDTH), mm(rc, DIAMOND_HALF)
    for p in items.points:
        z_surf = float(np.interp(p.s, *surface))
        z_top = z_surf if p.z_top is None else float(p.z_top)
        top = wt.map(QPointF(p.s, z_top))
        x, y_top = top.x(), top.y()
        if p.kind == "borehole" and p.log:
            for iv in p.log:
                y0 = wt.map(QPointF(p.s, z_top - iv.top)).y()
                y1 = wt.map(QPointF(p.s, z_top - iv.bottom)).y()
                painter.setPen(line_pen(rc, (0, 0, 0), 0.15))
                painter.setBrush(QBrush(QColor(*lithology_colour(iv.lithology))))
                painter.drawRect(QRectF(QPointF(x - width / 2, min(y0, y1)),
                                        QPointF(x + width / 2, max(y0, y1))))
            text = f"{p.label} {offset_text(p.offset)}".strip()
            draw_label(painter, text, x, y_top - 2)
        else:
            y = wt.map(QPointF(p.s, z_surf)).y()
            _diamond(painter, x, y, half)
            if p.label:
                draw_label(painter, p.label, x, y - half - 2)
