"""One borehole drawing, for the section and the borehole viewer.

A column at screen position ``x_px``: intervals filled with their QGIS symbol (see
``borehole_style``), an outline, optional depth ticks and layer text, and one curve track per
chosen curve to the right. Widths, text and patterns are screen units; only the vertical
position follows the data, through ``y_of_depth`` (depth below the collar -> pixel y).
The look's constants live here (interim styling rule)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from qgis.core import Qgis, QgsFeature
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPen, QPolygonF

from ..core.borehole_curves import CurveStyle, data_range, track_fraction
from .borehole_style import default_symbol

HIGHLIGHT_RGB = (230, 120, 0)
FLAG_RGB = (200, 0, 0)
OUTLINE_RGB = (0, 0, 0)
TRACK_FRAME_RGB = (150, 150, 150)
TEXT_RGB = (40, 40, 40)
TEXT_MM = 2.4
OUTLINE_MM = 0.15
TRACK_GAP_PX = 4.0
TEXT_GAP_PX = 4.0
TICK_PX = 4.0
TICK_MIN_SPACING_PX = 18.0
_DASH = {"solid": Qt.PenStyle.SolidLine, "dash": Qt.PenStyle.DashLine,
         "dot": Qt.PenStyle.DotLine, "dashdot": Qt.PenStyle.DashDotLine}
_MM = Qgis.RenderUnit.Millimeters


@dataclass
class ColumnOptions:
    width_px: float = 16
    opacity: float = 1.0
    layer_text: bool = False
    ticks: bool = False
    curve_keys: tuple = ()
    track_px: float = 40
    highlight: bool = False


def qcolor(text: str) -> QColor:
    """A colour from "#rrggbb" or "#rrggbbaa" (Qt itself reads 9 digits as #aarrggbb)."""
    if isinstance(text, str) and len(text) == 9 and text.startswith("#"):
        c = QColor(text[:7])
        c.setAlpha(int(text[7:], 16))
        return c
    return QColor(text)


def column_depth(p) -> float:
    """How deep the column reaches: the deepest interval or the total depth."""
    return max([iv.bottom for iv in p.log] + [p.total_depth or 0.0])


def draw_borehole(painter, rc, x_px: float, y_of_depth: Callable[[float], float], p,
                  opts: ColumnOptions, styles: dict, ranges: dict) -> QRectF:
    """Draw borehole ``p``; returns the drawn area (column, tracks, text) for hit tests."""
    w = float(opts.width_px)
    y0, y1 = y_of_depth(0.0), y_of_depth(column_depth(p))
    col = QRectF(QPointF(x_px - w / 2, min(y0, y1)), QPointF(x_px + w / 2, max(y0, y1)))
    area = QRectF(col)
    painter.save()
    try:
        painter.setOpacity(max(0.0, min(1.0, opts.opacity)))
        for iv in p.log:
            _interval(painter, rc, col, y_of_depth, iv)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(_pen(rc, OUTLINE_RGB, OUTLINE_MM))
        painter.drawRect(col)
        if opts.ticks:
            _ticks(painter, rc, col, y_of_depth, column_depth(p))
        right = col.right()
        for key in opts.curve_keys:
            track = QRectF(right + TRACK_GAP_PX, col.top(), float(opts.track_px), col.height())
            curve = next((c for c in p.curves if c.key == key), None)
            _track(painter, rc, track, y_of_depth, curve, styles.get(key) or CurveStyle(),
                   ranges.get(key))
            right = track.right()
            area = area.united(track)
        if opts.layer_text:
            area = area.united(_texts(painter, rc, right + TEXT_GAP_PX, y_of_depth, p))
    finally:
        painter.restore()
    if opts.highlight:
        painter.save()
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(*HIGHLIGHT_RGB), 2))
        painter.drawRect(col.adjusted(-1, -1, 1, 1))
        painter.restore()
    return area


def _pen(rc, rgb, width_mm: float) -> QPen:
    pen = QPen(QColor(*rgb), max(1.0, rc.convertToPainterUnits(width_mm, _MM)))
    pen.setCosmetic(True)
    return pen


def _interval(painter, rc, col: QRectF, y_of_depth, iv) -> None:
    ya, yb = y_of_depth(iv.top), y_of_depth(iv.bottom)
    poly = QPolygonF([QPointF(col.left(), ya), QPointF(col.right(), ya),
                      QPointF(col.right(), yb), QPointF(col.left(), yb),
                      QPointF(col.left(), ya)])
    sym = iv.symbol.clone() if iv.symbol is not None else default_symbol(iv.text)
    feature = iv.feature if iv.feature is not None else QgsFeature()
    rc.expressionContext().setFeature(feature)
    sym.startRender(rc, feature.fields())
    try:
        sym.renderPolygon(poly, None, feature, rc)
    finally:
        sym.stopRender(rc)


