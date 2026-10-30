"""Draw third-party context on a section: geology band, DEM, crossings and profile ties.

Called from ``WorkbenchProfileResults._render`` (possibly on a worker thread) with a painter
in device space; ``wt`` maps (chainage, elevation) to device pixels. Sizes are millimetres
via ``rc.convertToPainterUnits``. Only plain snapshot data is used. Boreholes and points
live in ``context_render_points``."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from qgis.core import Qgis
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF

from ..core.lithology import lithology_colour

_MM = Qgis.RenderUnit.Millimeters
BAND_GAP = 1.5                          # mm between the station number labels and the band
BAND_THICKNESS = 3.0                    # mm
LABEL_ROWS = 3
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


def band_offsets(rc) -> tuple[float, float]:
    """Device offsets above the surface of the band's lower and upper edge: clear of the
    station triangles and their number labels (see ``WorkbenchProfileResults._draw_stations``)."""
    half = max(3.0, mm(rc, 1.0))
    number = max(10, round(mm(rc, 3.0)))
    near = 2 * half + 1.6 * number + mm(rc, BAND_GAP)
    return near, near + mm(rc, BAND_THICKNESS)


# -- geology band ------------------------------------------------------------------------------
def draw_band(painter, rc, wt, items, surface) -> None:
    if not items.band or surface is None or len(surface[0]) < 2:
        return
    near, far = band_offsets(rc)
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
def offset_text(offset: float) -> str:
    return f"({'+' if offset >= 0 else '−'}{abs(round(offset))} m)"


@dataclass
class Label:
    x: float
    y: float            # device y of the label's bottom edge
    text: str
    rgb: tuple


def plan_labels(painter, rc, wt, items, surface) -> dict:
    """Place every crossing, tie, borehole and point label in rows above the band, centred
    on its chainage; a label that would overlap one in its row goes one row higher (up to
    ``LABEL_ROWS``). Keyed by ``id()`` of the item."""
    if surface is None or len(surface[0]) < 1:
        return {}
    set_label_font(painter, rc)
    fm = painter.fontMetrics()
    _, far = band_offsets(rc)
    h = fm.height() + 1
    specs = []
    for c in items.crossings:
        if c.kind != "profile":                        # drawn as a tie
            power = c.kind == "powerline"
            specs.append((c, c.s, ("⚡ " if power else "") + c.label,
                          POWERLINE_COLOUR if power else LINE_COLOUR))
    specs += [(t, t.s, tie_label(t), TIE_COLOUR) for t in items.ties]
    for p in items.points:
        text = (f"{p.label} {offset_text(p.offset)}".strip()
                if p.kind == "borehole" and p.log else p.label)
        specs.append((p, p.s, text, (0, 0, 0)))
    rows: list[list[tuple[float, float]]] = [[] for _ in range(LABEL_ROWS)]
    out = {}
    for item, s, text, rgb in specs:
        if not text:
            continue
        x = wt.map(QPointF(s, float(np.interp(s, *surface)))).x()
        half_w = (fm.horizontalAdvance(text) + 4) / 2
        row = next((r for r in range(LABEL_ROWS)
                    if all(x + half_w + 2 <= a or x - half_w - 2 >= b for a, b in rows[r])),
                   LABEL_ROWS - 1)
        rows[row].append((x - half_w, x + half_w))
        y = surface_y(wt, surface, s) - far - mm(rc, 1.0) - row * h
        out[id(item)] = Label(x, y, text, rgb)
    return out


def _vertical(painter, wt, s: float, z_range, label) -> None:
    """Dashed line from the bottom of the z range up to its label (or the top of the range)."""
    bottom = wt.map(QPointF(s, z_range[0]))
    top = QPointF(label.x, label.y) if label else wt.map(QPointF(s, z_range[1]))
    painter.drawLine(QPointF(top.x(), top.y()), bottom)


def draw_crossings(painter, rc, wt, items, z_range, plan=None) -> None:
    if not items.crossings or not z_range[0] < z_range[1]:
        return
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for c in items.crossings:
        if c.kind == "profile":
            continue
        power = c.kind == "powerline"
        painter.setPen(line_pen(rc, POWERLINE_COLOUR if power else LINE_COLOUR,
                                0.6 if power else 0.3, dashed=True))
        _vertical(painter, wt, c.s, z_range, (plan or {}).get(id(c)))


def tie_strip_column(tie):
    """The one column drawn beside a tie line: the first, if it has a scale and values."""
    col = tie.columns[0] if tie.columns else None
    if col is None or col.scale is None or not np.isfinite(np.asarray(col.values, float)).any():
        return None
    return col


def tie_label(tie) -> str:
    return tie.other_name + (f" · {round(tie.distance)} m" if tie.distance >= 0.5 else "")


def draw_ties(painter, rc, wt, items, z_range, plan=None) -> None:
    if not items.ties or not z_range[0] < z_range[1]:
        return
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    for tie in items.ties:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(line_pen(rc, TIE_COLOUR, 0.3, dashed=True))
        _vertical(painter, wt, tie.s, z_range, (plan or {}).get(id(tie)))
        x = wt.map(QPointF(tie.s, z_range[1])).x()
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


def draw_labels(painter, rc, items, plan: dict) -> None:
    """All labels last, so no column, strip or line overdraws one."""
    set_label_font(painter, rc)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    for lab in plan.values():
        draw_label(painter, lab.text, lab.x, lab.y, lab.rgb)


def draw_over_stations(painter, rc, wt, items, stations, station_z, surface, z_range) -> None:
    """Everything drawn after the stations: DEM, crossings, boreholes, ties, then labels."""
    from .context_render_points import draw_points

    plan = plan_labels(painter, rc, wt, items, surface)
    draw_dem(painter, rc, wt, items, stations, station_z)
    draw_crossings(painter, rc, wt, items, z_range, plan)
    draw_points(painter, rc, wt, items, surface)
    draw_ties(painter, rc, wt, items, z_range, plan)
    draw_labels(painter, rc, items, plan)
