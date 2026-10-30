"""Draw third-party context on a section: geology band, DEM, crossings and profile ties.

Called from ``WorkbenchProfileResults._render`` (possibly on a worker thread) with a painter
in device space; ``wt`` maps (chainage, elevation) to device pixels. Sizes are millimetres
via ``rc.convertToPainterUnits``. Only plain snapshot data is used. Boreholes and points
live in ``context_render_points``."""
from __future__ import annotations

import numpy as np
from qgis.core import Qgis
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF

from ..core.lithology import lithology_colour

_MM = Qgis.RenderUnit.Millimeters
BAND_NEAR, BAND_FAR = 1.5, 4.5          # mm above the surface
BAND_OPACITY = 0.85
DEM_COLOUR = (140, 90, 40)
FLAG_COLOUR = (220, 30, 30)             # station whose height disagrees with the DEM
POWERLINE_COLOUR = (255, 120, 0)
LINE_COLOUR = (90, 90, 90)
TIE_COLOUR = (30, 60, 160)
TIE_STRIP_WIDTH = 3.0                   # mm


def mm(rc, value: float) -> float:
    return rc.convertToPainterUnits(value, _MM)


def line_pen(rc, rgb, width_mm: float, dashed: bool = False) -> QPen:
    pen = QPen(QColor(*rgb), max(1.0, mm(rc, width_mm)))
    pen.setCosmetic(True)
    if dashed:
        pen.setStyle(Qt.PenStyle.DashLine)
    return pen


def set_label_font(painter, rc, size_mm: float = 2.6) -> QFont:
    font = QFont(painter.font())
    font.setPixelSize(max(9, round(mm(rc, size_mm))))
    painter.setFont(font)
    return font


def draw_label(painter, text: str, x: float, y_bottom: float, rgb=(0, 0, 0)) -> None:
    """Text centred on ``x`` with its bottom edge at ``y_bottom``, on a pale backing."""
    fm = painter.fontMetrics()
    w, h = fm.horizontalAdvance(text) + 4, fm.height()
    box = QRectF(x - w / 2, y_bottom - h, w, h)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(255, 255, 255, 170)))
    painter.drawRect(box)
    painter.setPen(QPen(QColor(*rgb), 1))
    painter.drawText(box, int(Qt.AlignmentFlag.AlignCenter), text)


def surface_y(wt, surface, s: float) -> float:
    """Device y of the drawn surface at chainage ``s``."""
    return wt.map(QPointF(s, float(np.interp(s, *surface)))).y()


def dem_at(dem, s) -> np.ndarray:
    """DEM elevation at chainages ``s``; nan outside the DEM or next to a gap."""
    ds, dz = (np.asarray(a, float) for a in dem)
    s = np.atleast_1d(np.asarray(s, float))
    if len(ds) < 2:
        return np.full(s.shape, np.nan)
    i = np.clip(np.searchsorted(ds, s, side="right") - 1, 0, len(ds) - 2)
    span = ds[i + 1] - ds[i]
    with np.errstate(invalid="ignore", divide="ignore"):
        t = np.where(span > 0, (s - ds[i]) / span, 0.0)
    out = np.where(t <= 0, dz[i], np.where(t >= 1, dz[i + 1], dz[i] + t * (dz[i + 1] - dz[i])))
    return np.where((s < ds[0]) | (s > ds[-1]), np.nan, out)


# -- geology band ------------------------------------------------------------------------------
def draw_band(painter, rc, wt, items, surface) -> None:
    if not items.band or surface is None or len(surface[0]) < 2:
        return
    near, far = mm(rc, BAND_NEAR), mm(rc, BAND_FAR)
    font = set_label_font(painter, rc, 2.4)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    ss = np.asarray(surface[0], float)
    for seg in items.band:
        inner = ss[(ss > seg.s0) & (ss < seg.s1)]
        xs = np.r_[seg.s0, inner, seg.s1]
        pts = [wt.map(QPointF(float(x), float(np.interp(x, *surface)))) for x in xs]
        poly = QPolygonF([QPointF(p.x(), p.y() - near) for p in pts]
                         + [QPointF(p.x(), p.y() - far) for p in reversed(pts)])
        r, g, b = lithology_colour(seg.label)
        painter.setBrush(QBrush(QColor(r, g, b, round(255 * BAND_OPACITY))))
        painter.setPen(line_pen(rc, (60, 60, 60), 0.15))
        painter.drawPolygon(poly)
        x0, x1 = pts[0].x(), pts[-1].x()
        if seg.label and painter.fontMetrics().horizontalAdvance(seg.label) + 4 <= abs(x1 - x0):
            xm = 0.5 * (x0 + x1)
            ym = surface_y(wt, surface, 0.5 * (seg.s0 + seg.s1)) - 0.5 * (near + far)
            painter.setPen(QPen(QColor(0, 0, 0), 1))
            painter.drawText(QRectF(xm - abs(x1 - x0) / 2, ym - font.pixelSize(),
                                    abs(x1 - x0), 2 * font.pixelSize()),
                             int(Qt.AlignmentFlag.AlignCenter), seg.label)


# -- DEM line and flagged stations ---------------------------------------------------------------
def draw_dem(painter, rc, wt, items, stations, station_z) -> None:
    if items.dem is None:
        return
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    ds, dz = (np.asarray(a, float) for a in items.dem)
    finite = np.isfinite(dz) & np.isfinite(ds)
    painter.setPen(line_pen(rc, DEM_COLOUR, 0.3, dashed=True))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    edges = np.flatnonzero(np.diff(np.r_[False, finite, False].astype(int)))
    for a, b in zip(edges[::2], edges[1::2]):          # runs of finite values, never bridged
        if b - a >= 2:
            painter.drawPolyline(QPolygonF([wt.map(QPointF(float(ds[k]), float(dz[k])))
                                            for k in range(a, b)]))
    if not stations or station_z is None:
        return
    s = np.array([st[0] for st in stations], float)
    with np.errstate(invalid="ignore"):
        flagged = np.abs(np.asarray(station_z, float) - dem_at(items.dem, s)) > items.dem_tolerance
    half = max(3.0, mm(rc, 1.0))
    painter.setPen(QPen(QColor(*FLAG_COLOUR), 1))
    painter.setBrush(QBrush(QColor(*FLAG_COLOUR)))
    for si, zi in zip(s[flagged], np.asarray(station_z, float)[flagged]):    # nan compares False
        p = wt.map(QPointF(float(si), float(zi)))
        x, y = p.x(), p.y()
        painter.drawPolygon(QPolygonF([QPointF(x, y), QPointF(x - half, y - 2 * half),
                                       QPointF(x + half, y - 2 * half)]))


# -- crossings and ties ------------------------------------------------------------------------
def _vertical(painter, wt, s: float, z_range, label: str, rgb) -> float:
    """Dashed line over the whole z range with its label at the top; returns device x."""
    top, bottom = wt.map(QPointF(s, z_range[1])), wt.map(QPointF(s, z_range[0]))
    painter.drawLine(top, bottom)
    if label:
        fm = painter.fontMetrics()
        draw_label(painter, label, top.x(), top.y() + fm.height() + 2, rgb)
    return top.x()


def draw_crossings(painter, rc, wt, items, z_range) -> None:
    if not items.crossings or not z_range[0] < z_range[1]:
        return
    set_label_font(painter, rc)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for c in items.crossings:
        if c.kind == "profile":                        # drawn as a tie
            continue
        power = c.kind == "powerline"
        rgb = POWERLINE_COLOUR if power else LINE_COLOUR
        painter.setPen(line_pen(rc, rgb, 0.6 if power else 0.3, dashed=True))
        _vertical(painter, wt, c.s, z_range, ("⚡ " if power else "") + c.label, rgb)


def tie_strip_column(tie):
    """The one column drawn beside a tie line: the first, if it has a scale and values."""
    col = tie.columns[0] if tie.columns else None
    if col is None or col.scale is None or not np.isfinite(np.asarray(col.values, float)).any():
        return None
    return col


def tie_label(tie) -> str:
    return tie.other_name + (f" · {round(tie.distance)} m" if tie.distance >= 0.5 else "")


def draw_ties(painter, rc, wt, items, z_range) -> None:
    if not items.ties or not z_range[0] < z_range[1]:
        return
    set_label_font(painter, rc)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    for tie in items.ties:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(line_pen(rc, TIE_COLOUR, 0.3, dashed=True))
        x = _vertical(painter, wt, tie.s, z_range, tie_label(tie), TIE_COLOUR)
        col = tie_strip_column(tie)
        if col is None:
            continue
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        for z_top, z_bot, rgba in zip(col.z_top, col.z_bottom, col.scale.rgba(col.values)):
            if rgba[3] == 0:
                continue
            y0 = wt.map(QPointF(tie.s, float(z_top))).y()
            y1 = wt.map(QPointF(tie.s, float(z_bot))).y()
            painter.setBrush(QBrush(QColor(*(int(c) for c in rgba))))
            painter.drawRect(QRectF(QPointF(x, min(y0, y1)),
                                    QPointF(x + mm(rc, TIE_STRIP_WIDTH), max(y0, y1))))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)


def context_z_values(snapshot) -> list[float]:
    """Elevations the context needs on the z axis: borehole log bottoms and tie columns."""
    items = snapshot.context
    if items is None:
        return []
    out: list[float] = []
    topo = snapshot.topo
    for p in items.points:
        if not p.log:
            continue
        top = p.z_top
        if top is None and topo is not None and len(topo[0]):
            top = float(np.interp(p.s, *topo))
        if top is not None:
            out.append(top - max(iv.bottom for iv in p.log))
    for tie in items.ties:
        col = tie_strip_column(tie)
        if col is not None and len(col.z_top):
            out.extend((float(np.max(col.z_top)), float(np.min(col.z_bottom))))
    return [v for v in out if np.isfinite(v)]
