"""Editing operations on interpretation pieces (pure; the edit tool and undo stack use them).

Polygons are edited on their open ring (the closing vertex dropped) and re-closed by
``normalise``; every operation returns a new piece and leaves its input unchanged.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass

import numpy as np

from ..core.interpretation import MIN_VERTICES, InterpPiece, normalise


@dataclass
class Hit:
    piece: InterpPiece
    vertex: int | None = None       # index into piece.vertices
    edge: int | None = None         # edge from vertex i to i + 1
    interior: bool = False


def _open(p: InterpPiece) -> list[tuple[float, float]]:
    v = [(float(s), float(z)) for s, z in p.vertices]
    return v[:-1] if p.kind == "polygon" and len(v) > 1 and v[0] == v[-1] else v


def _with(p: InterpPiece, vertices) -> InterpPiece:
    out = copy.deepcopy(p)
    out.vertices = list(vertices)
    return normalise(out) if out.kind == "polygon" else out


def _inside(ring, s, z) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        (s0, z0), (s1, z1) = ring[i], ring[(i + 1) % n]
        if (z0 > z) != (z1 > z) and s < s0 + (z - z0) * (s1 - s0) / (z1 - z0):
            inside = not inside
    return inside


def _seg_dist(p, a, b) -> float:
    p, a, b = (np.asarray(x, float) for x in (p, a, b))
    ab = b - a
    t = 0.0 if not ab.any() else float(np.clip(np.dot(p - a, ab) / np.dot(ab, ab), 0, 1))
    return float(np.hypot(*(a + t * ab - p)))


def pick_piece(pieces, s: float, z: float, tol_s: float, tol_z: float) -> Hit | None:
    """Nearest vertex within tolerance, else an edge, else a polygon interior (in that
    order over all pieces). Distances are measured in tolerance units, so the vertical
    exaggeration does not bias picking."""
    def scaled(v):
        return v[0] / tol_s, v[1] / tol_z
    q = scaled((s, z))
    best_v = best_e = None
    for p in pieces:
        ring = _open(p)
        for i, v in enumerate(ring):
            d = float(np.hypot(*(np.subtract(scaled(v), q))))
            if d <= 1.0 and (best_v is None or d < best_v[0]):
                best_v = (d, Hit(p, vertex=i))
        n = len(ring)
        edges = n if p.kind == "polygon" else n - 1
        for i in range(max(0, edges)):
            d = _seg_dist(q, scaled(ring[i]), scaled(ring[(i + 1) % n]))
            if d <= 1.0 and (best_e is None or d < best_e[0]):
                best_e = (d, Hit(p, edge=i))
    if best_v is not None:
        return best_v[1]
    if best_e is not None:
        return best_e[1]
    for p in pieces:
        if p.kind == "polygon" and _inside(_open(p), s, z):
            return Hit(p, interior=True)
    return None


def move_vertex(p: InterpPiece, index: int, s: float, z: float) -> InterpPiece:
    ring = _open(p)
    ring[index] = (float(s), float(z))
    return _with(p, ring)


def insert_vertex(p: InterpPiece, edge: int, s: float, z: float) -> InterpPiece:
    ring = _open(p)
    ring.insert(edge + 1, (float(s), float(z)))
    return _with(p, ring)


def delete_vertex(p: InterpPiece, index: int) -> InterpPiece | None:
    """The piece without vertex ``index``; ``None`` when too few vertices would remain."""
    ring = _open(p)
    del ring[index]
    if len(ring) < MIN_VERTICES[p.kind]:
        return None
    return _with(p, ring)


def move_piece(p: InterpPiece, ds: float, dz: float) -> InterpPiece:
    out = copy.deepcopy(p)
    out.vertices = [(float(s) + ds, float(z) + dz) for s, z in p.vertices]
    return out
