"""Log curves of boreholes: track scale, data range and readout values (no QGIS/Qt).

A curve is drawn in its own track beside the borehole column. Samples that cannot be shown
(NULL, or <= 0 on a log scale) are gaps: the line breaks there and the readout never
interpolates across them."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DASHES = ("solid", "dash", "dot", "dashdot")
FILLS = ("none", "left", "right")


@dataclass
class CurveStyle:
    colour: str = "#1f7a3a"
    width_mm: float = 0.4
    dash: str = "solid"           # one of DASHES
    fill: str = "none"            # one of FILLS: fill from the line to the track's edge
    fill_colour: str = "#1f7a3a40"
    log: bool = False
    vmin: float | None = None     # None: the data range of the boreholes in view
    vmax: float | None = None


def _usable(values: np.ndarray, log: bool) -> np.ndarray:
    v = np.asarray(values, float)
    ok = np.isfinite(v)
    if log:
        ok &= v > 0
    return ok


def track_fraction(values: np.ndarray, vmin: float, vmax: float, log: bool) -> np.ndarray:
    """Each value's position across the track, 0 (left, ``vmin``) .. 1 (right, ``vmax``);
    nan where the value cannot be shown. Values beyond the range are clipped to the edges."""
    v = np.asarray(values, float)
    out = np.full(v.shape, np.nan)
    ok = _usable(v, log)
    if log:
        if vmin <= 0 or vmax <= 0:
            return out
        lo, hi, x = np.log10(vmin), np.log10(vmax), np.log10(v[ok])
    else:
        lo, hi, x = vmin, vmax, v[ok]
    span = hi - lo
    out[ok] = 0.5 if span == 0 else np.clip((x - lo) / span, 0.0, 1.0)
    return out


def data_range(curves, log: bool) -> tuple[float, float] | None:
    """(min, max) over the usable samples of ``curves``; ``None`` when there are none."""
    parts = [np.asarray(c.values, float)[_usable(c.values, log)] for c in curves]
    parts = [p for p in parts if p.size]
    if not parts:
        return None
    allv = np.concatenate(parts)
    return float(allv.min()), float(allv.max())


def value_at(curve, depth: float, log: bool = False) -> float | None:
    """The curve's value at ``depth``: linear between the two neighbouring samples, ``None``
    outside the samples or when either neighbour is a gap (on a ``log`` scale also a sample
    <= 0, as in the drawn line)."""
    d, v = np.asarray(curve.depth, float), np.asarray(curve.values, float)
    if log:
        v = np.where(v > 0, v, np.nan)
    if d.size == 0 or depth < d[0] or depth > d[-1]:
        return None
    i = int(np.searchsorted(d, depth))
    if i < d.size and d[i] == depth:
        return float(v[i]) if np.isfinite(v[i]) else None
    a, b = i - 1, i
    if not (np.isfinite(v[a]) and np.isfinite(v[b])) or d[b] == d[a]:
        return None
    t = (depth - d[a]) / (d[b] - d[a])
    return float(v[a] + t * (v[b] - v[a]))
