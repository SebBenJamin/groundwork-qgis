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


def _nearest(points, s, z, tol_s, tol_z):
    if not points:
        return None
    a = np.asarray(points, float)
    d = np.hypot((a[:, 0] - s) / tol_s, (a[:, 1] - z) / tol_z)
    i = int(np.argmin(d))
    return (float(a[i, 0]), float(a[i, 1])) if d[i] <= 1.0 else None


def snap(s: float, z: float, targets: SnapTargets, tol_s: float,
         tol_z: float) -> tuple[float, float] | None:
    """The snapped (s, z), or None when nothing is near. A vertex wins over a borehole
    boundary, which wins over the ground line (same s, z on the line)."""
    for pts in (targets.vertices, targets.boundaries):
        hit = _nearest(pts, s, z, tol_s, tol_z)
        if hit is not None:
            return hit
    if targets.ground is not None and len(targets.ground[0]) >= 2:
        gs, gz = (np.asarray(a, float) for a in targets.ground)
        if gs[0] <= s <= gs[-1]:
            zg = float(np.interp(s, gs, gz))
            if abs(z - zg) <= tol_z:
                return float(s), zg
    return None
