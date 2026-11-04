"""Where a four-electrode reading sits on a pseudosection (no QGIS).

Depth is the median depth of investigation (Edwards 1977): the depth above which half of a
homogeneous half-space's signal comes from. For one electrode pair at distance r the share
from above depth z is 1 - r / sqrt(r^2 + 4 z^2); a reading combines its pairs AM(+), AN(-),
BM(-), BN(+) weighted like its geometric factor, so any geometry works (Wenner 0.519a,
dipole-dipole n=1 0.416a, pole-pole 0.866a). An absent pole electrode is NaN.
"""
from __future__ import annotations

import numpy as np

_PAIRS = (("a", "m", 1.0), ("a", "n", -1.0), ("b", "m", -1.0), ("b", "n", 1.0))


def midpoint(a, b, m, n) -> np.ndarray:
    """Mean x of the electrodes present."""
    return np.nanmean(np.vstack([np.asarray(v, float) for v in (a, b, m, n)]), axis=0)


def median_depth(a, b, m, n, iterations: int = 60) -> np.ndarray:
    """Median depth of investigation per reading (same units as x); NaN when the reading
    has no signal (e.g. coincident electrodes)."""
    pos = {k: np.atleast_1d(np.asarray(v, float)) for k, v in zip("abmn", (a, b, m, n))}
    pairs = []
    for p, q, sign in _PAIRS:
        r = np.abs(pos[p] - pos[q])
        ok = np.isfinite(r) & (r > 0)
        pairs.append((np.where(ok, r, 1.0), np.where(ok, sign, 0.0)))
    total = sum(s / r for r, s in pairs)                    # proportional to 1/K
    scale = sum(np.abs(s) / r for r, s in pairs)
    signal = np.abs(total) > 1e-9 * np.maximum(scale, 1e-300)
    safe_total = np.where(signal, total, 1.0)

    def above(z):                                           # share of the signal above z
        rest = sum(s / np.sqrt(r * r + 4 * z * z) for r, s in pairs)
        return 1.0 - rest / safe_total

    span = max(float(np.max(np.where(s != 0, r, 0.0))) for r, s in pairs) or 1.0
    lo = np.zeros_like(total)
    hi = np.full_like(total, 10.0 * span)
    for _ in range(iterations):
        mid = (lo + hi) / 2
        low = above(mid) < 0.5
        lo = np.where(low, mid, lo)
        hi = np.where(low, hi, mid)
    return np.where(signal, (lo + hi) / 2, np.nan)
