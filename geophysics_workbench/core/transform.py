"""Control-point transforms from local to real-world coordinates. Pure NumPy."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Transform2D:
    """``world = matrix @ local + offset``; residuals are in world units."""

    kind: str
    matrix: np.ndarray
    offset: np.ndarray
    residuals: np.ndarray
    rms: float

    def apply(self, xy: np.ndarray) -> np.ndarray:
        pts = np.asarray(xy, dtype=float)
        return pts @ self.matrix.T + self.offset

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "matrix": np.asarray(self.matrix, float).tolist(),
            "offset": np.asarray(self.offset, float).tolist(),
            "residuals": np.asarray(self.residuals, float).tolist(),
            "rms": float(self.rms),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transform2D":
        return cls(
            kind=d["kind"],
            matrix=np.array(d["matrix"], dtype=float),
            offset=np.array(d["offset"], dtype=float),
            residuals=np.array(d["residuals"], dtype=float),
            rms=float(d["rms"]),
        )


def fit_control_points(local: np.ndarray, world: np.ndarray) -> Transform2D:
    """Fit local -> world from control points.

    Two points give a similarity (rotation + uniform scale + shift); three or
    more give a least-squares affine. Raises ValueError for fewer than two
    points or degenerate (coincident / collinear for affine) local points.
    """
    loc = np.asarray(local, dtype=float)
    wld = np.asarray(world, dtype=float)
    if loc.ndim != 2 or loc.shape[1] != 2 or loc.shape != wld.shape:
        raise ValueError("local and world must both have shape (n, 2)")
    n = len(loc)
    if n < 2:
        raise ValueError("at least two control points are required")
    if np.ptp(loc, axis=0).max() == 0:
        raise ValueError("control points are coincident in local coordinates")

    if n == 2:
        z = loc[:, 0] + 1j * loc[:, 1]
        w = wld[:, 0] + 1j * wld[:, 1]
        a = (w[1] - w[0]) / (z[1] - z[0])
        b = w[0] - a * z[0]
        matrix = np.array([[a.real, -a.imag], [a.imag, a.real]])
        offset = np.array([b.real, b.imag])
        kind = "similarity"
    else:
        design = np.column_stack([loc, np.ones(n)])
        if np.linalg.matrix_rank(design) < 3:
            raise ValueError("control points are collinear in local coordinates")
        coef, *_ = np.linalg.lstsq(design, wld, rcond=None)
        matrix = coef[:2].T
        offset = coef[2]
        kind = "affine"

    resid = np.hypot(*(loc @ matrix.T + offset - wld).T)
    rms = float(np.sqrt(np.mean(resid**2)))
    return Transform2D(kind, matrix, offset, resid, rms)