def _font(painter, rc) -> QFont:
    font = QFont(painter.font())
    font.setPixelSize(max(8, round(rc.convertToPainterUnits(TEXT_MM, _MM))))
    return font


def _ticks(painter, rc, col: QRectF, y_of_depth, depth: float) -> None:
    px_per_m = abs(y_of_depth(1.0) - y_of_depth(0.0)) or 1.0
    step = next((s for s in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100)
                 if s * px_per_m >= TICK_MIN_SPACING_PX), 100)
    painter.setPen(_pen(rc, OUTLINE_RGB, OUTLINE_MM))
    painter.setFont(_font(painter, rc))
    fm = painter.fontMetrics()
    for d in np.arange(0.0, depth + 1e-9, step):
        y = y_of_depth(float(d))
        painter.drawLine(QPointF(col.left() - TICK_PX, y), QPointF(col.left(), y))
        text = f"{d:g}"
        painter.drawText(QPointF(col.left() - TICK_PX - 2 - fm.horizontalAdvance(text),
                                 y + fm.ascent() / 2 - 1), text)


def _texts(painter, rc, x: float, y_of_depth, p) -> QRectF:
    painter.setFont(_font(painter, rc))
    painter.setPen(QPen(QColor(*TEXT_RGB)))
    fm = painter.fontMetrics()
    area = QRectF()
    for iv in p.log:
        if not iv.text:
            continue
        y = (y_of_depth(iv.top) + y_of_depth(iv.bottom)) / 2
        painter.drawText(QPointF(x, y + fm.ascent() / 2 - 1), iv.text)
        area = area.united(QRectF(x, y - fm.height() / 2, fm.horizontalAdvance(iv.text),
                                  fm.height()))
    return area


def curve_range(curve, style: CurveStyle, given) -> tuple[float, float] | None:
    """The track's scale: the style's own min/max, else ``given`` (the data range of the
    boreholes in view), else this curve's own data."""
    lo, hi = given if given is not None else (data_range([curve], style.log) if curve
                                              else None) or (None, None)
    lo = style.vmin if style.vmin is not None else lo
    hi = style.vmax if style.vmax is not None else hi
    return None if lo is None or hi is None else (float(lo), float(hi))


def _track(painter, rc, track: QRectF, y_of_depth, curve, style: CurveStyle, given) -> None:
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.setPen(_pen(rc, TRACK_FRAME_RGB, OUTLINE_MM))
    painter.drawRect(track)
    rng = curve_range(curve, style, given)
    if curve is None or rng is None or len(curve.depth) == 0:
        return
    f = track_fraction(curve.values, rng[0], rng[1], style.log)
    xs = track.left() + f * track.width()
    ys = np.array([y_of_depth(float(d)) for d in curve.depth])
    pen = QPen(qcolor(style.colour), max(1.0, rc.convertToPainterUnits(style.width_mm, _MM)))
    pen.setStyle(_DASH.get(style.dash, Qt.PenStyle.SolidLine))
    for run in _runs(np.isfinite(f)):
        pts = [QPointF(float(xs[i]), float(ys[i])) for i in run]
        if style.fill in ("left", "right") and len(pts) > 1:
            edge = track.left() if style.fill == "left" else track.right()
            poly = QPolygonF(pts + [QPointF(edge, pts[-1].y()), QPointF(edge, pts[0].y())])
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(qcolor(style.fill_colour)))
            painter.drawPolygon(poly)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        if len(pts) == 1:
            painter.drawPoint(pts[0])
        else:
            painter.drawPolyline(QPolygonF(pts))
    _header(painter, rc, track, curve, rng)


def _header(painter, rc, track: QRectF, curve, rng) -> None:
    painter.setFont(_font(painter, rc))
    painter.setPen(QPen(QColor(*TEXT_RGB)))
    fm = painter.fontMetrics()
    y = track.top() - 2
    painter.drawText(QPointF(track.left(), y - fm.height()), f"{curve.name} {curve.unit}".strip())
    lo, hi = f"{rng[0]:g}", f"{rng[1]:g}"
    painter.drawText(QPointF(track.left(), y), lo)
    painter.drawText(QPointF(track.right() - fm.horizontalAdvance(hi), y), hi)


def _runs(ok: np.ndarray) -> list[list[int]]:
    """Index runs of consecutive True values (a gap breaks the line)."""
    runs, cur = [], []
    for i, good in enumerate(ok):
        if good:
            cur.append(i)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs
