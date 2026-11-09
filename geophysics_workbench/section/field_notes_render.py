"""Field notes along the top of the section: a marker for a note at one chainage, a bar
for a stretch, each under its label (placed by ``context_render.plan_labels`` with the
crossing and borehole labels, so none overlap). Hover and click show the full text.
The look's constants live here (interim styling rule)."""
from __future__ import annotations

from qgis.PyQt.QtCore import QPointF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QPen, QPolygonF

from ..core.field_notes import note_range

NOTE_RGB = (176, 82, 0)
NOTE_BAR_PX = 3
LABEL_CHARS = 40


def label_text(text: str) -> str:
    """The first line, at most ``LABEL_CHARS`` characters ("…" when cut)."""
    first = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    return first if len(first) <= LABEL_CHARS else first[:LABEL_CHARS - 1] + "…"


def _position(note) -> str:
    lo, hi = note_range(note)
    where = f"{lo:.1f} m" if note.s_to is None else f"{lo:.1f}–{hi:.1f} m"
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

    from .context_render import surface_y
    notes = [n for n in items.field_notes if n.shown]
    if not notes or surface is None or len(surface[0]) < 1:
        return
    colour = QColor(*NOTE_RGB)
    painter.save()
    try:
        for n in notes:
            label = plan.get(id(n))
            if label is None:
                continue
            lo, hi = note_range(n)
            y = label.y + 2
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
            else:
                x0 = wt.map(QPointF(lo, 0.0)).x()
                x1 = wt.map(QPointF(hi, 0.0)).x()
                pen = QPen(colour, NOTE_BAR_PX)
                pen.setCapStyle(Qt.PenCapStyle.FlatCap)
                painter.setPen(pen)
                painter.drawLine(QPointF(min(x0, x1), y + 2), QPointF(max(x0, x1), y + 2))
                painter.setPen(QPen(colour, 1))
                for x in (x0, x1):
                    painter.drawLine(QPointF(x, y), QPointF(x, y + 7))
    finally:
        painter.restore()
