"""Field notes along the top of the section: a marker for a note at one chainage, a bar
for a stretch, each under its label (placed by ``context_render.plan_labels`` with the
crossing and borehole labels, so none overlap). Hover and click show the full text.
The look's constants live here (interim styling rule)."""
from __future__ import annotations

from dataclasses import dataclass

from qgis.PyQt.QtCore import QPointF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QPen, QPolygonF

from ..core.field_notes import note_range
from ..core.numbers import fmt

NOTE_RGB = (176, 82, 0)
NOTE_BAR_PX = 3
LANE_MM = 1.0                   # one lane of stretch bars above the band
LABEL_CHARS = 40
STRETCH_MM = 0.5                # a stretch bar's width when its style gives none


@dataclass(frozen=True)
class NoteLook:
    """A note's look from its QGIS layer style: colour, and a stretch's line width (mm)."""
    rgb: tuple[int, int, int]
    width_mm: float | None = None


DEFAULT_LOOK = NoteLook(NOTE_RGB)


def note_looks(store, project) -> dict:
    """note id -> ``NoteLook`` from the "Field notes" (points) and "Field notes (stretches)"
    layers' renderers, per feature, so categorized or rule-based styles work per note
    (main thread only). Notes without a layer get ``DEFAULT_LOOK`` from the caller."""
    from qgis.core import Qgis, QgsLineSymbol, QgsRenderContext

    from ..ui.field_note_layers import field_note_layers
    out = {}
    layers = field_note_layers(store, project)
    # points first: the points layer also holds a stretch's midpoint, and a stretch takes
    # its look from the stretches layer
    for layer in (layers.get("field_notes_points"), layers.get("field_notes_lines")):
        if layer is None or layer.renderer() is None:
            continue
        renderer = layer.renderer().clone()
        rc = QgsRenderContext()
        renderer.startRender(rc, layer.fields())
        try:
            for feature in layer.getFeatures():
                symbols = renderer.symbolsForFeature(feature, rc)
                if not symbols:
                    continue
                sym, c = symbols[0], symbols[0].color()
                width = sym.width() if isinstance(sym, QgsLineSymbol) and \
                    sym.outputUnit() == Qgis.RenderUnit.Millimeters else None
                out[feature["note_id"]] = NoteLook((c.red(), c.green(), c.blue()), width)
        finally:
            renderer.stopRender(rc)
    return out


def label_text(text: str) -> str:
    """The first line, at most ``LABEL_CHARS`` characters ("…" when cut)."""
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return first if len(first) <= LABEL_CHARS else first[:LABEL_CHARS - 1] + "…"


def _position(note) -> str:
    lo, hi = note_range(note)
    where = f"{fmt(lo, 1)} m" if note.s_to is None else f"{fmt(lo, 1)}–{fmt(hi, 1)} m"
    return where + (f" (electrodes {note.stations})" if note.stations else "")


def field_note_lines(notes, s: float, tol_s: float) -> list[str]:
    """Readout lines for the shown notes at chainage ``s`` (within ``tol_s``)."""
    out = []
    for n in notes:
        lo, hi = note_range(n)
        if n.shown and lo - tol_s <= s <= hi + tol_s:
            text = " / ".join(line.strip() for line in (n.text or "").splitlines() if line.strip())
            out.append(f"Field note {_position(n)}: {text}")
    return out


def draw_field_notes(painter, rc, wt, items, surface, plan: dict) -> None:
    """Markers and stretch bars just under each note's label; down to the ground for a note
    at one chainage."""
    import numpy as np

    from .context_render import band_offsets, mm, surface_y, top_level
    notes = [n for n in items.field_notes if n.shown]
    if not notes or surface is None or len(surface[0]) < 1:
        return
    looks = getattr(items, "note_looks", {}) or {}
    _, far = band_offsets(rc, top_level(items))
    lanes = stretch_lanes(notes)
    painter.save()
    try:
        for n in notes:
            label = plan.get(id(n))
            if label is None:
                continue
            lo, hi = note_range(n)
            y = label.y + 2
            look = looks.get(n.id, DEFAULT_LOOK)
            colour = QColor(*look.rgb)
            if n.s_to is None:
                x = wt.map(QPointF(lo, float(np.interp(lo, *surface)))).x()
                ground = surface_y(wt, surface, lo)
                pen = QPen(colour, 1, Qt.PenStyle.DashLine)
                painter.setPen(pen)
                painter.drawLine(QPointF(x, y + 5), QPointF(x, ground))
                painter.setPen(QPen(colour, 1))
                painter.setBrush(QBrush(colour))
                painter.drawPolygon(QPolygonF([QPointF(x - 4, y), QPointF(x + 4, y),
                                               QPointF(x, y + 6)]))
            else:                               # a stretch: its lane along the ground
                x0 = wt.map(QPointF(lo, 0.0)).x()
                x1 = wt.map(QPointF(hi, 0.0)).x()
                off = far + mm(rc, 0.5) + lanes.get(n.id, 0) * mm(rc, LANE_MM)
                ss = np.linspace(lo, hi, 2 + int(abs(x1 - x0) / 4))
                ys = _smooth(np.array([surface_y(wt, surface, s) for s in ss]))
                pts = [QPointF(wt.map(QPointF(s, 0.0)).x(), y_s - off)
                       for s, y_s in zip(ss, ys)]
                pen = QPen(colour, max(2.0, mm(rc, look.width_mm or STRETCH_MM)))
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolyline(QPolygonF(pts))
                painter.setPen(QPen(colour, 1))
                for p in (pts[0], pts[-1]):
                    painter.drawLine(QPointF(p.x(), p.y() - 3), QPointF(p.x(), p.y() + 3))
                mid = surface_y(wt, surface, (lo + hi) / 2) - off
                painter.setPen(QPen(colour, 1, Qt.PenStyle.DotLine))
                painter.drawLine(QPointF(label.x, y), QPointF(label.x, mid))
    finally:
        painter.restore()


def _smooth(ys, window_px: float = 60.0):
    """The ground under a stretch, smoothed over about ``window_px`` (samples every ~4 px)
    and never below the highest nearby ground, so the lane runs calmly above the stations."""
    import numpy as np
    n = max(1, min(len(ys), int(window_px / 4)) | 1)
    if n == 1:
        return ys
    padded = np.pad(ys, n // 2, mode="edge")
    top = np.array([padded[i:i + n].min() for i in range(len(ys))])   # device y: min = highest
    return np.convolve(np.pad(top, n // 2, mode="edge"), np.ones(n) / n, mode="valid")


def stretch_lanes(notes) -> dict:
    """Lane (0 = nearest the ground) of every shown stretch, by note id: a stretch takes the
    lowest lane free over its whole range."""
    out, ends = {}, []
    stretches = sorted((n for n in notes if n.shown and n.s_to is not None), key=note_range)
    for n in stretches:
        lo, hi = note_range(n)
        lane = next((i for i, end in enumerate(ends) if end < lo), len(ends))
        if lane == len(ends):
            ends.append(hi)
        else:
            ends[lane] = hi
        out[n.id] = lane
    return out


def lanes_px(px_per_mm: float, notes) -> float:
    """Height the stretch lanes need between the band and the label rows."""
    lanes = stretch_lanes(notes)
    return (max(lanes.values()) + 1) * px_per_mm * LANE_MM if lanes else 0.0
