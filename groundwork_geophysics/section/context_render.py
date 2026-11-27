"""Draw third-party context on a section: geology band, DEM, crossings and profile ties.

Called from ``WorkbenchProfileResults._render`` (possibly on a worker thread) with a painter
in device space; ``wt`` maps (chainage, elevation) to device pixels. Sizes are millimetres
via ``rc.convertToPainterUnits``. Only plain snapshot data is used. Boreholes and points
live in ``context_render_points``."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from qgis.core import Qgis
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF

from ..core.context import DEFAULT_LINE_RGB, strips_of
from ..core.dataset_types import READINGS_KINDS  # readings: never a tie strip's scale
from ..core.lithology import label_colour
from ..core.ties import strip_column

_MM = Qgis.RenderUnit.Millimeters
BAND_GAP = 1.5                          # mm between the station number labels and the band
BAND_THICKNESS = 3.0                    # mm
STRIP_GAP = 0.6                         # mm between stacked strips
LABEL_ROWS = 3
BAND_OPACITY = 0.85
DEM_COLOUR = (140, 90, 40)
FLAG_COLOUR = (220, 30, 30)             # station whose height disagrees with the DEM
LINE_COLOUR = DEFAULT_LINE_RGB
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


def label_font_px(px_per_mm: float, size_mm: float = 2.6) -> int:
    return max(9, round(px_per_mm * size_mm))


def set_label_font(painter, rc, size_mm: float = 2.6) -> QFont:
    font = QFont(painter.font())
    font.setPixelSize(label_font_px(mm(rc, 1.0), size_mm))
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


def band_offsets(rc, level: int = 0) -> tuple[float, float]:
    """Device offsets above the surface of a strip's lower and upper edge: clear of the
    station triangles and their number labels (see ``WorkbenchProfileResults._draw_stations``).
    Level 0 is the strip nearest the ground."""
    return band_offsets_px(mm(rc, 1.0), level)


def band_offsets_px(px_per_mm: float, level: int = 0) -> tuple[float, float]:
    """``band_offsets`` for ``px_per_mm`` device pixels per millimetre."""
    half = max(3.0, px_per_mm)
    number = max(10, round(px_per_mm * 3.0))
    near = 2 * half + 1.6 * number + px_per_mm * BAND_GAP + level * px_per_mm * (
        BAND_THICKNESS + STRIP_GAP)
    return near, near + px_per_mm * BAND_THICKNESS


def top_level(items) -> int:
    """Level of the highest strip drawn for ``items`` (0 for none or one): labels sit above it."""
    return max(0, len(strips_of(items.band)) - 1)


def context_headroom_px(px_per_mm: float, line_height: float, labels: bool = True,
                        strips: int = 1) -> float:
    """Device pixels ``strips`` stacked strips and, with ``labels``, ``LABEL_ROWS`` rows of
    labels need above the surface, as ``plan_labels`` places them; ``line_height`` is the
    label font's height (``fontMetrics().height()``). The section panel fits its view with it."""
    _, far = band_offsets_px(px_per_mm, max(1, strips) - 1)
    return far + px_per_mm * 1.0 + (LABEL_ROWS * (line_height + 1) if labels else 0.0)


# -- geology strips ----------------------------------------------------------------------------
TITLE_MIN_UNIT_PX = 6.0     # of a unit that must remain beside a strip's title


