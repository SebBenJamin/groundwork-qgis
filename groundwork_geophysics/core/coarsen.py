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


def _lattice(a: np.ndarray) -> tuple[float, float] | None:
    """(first level, spacing) when the values of ``a`` sit on at least two levels at a
    regular spacing, else None."""
    a = np.sort(a[np.isfinite(a)])
    if len(a) < 2:
        return None
    tol = _tolerance(a)
    levels = a[np.r_[True, np.diff(a) > tol]]
    if len(levels) < 2:
        return None
    spacing = float(np.median(np.diff(levels)))
    if spacing <= tol:
        return None
    k = np.round((levels - levels[0]) / spacing)
    if np.abs(levels - (levels[0] + k * spacing)).max() > max(tol, 0.01 * spacing):
        return None
    return float(levels[0]), spacing


def point_grid(x, z) -> PointGrid | None:
    """The regular grid ``x`` (position along the line) and ``z`` sit on, or None."""
    x, z = np.asarray(x, float).ravel(), np.asarray(z, float).ravel()
    gx, gz = _lattice(x), _lattice(z)
    if gx is None or gz is None:
        return None
    return PointGrid(int(len(x)), gx[1], gz[1])


def _nice(size: float) -> bool:
    if size <= 0:
        return False
    mantissa = size / 10 ** math.floor(math.log10(size))
    return any(abs(mantissa - n) <= 1e-6 * n for n in _NICE) or abs(mantissa - 10) <= 1e-5


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
    gx, gz = _lattice(x), _lattice(z)
    if gx is None or gz is None:
        raise ValueError("the points are not on a regular grid")
    fx, fz = (max(1, int(f)) for f in block)
    ix = np.round((x - gx[0]) / gx[1]).astype(np.int64)
    iz = np.round((z - gz[0]) / gz[1]).astype(np.int64)
    rows = int(iz.max()) // fz + 1
    keys, inverse = np.unique((ix // fx) * rows + iz // fz, return_inverse=True)
    inverse = inverse.ravel()
    n = len(keys)
    order = np.argsort(inverse, kind="stable")
    starts = np.r_[0, np.flatnonzero(np.diff(inverse[order])) + 1]

    def span(i, g):
        lo = np.minimum.reduceat(i[order], starts)
        hi = np.maximum.reduceat(i[order], starts)
        return g[0] + g[1] * (lo - 0.5), g[0] + g[1] * (hi + 0.5)
    boxes = np.column_stack([*span(ix, gx), *span(iz, gz)])
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
