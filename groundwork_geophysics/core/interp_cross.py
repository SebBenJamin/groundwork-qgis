"""Interpretation of a crossing profile, cut at the crossing (no QGIS).

``crossing_marks`` takes the other profile's pieces (in its own chainage) and the chainage
``s`` of the crossing on that profile, and returns what a vertical line there meets.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .interpretation import InterpPiece


@dataclass
class CrossMark:
    feature_id: str
    kind: str           # "line", "polygon" or "point"
    z_top: float
    z_bottom: float     # = z_top for lines and points
    #: the piece it comes from (for its symbol); not part of equality
    piece_id: str = field(default="", compare=False)


def _cuts(vertices, s: float, half_open: bool) -> list[float]:
    """Elevations where the polyline ``vertices`` meets the vertical line at ``s``. Vertical
    segments are skipped; ``half_open`` counts a vertex on the line once (rings)."""
    out = []
    for (s0, z0), (s1, z1) in zip(vertices[:-1], vertices[1:]):
        if s0 == s1:
            continue
        lo, hi = min(s0, s1), max(s0, s1)
        inside = lo <= s < hi if half_open else lo <= s <= hi
        if inside:
            out.append(float(z0 + (z1 - z0) * (s - s0) / (s1 - s0)))
    return out


def crossing_marks(pieces: list[InterpPiece], s: float, point_tol: float) -> list[CrossMark]:
    marks: list[CrossMark] = []
    for p in pieces:
        if p.kind == "point":
            ps, pz = p.vertices[0]
            if abs(ps - s) <= point_tol:
                marks.append(CrossMark(p.feature_id, "point", float(pz), float(pz), p.id))
        elif p.kind == "line":
            zs: list[float] = []
            for z in _cuts(p.vertices, s, half_open=False):
                if not zs or abs(zs[-1] - z) > 1e-9:       # a vertex on the line: once
                    zs.append(z)
            marks += [CrossMark(p.feature_id, "line", z, z, p.id) for z in zs]
        elif p.kind == "polygon":
            ring = list(p.vertices)
            if ring and ring[0] != ring[-1]:
                ring.append(ring[0])
            zs = sorted(_cuts(ring, s, half_open=True), reverse=True)
            marks += [CrossMark(p.feature_id, "polygon", zs[i], zs[i + 1], p.id)
                      for i in range(0, len(zs) - 1, 2)]
    return marks
