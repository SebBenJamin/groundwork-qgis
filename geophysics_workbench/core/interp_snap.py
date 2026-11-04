"""Snapping for interpretation drawing on the section (no QGIS).

Coordinates are section space: chainage s and elevation z. Tolerances are given per axis
(the section is usually exaggerated), so "near" means ``hypot(ds/tol_s, dz/tol_z) <= 1``.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class SnapTargets:
    vertices: list[tuple[float, float]] = field(default_factory=list)    # existing pieces
    boundaries: list[tuple[float, float]] = field(default_factory=list)  # borehole layers
    ground: tuple[np.ndarray, np.ndarray] | None = None                  # (s asc, z)
    lines: list[np.ndarray] = field(default_factory=list)   # (k, 2) polylines, e.g. coverage edge


def _nearest(points, s, z, tol_s, tol_z):
    if not points:
        return None
    a = np.asarray(points, float)
    d = np.hypot((a[:, 0] - s) / tol_s, (a[:, 1] - z) / tol_z)
    i = int(np.argmin(d))
    return (float(a[i, 0]), float(a[i, 1])) if d[i] <= 1.0 else None


def _on_lines(lines, s, z, tol_s, tol_z):
    """Nearest point on any polyline, in the scaled metric, when within tolerance."""
    best, best_d = None, 1.0
    p = np.array([s / tol_s, z / tol_z])
    for line in lines:
        a = np.asarray(line, float)
        if len(a) < 2:
            continue
        a = a / [tol_s, tol_z]
        u, v = a[:-1], a[1:]
        d = v - u
        den = np.maximum((d * d).sum(axis=1), 1e-30)
        t = np.clip(((p - u) * d).sum(axis=1) / den, 0.0, 1.0)
        q = u + t[:, None] * d
        dist = np.hypot(*(q - p).T)
        i = int(np.argmin(dist))
        if dist[i] <= best_d:
            best_d, best = dist[i], (float(q[i, 0] * tol_s), float(q[i, 1] * tol_z))
    return best


def snap(s: float, z: float, targets: SnapTargets, tol_s: float,
         tol_z: float) -> tuple[float, float] | None:
    """The snapped (s, z), or None when nothing is near. A vertex wins over a borehole
    boundary, over a line (e.g. the coverage edge), over the ground line (same s)."""
    for pts in (targets.vertices, targets.boundaries):
        hit = _nearest(pts, s, z, tol_s, tol_z)
        if hit is not None:
            return hit
    hit = _on_lines(targets.lines, s, z, tol_s, tol_z)
    if hit is not None:
        return hit
    if targets.ground is not None and len(targets.ground[0]) >= 2:
        gs, gz = (np.asarray(a, float) for a in targets.ground)
        if gs[0] <= s <= gs[-1]:
            zg = float(np.interp(s, gs, gz))
            if abs(z - zg) <= tol_z:
                return float(s), zg
    return None
