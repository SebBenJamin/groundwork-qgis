"""Trace positions along a track, shared by the SEG-Y and radar readers (no QGIS/Qt): repeated
position fixes spread out, and whether the positions describe a line walked once."""
from __future__ import annotations

import numpy as np

#: one position holding more than this share of the traces ...
REPEAT_SHARE = 0.10
#: ... and more than this many of them is not a line walked once
REPEAT_MIN = 5
#: positions closer than this (metres or the file's units) are the same position
_SAME = 0.01


def spread_fixes(xy) -> np.ndarray:
    """Positions with repeated fixes spread out: the traces between two changes of position
    are placed evenly from one fix to the next; the last run keeps the spacing of the run
    before it. Without a second fix the positions are returned as they are."""
    xy = np.asarray(xy, dtype=np.float64)
    n = len(xy)
    starts = np.flatnonzero(np.r_[True, (np.diff(xy, axis=0) != 0).any(axis=1)])
    if starts.size < 2:
        return xy
    lengths = np.diff(np.r_[starts, n])
    fixes = xy[starts]
    steps = np.empty_like(fixes)
    steps[:-1] = np.diff(fixes, axis=0) / lengths[:-1, None]
    steps[-1] = steps[-2]
    run = np.repeat(np.arange(starts.size), lengths)
    k = (np.arange(n) - starts[run]).astype(np.float64)
    return fixes[run] + k[:, None] * steps[run]


def repeats(xy) -> bool:
    """True when the positions (n, 2) do not describe a line walked once: one position the
    line comes back to holds more than ``REPEAT_SHARE`` of the traces (and more than
    ``REPEAT_MIN``; a held fix in one run is a repeated fix, not a return), or, after the
    repeated fixes are spread out, the distance along the line (its main direction) goes
    back by more than one trace spacing (the median step). GPS-style runs of one fix that
    always advance are a line walked once."""
    xy = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
    n = len(xy)
    if n < 3 or not np.isfinite(xy).all():
        return False
    keys = np.round(xy / _SAME).astype(np.int64)
    _u, which, counts = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    if len(counts) < 2:
        return False                            # no position change: nothing to judge
    which = which.reshape(-1)
    starts = np.r_[True, which[1:] != which[:-1]]
    runs = np.bincount(which[starts], minlength=len(counts))
    # a position the line comes back to; one run of a held fix is spread out below
    top = int(counts[runs > 1].max(initial=0))
    if top > REPEAT_MIN and top > REPEAT_SHARE * n:
        return True
    spread = spread_fixes(xy)
    steps = np.diff(spread, axis=0)
    lengths = np.hypot(steps[:, 0], steps[:, 1])
    moving = lengths > _SAME
    if not moving.any():
        return False
    spacing = float(np.median(lengths[moving]))
    along = _along(spread)
    if along[-1] < along[0]:
        along = -along                          # walked against the axis
    return bool((np.maximum.accumulate(along) - along).max() > spacing)


def _along(xy: np.ndarray) -> np.ndarray:
    """Distance of each position along the line's main direction (its principal axis)."""
    centred = xy - xy.mean(axis=0)
    _u, _s, vt = np.linalg.svd(centred, full_matrices=False)
    return centred @ vt[0]