def draw_band(painter, rc, wt, items, surface) -> None:
    if not items.band or surface is None or len(surface[0]) < 2:
        return
    font = set_label_font(painter, rc, 2.4)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    ss = np.asarray(surface[0], float)
    strips = strips_of(items.band)
    # the visible plot in the device space wt.map returns (the panel and plates clip to it)
    clip = painter.clipBoundingRect() if painter.hasClipping() else QRectF()
    left = clip.left() if not clip.isEmpty() else -math.inf
    right = clip.right() if not clip.isEmpty() else math.inf
    inv, _ok = wt.inverted()
    px = font.pixelSize()
    flags = int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    for k, (title, segs) in enumerate(strips):
        near, far = band_offsets(rc, len(strips) - 1 - k)
        mid = 0.5 * (near + far)
        title_seg = title_end = None        # the unit the title sits in; its right edge (px)
        for i, seg in enumerate(segs):
            inner = ss[(ss > seg.s0) & (ss < seg.s1)]
            xs = np.r_[seg.s0, inner, seg.s1]
            pts = [wt.map(QPointF(float(x), float(np.interp(x, *surface)))) for x in xs]
            poly = QPolygonF([QPointF(p.x(), p.y() - near) for p in pts]
                             + [QPointF(p.x(), p.y() - far) for p in reversed(pts)])
            r, g, b = seg.rgb or label_colour(seg.label)
            painter.setBrush(QBrush(QColor(r, g, b, round(255 * BAND_OPACITY))))
            painter.setPen(line_pen(rc, (60, 60, 60), 0.15))
            painter.drawPolygon(poly)
            x0, x1 = pts[0].x(), pts[-1].x()
            width = abs(x1 - x0)
            xm = 0.5 * (x0 + x1)
            lo, hi = max(min(x0, x1), left), min(max(x0, x1), right)    # the visible part
            fm = painter.fontMetrics()
            if title and title_seg is None and hi > lo:     # the first visible unit with room
                need = fm.horizontalAdvance(title) + 4
                if need + TITLE_MIN_UNIT_PX <= hi - lo:
                    tx = lo + 2
                    s_t = inv.map(QPointF(tx + need / 2, 0.0)).x()      # chainage under it
                    ty = surface_y(wt, surface, s_t) - mid
                    painter.setPen(QPen(QColor(0, 0, 0), 1))
                    painter.drawText(QRectF(tx, ty - px, need, 2 * px), flags, title)
                    title_seg, title_end = i, tx + need
            if not seg.label:
                continue
            lw = fm.horizontalAdvance(seg.label) + 4
            if i == title_seg:                  # beside the title, in what is left of the unit
                if lw > hi - title_end:
                    continue
                cx = 0.5 * (title_end + hi)
                cw = hi - title_end
            elif lw <= width:                   # centred on the whole unit, as before
                cx, cw = xm, width
            else:
                continue
            cy = surface_y(wt, surface, inv.map(QPointF(cx, 0.0)).x()) - mid
            painter.setPen(QPen(QColor(0, 0, 0), 1))
            painter.drawText(QRectF(cx - cw / 2, cy - px, cw, 2 * px),
                             int(Qt.AlignmentFlag.AlignCenter), seg.label)


# -- DEM line and flagged stations ---------------------------------------------------------------
def draw_dem(painter, rc, wt, items, stations, heights) -> None:
    """Dashed DEM line, and a red triangle on each station whose measured height
    (``heights``, aligned with ``stations``; nan = none) is off the DEM by more than the
    tolerance, drawn at that measured height in either topography mode."""
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
    if not stations or heights is None:
        return
    s = np.array([st[0] for st in stations], float)
    with np.errstate(invalid="ignore"):
        flagged = np.abs(np.asarray(heights, float) - dem_at(items.dem, s)) > items.dem_tolerance
    half = max(3.0, mm(rc, 1.0))
    painter.setPen(QPen(QColor(*FLAG_COLOUR), 1))
    painter.setBrush(QBrush(QColor(*FLAG_COLOUR)))
    for si, zi in zip(s[flagged], np.asarray(heights, float)[flagged]):    # nan compares False
        p = wt.map(QPointF(float(si), float(zi)))
        x, y = p.x(), p.y()
        painter.drawPolygon(QPolygonF([QPointF(x, y), QPointF(x - half, y - 2 * half),
                                       QPointF(x + half, y - 2 * half)]))


