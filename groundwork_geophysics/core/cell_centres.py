"""Rebuild rectangular cells from cell-centre models (no QGIS/Qt).

ZondRes2D xyz and R2/ResIPy ``res.dat`` files store one value per cell, at its centre.
When the centres line up in rows of constant z (or else columns of constant x), the real
cells are rebuilt as quads: edges at the midpoints between neighbouring centres, outer
edges half the neighbouring gap beyond the outermost centres. Fully vectorised.

Grouping alone does not prove a grid. Coarser cells at depth interleave with fine ones,
so neighbouring groups must join: their spans overlap, and the ends of their spans differ
by no more than ``JUMP`` x the end cells' extent, or the cells would draw as strips with
gaps. And a symmetric hill puts every elevation in exactly two columns, so its column
model also groups into rows of two cells each: when both groupings work for an elevation
model, the one with fewer, fuller groups is the grid (a coincidental grouping has many
tiny groups). A depth model hangs from a flat datum, so its rows are never coincidental:
valid rows always win there, and their span ends may step (a trapezoid model).
"""
from __future__ import annotations

import numpy as np

ABS_TOL = 1e-3          # metres: centres closer than this share a row / column level
REL_TOL = 1e-6          # ... or this fraction of the coordinate range, if larger
JUMP = 1.5              # neighbouring span ends may differ by this x the end cells' extent


def _tolerance(a: np.ndarray) -> float:
    return max(ABS_TOL, REL_TOL * float(np.ptp(a))) if a.size else ABS_TOL


def _outer_edges(level: np.ndarray, first: np.ndarray, last: np.ndarray):
    """Lower and upper edge of each sorted value: midpoints to the neighbours inside its
    group (``first``/``last`` mark group ends), half the neighbouring gap at the ends."""
    n = len(level)
    lo, hi = np.empty(n), np.empty(n)
    mid = 0.5 * (level[1:] + level[:-1])
    lo[1:], hi[:-1] = mid, mid
    gap_up = np.r_[level[1:] - level[:-1], np.nan]            # to the next value
    gap_dn = np.r_[np.nan, level[1:] - level[:-1]]            # from the previous value
    lo[first] = level[first] - 0.5 * gap_up[first]
    hi[last] = level[last] + 0.5 * gap_dn[last]
    return lo, hi


def _spans_join(lo_s, hi_s, first, last, check_jumps: bool = True) -> bool:
    """True when every group's span along ``b`` joins the next group's (arrays sorted by
    group in level order, then ``b``): the spans overlap, and (with ``check_jumps``) at
    each end they differ by at most ``JUMP`` x the larger extent of the two groups' end
    cells there."""
    g_lo, g_hi = lo_s[first], hi_s[last]
    if not np.all(np.maximum(g_lo[1:], g_lo[:-1]) < np.minimum(g_hi[1:], g_hi[:-1])):
        return False
    if not check_jumps:
        return True
    ext_lo = hi_s[first] - lo_s[first]                   # first cell of each group
    ext_hi = hi_s[last] - lo_s[last]                     # last cell of each group
    ok_lo = np.abs(np.diff(g_lo)) <= JUMP * np.maximum(ext_lo[1:], ext_lo[:-1])
    ok_hi = np.abs(np.diff(g_hi)) <= JUMP * np.maximum(ext_hi[1:], ext_hi[:-1])
    return bool(np.all(ok_lo) and np.all(ok_hi))


