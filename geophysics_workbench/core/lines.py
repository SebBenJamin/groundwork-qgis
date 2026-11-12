"""Profile lines from what a user has: surveyed positions in a known order, or the map
coordinates of a model's cells. Pure NumPy and SciPy (does not import ``core.model``)."""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from .placement import Positions

#: two points closer than this (in map metres) are the same coordinate
SAME = 1e-6


def order_of(positions: Positions) -> np.ndarray:
    """Index order of the positions: by station number when there are numbers, else by
    in-line distance when every position has one, else as given. The sort is stable."""
    n = len(positions.xyz)
    if positions.numbers is not None:
        return np.argsort(np.asarray(positions.numbers), kind="stable")
    if positions.inline is not None:
        inline = np.asarray(positions.inline, dtype=float)
        if inline.shape == (n,) and np.isfinite(inline).all():
            return np.argsort(inline, kind="stable")
    return np.arange(n)


def _rows_text(pairs) -> str:
    return ", ".join(f"rows {a} and {b}" for a, b in pairs)


def line_through(xy: np.ndarray, rows: np.ndarray | None = None) -> np.ndarray:
    """The polyline through the points in the order given. Raises ValueError naming the rows
    that repeat a coordinate or have none, and when fewer than two points are given.
    ``rows``: each point's 1-based row in the user's input (default 1..n), for the messages."""
    pts = np.asarray(xy, dtype=float)[:, :2]
    labels = np.arange(1, len(pts) + 1) if rows is None else np.asarray(rows)
    missing = labels[~np.isfinite(pts).all(axis=1)]
    if len(missing):
        raise ValueError("No map position in row" + ("s " if len(missing) > 1 else " ")
                         + ", ".join(str(r) for r in missing) + ".")
    if len(pts) < 2:
        raise ValueError("A line needs at least two distinct positions.")
    pairs = sorted(tuple(sorted((int(labels[i]), int(labels[j]))))
                   for i, j in cKDTree(pts).query_pairs(SAME))
    if pairs:
        raise ValueError(f"Positions repeat a coordinate: {_rows_text(pairs)}.")
    return pts.copy()


def drop_repeated_vertices(xy: np.ndarray) -> np.ndarray:
    """The vertices without those that repeat the previous one (closer than ``SAME``)."""
    pts = np.asarray(xy, dtype=float)[:, :2]
    if len(pts) < 2:
        return pts.copy()
    keep = [0]
    for i in range(1, len(pts)):
        if np.hypot(*(pts[i] - pts[keep[-1]])) >= SAME:
            keep.append(i)
    return pts[keep]


def _merged(xy: np.ndarray, tol: float) -> np.ndarray:
    return np.unique(np.round(xy / tol) * tol, axis=0)


def _walk(pts: np.ndarray, start: int) -> np.ndarray:
    """Visit every point, always going on to the nearest one not yet visited."""
    n = len(pts)
    tree = cKDTree(pts)
    left = np.ones(n, dtype=bool)
    order = np.empty(n, dtype=int)
    i = start
    for k in range(n):
        order[k] = i
        left[i] = False
        if k == n - 1:
            break
        _, near = tree.query(pts[i], k=min(16, n))
        near = [j for j in np.atleast_1d(near) if left[j]]
        if near:
            i = near[0]
        else:
            cand = np.flatnonzero(left)
            i = cand[np.argmin(np.hypot(*(pts[cand] - pts[i]).T))]
    return order


def _douglas_peucker(pts: np.ndarray, eps: float) -> np.ndarray:
    keep = np.zeros(len(pts), dtype=bool)
    keep[[0, -1]] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = pts[b] - pts[a]
        rel = pts[a + 1:b] - pts[a]
        length = np.hypot(*seg)
        if length > 0:
            dist = np.abs(seg[0] * rel[:, 1] - seg[1] * rel[:, 0]) / length
        else:
            dist = np.hypot(rel[:, 0], rel[:, 1])
        i = int(np.argmax(dist))
        if dist[i] > eps:
            m = a + 1 + i
            keep[m] = True
            stack += [(a, m), (m, b)]
    return pts[keep]


def line_from_cloud(xy: np.ndarray) -> tuple[np.ndarray, int]:
    """(line, number of bends) through the unique map positions of a model's cells, ordered
    along the line and simplified. Raises ValueError when the positions cover an area."""
    pts = np.asarray(xy, dtype=float)[:, :2]
    pts = pts[np.isfinite(pts).all(axis=1)]
    pts = _merged(pts, SAME) if len(pts) else pts
    if len(pts) < 2:
        raise ValueError("The model's map coordinates have fewer than two distinct positions.")
    gap, _ = cKDTree(pts).query(pts, k=2)
    pts = _merged(pts, 0.01 * float(np.median(gap[:, 1])))
    centred = pts - pts.mean(axis=0)
    axis = np.linalg.svd(centred, full_matrices=False)[2][0]
    if axis[0] < 0 or (axis[0] == 0 and axis[1] < 0):
        axis = -axis
    pts = pts[_walk(pts, int(np.argmin(centred @ axis)))]
    steps = np.hypot(*np.diff(pts, axis=0).T)
    diagonal = float(np.hypot(*(pts.max(axis=0) - pts.min(axis=0))))
    if steps.sum() > 3 * diagonal:
        raise ValueError("The model's map coordinates do not follow a line: this looks like "
                         "an area or a 3D model. Draw the profile line instead.")
    line = _douglas_peucker(pts, 0.5 * float(np.median(steps)))
    return line, len(line) - 2