# -- crossings and ties ------------------------------------------------------------------------
def offset_text(offset: float) -> str:
    """Side and distance of a borehole off the line, e.g. "(+2 m)", "(0 m)", never "−0"."""
    from ..core.numbers import fmt
    return f"({fmt(offset, 0, sign=True)} m)"


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
    _, far = band_offsets(rc, top_level(items))
    h = fm.height() + 1
    specs = []
    for c in items.crossings:
        if c.kind != "profile":                        # drawn as a tie
            specs.append((c, c.s, c.label, c.rgb))
    specs += [(t, t.s, tie_label(t), TIE_COLOUR) for t in items.ties]
    for p in items.points:
        text = (f"{p.label} {offset_text(p.offset)}".strip()
                if p.kind == "borehole" and p.log else p.label)
        specs.append((p, p.s, text, (0, 0, 0)))
    from ..core.field_notes import note_range
    from .field_notes_render import DEFAULT_LOOK, label_text
    looks = getattr(items, "note_looks", {}) or {}
    for n in items.field_notes:
        if n.shown:
            lo, hi = note_range(n)
            rgb = looks.get(n.id, DEFAULT_LOOK).rgb          # the note's layer colour
            specs.append((n, (lo + hi) / 2, label_text(n.text), rgb))
    from .field_notes_render import lanes_px
    lanes = lanes_px(mm(rc, 1.0), items.field_notes)        # stretch lanes under the labels
    specs = [sp for sp in specs if sp[2]]
    spans, xs = [], []
    for item, s, text, _rgb in specs:
        x = wt.map(QPointF(s, float(np.interp(s, *surface)))).x()
        half_w = (fm.horizontalAdvance(text) + 4) / 2 + 2
        spans.append((x - half_w, x + half_w, _label_priority(item)))
        xs.append(x)
    out = {}
    # the visible plot's top (the panel and plates clip to it): a label above it is left
    # out rather than cut off
    top = painter.clipBoundingRect().top() if painter.hasClipping() else None
    # rows follow the ground under each label, so over a dip two different rows can meet:
    # every candidate row is checked against the rectangles already placed
    placed: list[tuple[float, float, float, float]] = []
    order = sorted(range(len(specs)), key=lambda i: (spans[i][2], spans[i][0]))
    for i in order:
        item, s, text, rgb = specs[i]
        x0, x1 = spans[i][0], spans[i][1]
        base = surface_y(wt, surface, s) - far - mm(rc, 1.0) - lanes
        for row in range(LABEL_ROWS):
            y = base - row * h
            if top is not None and y - h < top:
                break                                   # higher rows are further out of view
            if all(x1 <= a0 or x0 >= a1 or y <= b0 or y - h >= b1
                   for a0, b0, a1, b1 in placed):
                placed.append((x0, y - h, x1, y))
                out[id(item)] = Label(xs[i], y, text, rgb)
                break                                   # no room in any row: left out
    return out


def _label_priority(item) -> int:
    """Which labels get a row first: field notes, ties, crossings, boreholes, points."""
    from ..core.context import Crossing, ProjectedPoint
    from ..core.field_notes import FieldNote
    from ..core.ties import Tie
    if isinstance(item, FieldNote):
        return 0
    if isinstance(item, Tie):
        return 1
    if isinstance(item, Crossing):
        return 2
    if isinstance(item, ProjectedPoint):
        return 3 if item.kind == "borehole" else 4
    return 5


def place_labels(spans, rows: int) -> list:
    """Row (0 = lowest) of each ``(x0, x1, priority)`` span, or None when no row has room.
    Lower priority numbers are placed first; within a priority, left to right."""
    taken: list[list[tuple[float, float]]] = [[] for _ in range(rows)]
    out: list = [None] * len(spans)
    for i in sorted(range(len(spans)), key=lambda i: (spans[i][2], spans[i][0])):
        x0, x1, _p = spans[i]
        row = next((r for r in range(rows)
                    if all(x1 <= a or x0 >= b for a, b in taken[r])), None)
        if row is not None:
            taken[row].append((x0, x1))
            out[i] = row
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
        painter.setPen(line_pen(rc, c.rgb, 0.4, dashed=True))
        _vertical(painter, wt, c.s, z_range, (plan or {}).get(id(c)))


def tie_strip_column(tie):
    """The one column drawn beside a tie line (``core.ties.strip_column``)."""
    return strip_column(tie)




def strip_scale(col, host_layers):
    """The scale a tie strip is drawn with: that of the viewed profile's topmost model of
    the column's quantity (visible ones first), so equal values look equal across the tie
    (finding F2) and the strip looks the same whichever layers are switched on (measured
    data never lends its scale); the column's own scale when the profile has no model."""
    models = [la for la in (host_layers or ())
              if la.mesh is not None and la.style.scale is not None
              and la.dataset.kind not in READINGS_KINDS
              and la.dataset.quantity == col.quantity]
    if not models:
        return col.scale
    # stable sort: visible after hidden, each in drawing order (last is on top)
    return sorted(models, key=lambda la: bool(la.style.visible))[-1].style.scale