def _grouped_boxes(a: np.ndarray, b: np.ndarray, check_jumps: bool = True):
    """Boxes for centres grouped by equal ``a`` (rows when ``a`` is z), or None.

    Returns ``(a_lo, a_hi, b_lo, b_hi, in_lowest, in_highest, n_groups)``, arrays in input
    order: the ``a`` edges come from the sorted group levels and the ``b`` edges from
    neighbours inside each group; ``in_lowest`` / ``in_highest`` mark centres of the
    lowest / highest ``a`` group; ``n_groups`` counts the groups.
    None when there are fewer than 2 groups, a group with fewer than 2 centres, two
    centres of one group at the same ``b``, or neighbouring groups that do not join
    (``_spans_join``; ``check_jumps`` also rejects span ends that jump)."""
    n = len(a)
    tol_a, tol_b = _tolerance(a), _tolerance(b)
    order_a = np.argsort(a, kind="stable")
    new_group = np.r_[True, np.diff(a[order_a]) > tol_a]
    gid = np.empty(n, dtype=np.int64)
    gid[order_a] = np.cumsum(new_group) - 1
    n_groups = int(gid.max()) + 1
    counts = np.bincount(gid, minlength=n_groups)
    if n_groups < 2 or counts.min() < 2:
        return None
    levels = np.bincount(gid, weights=a, minlength=n_groups) / counts
    # edges between group levels
    g_first = np.zeros(n_groups, dtype=bool)
    g_last = np.zeros(n_groups, dtype=bool)
    g_first[0] = g_last[-1] = True
    lev_lo, lev_hi = _outer_edges(levels, g_first, g_last)
    # edges inside each group, sorted by b
    order = np.lexsort((b, gid))
    gs, bs = gid[order], b[order]
    first = np.r_[True, gs[1:] != gs[:-1]]
    last = np.r_[gs[1:] != gs[:-1], True]
    if np.any(np.diff(bs)[~last[:-1]] <= tol_b):
        return None                                        # duplicate centre in a group
    lo_s, hi_s = _outer_edges(bs, first, last)
    if not _spans_join(lo_s, hi_s, first, last, check_jumps):
        return None                                        # strips with gaps between them
    b_lo, b_hi = np.empty(n), np.empty(n)
    b_lo[order], b_hi[order] = lo_s, hi_s
    return lev_lo[gid], lev_hi[gid], b_lo, b_hi, gid == 0, gid == n_groups - 1, n_groups


def cell_boxes(x, z, depth: bool = False) -> tuple[str, np.ndarray] | None:
    """``("rows" | "columns", boxes)`` with boxes ``(n, 4)`` = x_lo, x_hi, z_lo, z_hi in
    input order, or None when the centres form neither rows nor columns that tile. When
    both work, rows win for a depth model; otherwise the grouping with fewer groups wins
    (rows on a tie).

    With ``depth`` the top edge of a row model is depth 0 (the surface): the lowest row
    edge when the depths are positive, the highest when they are given as negative z."""
    x, z = np.asarray(x, dtype=float).ravel(), np.asarray(z, dtype=float).ravel()
    # depth rows are real (flat datum): a trapezoid's ends may step by several cells
    rows, cols = _grouped_boxes(z, x, check_jumps=not depth), _grouped_boxes(x, z)
    if rows is not None and (depth or cols is None or rows[-1] <= cols[-1]):
        z_lo, z_hi, x_lo, x_hi, in_first, in_last, _n = rows
        if depth and z.min() >= 0:
            z_lo = np.where(in_first, 0.0, z_lo)
        elif depth and z.max() <= 0:
            z_hi = np.where(in_last, 0.0, z_hi)
        return "rows", np.column_stack([x_lo, x_hi, z_lo, z_hi])
    if cols is not None:
        x_lo, x_hi, z_lo, z_hi, _first, _last, _n = cols
        return "columns", np.column_stack([x_lo, x_hi, z_lo, z_hi])
    return None


def quads(boxes: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Vertices ``(4n, 2)`` and cells ``(n, 4)`` (each quad its own 4 vertices,
    counter-clockwise) for ``boxes`` from ``cell_boxes``."""
    x_lo, x_hi, z_lo, z_hi = boxes.T
    verts = np.stack([np.column_stack([x_lo, z_lo]), np.column_stack([x_hi, z_lo]),
                      np.column_stack([x_hi, z_hi]), np.column_stack([x_lo, z_hi])], axis=1)
    return verts.reshape(-1, 2), np.arange(4 * len(boxes)).reshape(-1, 4)
