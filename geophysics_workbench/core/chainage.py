"""Chainage (distance along a polyline) for crooked profile lines. Pure NumPy."""
from __future__ import annotations

import numpy as np


class Chainage:
    """A polyline with a distance-along-line coordinate ``s``."""

    def __init__(self, xy: np.ndarray):
        pts = np.asarray(xy, dtype=float)
        if pts.ndim != 2 or pts.shape[1] != 2:
            raise ValueError("xy must have shape (n, 2)")
        if len(pts) > 1:
            keep = np.r_[True, np.any(np.diff(pts, axis=0) != 0, axis=1)]
            pts = pts[keep]
        if len(pts) < 2:
            raise ValueError("a line needs at least two distinct points")
        self._xy = pts
        seg = np.diff(pts, axis=0)
        self._seg_len = np.hypot(seg[:, 0], seg[:, 1])
        self._cum = np.r_[0.0, np.cumsum(self._seg_len)]
        if self._cum[-1] <= 0:
            raise ValueError("line has zero length")

    @property
    def xy(self) -> np.ndarray:
        return self._xy.copy()

    @property
    def length(self) -> float:
        return float(self._cum[-1])

    def to_xy(self, s) -> np.ndarray:
        """Coordinates at chainage ``s``; beyond the ends it extrapolates
        along the first/last segment."""
        s = np.asarray(s, dtype=float)
        i = np.clip(np.searchsorted(self._cum, s, side="right") - 1, 0, len(self._seg_len) - 1)
        a = self._xy[i]
        d = (self._xy[i + 1] - a) / self._seg_len[i][..., None]
        return a + d * (s - self._cum[i])[..., None]

    def project(self, xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Project points onto the line, returning ``(s, offset)``.

        ``s`` is the chainage of the nearest point ON the polyline (clamped to
        ``[0, length]``, no extrapolation); ``offset`` is the signed distance
        to it, positive to the left of the line direction.
        """
        p = np.atleast_2d(np.asarray(xy, dtype=float))
        a = self._xy[:-1]
        d = np.diff(self._xy, axis=0)
        rel = p[:, None, :] - a[None, :, :]                      # (m, k, 2)
        t = np.clip(np.einsum("mkc,kc->mk", rel, d) / self._seg_len**2, 0.0, 1.0)
        diff = rel - t[..., None] * d[None, :, :]
        dist = np.hypot(diff[..., 0], diff[..., 1])
        best = np.argmin(dist, axis=1)
        rows = np.arange(len(p))
        cross = d[best, 0] * rel[rows, best, 1] - d[best, 1] * rel[rows, best, 0]
        s = self._cum[best] + t[rows, best] * self._seg_len[best]
        offset = np.where(cross >= 0, 1.0, -1.0) * dist[rows, best]
        return s, offset

    def reversed(self) -> "Chainage":
        return Chainage(self._xy[::-1])