def tie_label(tie) -> str:
    """The other profile's name; with the gap of a near miss ("R2 · 8 m"), or the shared
    stretch of profiles running along each other ("R2 · along 165–260 m")."""
    stretch = getattr(tie, "stretch", None)
    if stretch is not None:
        return f"{tie.other_name} · along {round(stretch[0])}–{round(stretch[1])} m"
    return tie.other_name + (f" · {round(tie.distance)} m" if tie.distance >= 0.5 else "")


def draw_ties(painter, rc, wt, items, z_range, plan=None, host_layers=()) -> None:
    """Dashed tie lines, each with a strip of the other profile's column just right of
    the line, or in the nearest free slot beside a borehole column (``strip_start``)."""
    from .context_readout import strip_start
    from .context_render_points import column_px, right_extent_px

    if not items.ties or not z_range[0] < z_range[1]:
        return
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    width = mm(rc, TIE_STRIP_WIDTH)
    px_per_m = abs(wt.map(QPointF(1.0, 0.0)).x() - wt.map(QPointF(0.0, 0.0)).x()) or 1.0
    for tie in items.ties:
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(line_pen(rc, TIE_COLOUR, 0.3, dashed=True))
        _vertical(painter, wt, tie.s, z_range, (plan or {}).get(id(tie)))
        col = tie_strip_column(tie)
        if col is None:
            continue
        start = strip_start(items.points, tie.s, width / px_per_m,
                            lambda q: column_px(rc, items, q) / 2 / px_per_m,
                            lambda q: right_extent_px(items, q) / px_per_m)
        x = wt.map(QPointF(start, z_range[1])).x()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setPen(Qt.PenStyle.NoPen)
        rgba_all = strip_scale(col, host_layers).rgba(col.values)
        ys = []
        for z_top, z_bot, rgba in zip(col.z_top, col.z_bottom, rgba_all):
            if rgba[3] == 0:
                continue
            y0 = wt.map(QPointF(tie.s, float(z_top))).y()
            y1 = wt.map(QPointF(tie.s, float(z_bot))).y()
            painter.setBrush(QBrush(QColor(*(int(c) for c in rgba))))
            painter.drawRect(QRectF(QPointF(x, min(y0, y1)), QPointF(x + width, max(y0, y1))))
            ys += [y0, y1]
        if ys:              # in the host's scale the strip matches the section: frame it
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(line_pen(rc, TIE_COLOUR, 0.2))
            painter.drawRect(QRectF(QPointF(x, min(ys)), QPointF(x + width, max(ys))))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)


def context_z_values(items, topo) -> list[float]:
    """Elevations the context ``items`` need on the z axis: borehole log bottoms and the
    drawn tie columns; ``topo`` is the surface a borehole without its own top hangs from.
    Used by the generator's ``zRange`` and the section panel's "Zoom Full"."""
    if items is None:
        return []
    out: list[float] = []
    from ..core.context import collar_height
    from .borehole_draw import column_depth
    for p in items.points:
        depth = column_depth(p) if p.kind == "borehole" else 0.0
        if depth <= 0:
            continue
        surface = float(np.interp(p.s, *topo)) if topo is not None and len(topo[0]) else None
        top = collar_height(p.z_top, None, surface)[0]
        if top is not None:
            out.append(top - depth)
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


def draw_over_stations(painter, rc, wt, items, stations, heights, surface, z_range,
                       host_layers=()) -> None:
    """Everything drawn after the stations: DEM, crossings, boreholes, ties, then labels.
    ``heights`` are the measured station heights; ``host_layers`` the viewed profile's
    snapshot layers (tie strips use their scale)."""
    from .context_render_points import draw_points

    plan = plan_labels(painter, rc, wt, items, surface)
    draw_dem(painter, rc, wt, items, stations, heights)
    draw_crossings(painter, rc, wt, items, z_range, plan)
    draw_points(painter, rc, wt, items, surface)
    draw_ties(painter, rc, wt, items, z_range, plan, host_layers)
    from .field_notes_render import draw_field_notes
    draw_field_notes(painter, rc, wt, items, surface, plan)
    draw_labels(painter, rc, items, plan)
