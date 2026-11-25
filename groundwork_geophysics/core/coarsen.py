"""Coarser cells for over-fine model exports (no QGIS/Qt).

Some programs export a model interpolated onto a grid far finer than the inversion
resolves (0.25 m x 0.1 m, millions of points). Such a table's points lie on a regular
lattice in position and vertical (``point_grid``); Add Data offers whole-number blocks of
them (``proposed_block``) and the reader averages each block into one cell
(``coarsen_boxes``). The file is never changed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .cell_centres import _tolerance

#: more points than this: Add Data offers coarser cells
OFFER_ABOVE = 100_000
#: the proposal aims at about this many cells or fewer
TARGET_CELLS = 50_000
_MAX_FACTOR = 64
_NICE = (1.0, 2.0, 2.5, 5.0)


@dataclass(frozen=True)
class PointGrid:
    n_points: int
    dx: float                   # spacing of the position levels (m)
    dz: float                   # spacing of the vertical levels (m)


def _levels(a: np.ndarray) -> np.ndarray | None:
    """The distinct values of ``a`` (closer than the tolerance count as one), ascending;
    None with fewer than two. Uneven steps are fine: a real export's positions are rounded
    to centimetres, so the step from one to the next wobbles by millimetres."""
    a = np.sort(a[np.isfinite(a)])
    if len(a) < 2:
        return None
    levels = a[np.r_[True, np.diff(a) > _tolerance(a)]]
    return levels if len(levels) >= 2 else None


def _index(a: np.ndarray, levels: np.ndarray) -> np.ndarray:
    """The level each value of ``a`` belongs to."""
    return np.clip(np.searchsorted(levels, a + _tolerance(levels), side="right") - 1,
                   0, len(levels) - 1)


def _edges(levels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Lower and upper edge of each level's cells: halfway to the neighbouring levels, half
    a step beyond the outermost."""
    mid = 0.5 * (levels[1:] + levels[:-1])
    return (np.r_[levels[0] - 0.5 * (levels[1] - levels[0]), mid],
            np.r_[mid, levels[-1] + 0.5 * (levels[-1] - levels[-2])])


def point_grid(x, z) -> PointGrid | None:
    """The grid ``x`` (position along the line) and ``z`` sit on, or None: the points take
    most places of a grid of their distinct positions and heights (scattered points take
    hardly any). ``dx``/``dz``: the median step between neighbouring levels."""
    x, z = np.asarray(x, float).ravel(), np.asarray(z, float).ravel()
    lx, lz = _levels(x), _levels(z)
    if lx is None or lz is None or len(lx) * len(lz) > 2 * len(x):
        return None
    return PointGrid(int(len(x)), float(np.median(np.diff(lx))), float(np.median(np.diff(lz))))


def _nice(size: float) -> bool:
    if size <= 0:
        return False
    mantissa = size / 10 ** math.floor(math.log10(size))
    # within 2 %: along a diagonal line rounded positions are 0.2518 m apart, not 0.25
    return any(abs(mantissa - n) <= 0.02 * n for n in (*_NICE, 10.0))


def proposed_block(grid: PointGrid) -> tuple[int, int] | None:
    """Whole-number block factors ``(fx, fz)`` that bring ``grid`` to about
    ``TARGET_CELLS`` cells or fewer, the fewest points per block first; cells no more
    lopsided than the file's, of "nice" sizes (1, 2, 2.5, 5 x 10^k m) when the spacing
    allows, else any. None when ``grid`` has no more than ``OFFER_ABOVE`` points."""
    if grid.n_points <= OFFER_ABOVE:
        return None
    need = grid.n_points / TARGET_CELLS
    old = math.log(grid.dx / grid.dz)
    pairs = [(fx, fz) for fx in range(1, _MAX_FACTOR + 1) for fz in range(1, _MAX_FACTOR + 1)
             if fx * fz >= need
             and abs(math.log(fx * grid.dx / (fz * grid.dz))) <= abs(old) + 1e-9]
    if not pairs:
        return None
    nice = [(fx, fz) for fx, fz in pairs if _nice(fx * grid.dx) and _nice(fz * grid.dz)]
    return min(nice or pairs, key=lambda p: (p[0] * p[1],
                                              abs(math.log(p[0] * grid.dx / (p[1] * grid.dz))
                                                  - old)))


def coarsen_boxes(x, z, v, coverage, block: tuple[int, int], log: bool):
    """``(boxes, v, coverage)``: every block of ``block`` = (fx, fz) lattice points averaged
    into one cell. A box (x_lo, x_hi, z_lo, z_hi) spans the levels its own points have,
    half a spacing beyond, so the model's outline stays where it was (a block at the edge
    holds fewer points). ``v`` without a value is NaN (the caller turns fill values into
    NaN); a block keeps a value when at least half of its points have one: the mean (of
    log10 values when ``log``), else NaN. Coverage: the mean of its finite values, -inf
    when all it has is -inf (no ray), else NaN. ValueError when the points are not on a
    regular grid."""
    x, z, v = (np.asarray(a, float).ravel() for a in (x, z, v))
    if point_grid(x, z) is None:
        raise ValueError("the points are not on a regular grid")
    lx, lz = _levels(x), _levels(z)
    fx, fz = (max(1, int(f)) for f in block)
    ix, iz = _index(x, lx), _index(z, lz)
    rows = int(iz.max()) // fz + 1
    keys, inverse = np.unique((ix // fx) * rows + iz // fz, return_inverse=True)
    inverse = inverse.ravel()
    n = len(keys)
    order = np.argsort(inverse, kind="stable")
    starts = np.r_[0, np.flatnonzero(np.diff(inverse[order])) + 1]

    def span(i, levels):
        lo_edge, hi_edge = _edges(levels)
        return (lo_edge[np.minimum.reduceat(i[order], starts)],
                hi_edge[np.maximum.reduceat(i[order], starts)])
    boxes = np.column_stack([*span(ix, lx), *span(iz, lz)])
    with np.errstate(invalid="ignore", divide="ignore"):
        vals = np.log10(np.where(v > 0, v, np.nan)) if log else v
    has = np.isfinite(vals)
    n_all = np.bincount(inverse, minlength=n)
    n_has = np.bincount(inverse[has], minlength=n)
    total = np.bincount(inverse[has], weights=vals[has], minlength=n)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where((n_has > 0) & (2 * n_has >= n_all), total / np.maximum(n_has, 1),
                        np.nan)
    cv = np.power(10.0, mean) if log else mean
    ccov = None
    if coverage is not None:
        cov = np.asarray(coverage, float).ravel()
        fin = np.isfinite(cov)
        c_n = np.bincount(inverse[fin], minlength=n)
        c_sum = np.bincount(inverse[fin], weights=cov[fin], minlength=n)
        no_ray = np.bincount(inverse[np.isneginf(cov)], minlength=n) > 0
        ccov = np.where(c_n > 0, c_sum / np.maximum(c_n, 1), np.where(no_ray, -np.inf, np.nan))
    return boxes, cv, ccov
