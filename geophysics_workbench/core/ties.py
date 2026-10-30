"""Ties where two profiles cross: model columns and their mismatch (no QGIS/Qt)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .colors import ColorScale


@dataclass
class TieColumn:
    dataset_name: str
    z_top: np.ndarray       # (k,) top to bottom
    z_bottom: np.ndarray
    values: np.ndarray
    scale: ColorScale | None
    quantity: str
    unit: str


@dataclass
class Tie:
    s: float                # chainage on this profile
    other_id: str
    other_name: str
    s_other: float          # chainage on the crossing profile
    distance: float         # horizontal gap between the two lines at the crossing
    columns: list[TieColumn]


@dataclass
class TieMismatch:
    z: np.ndarray                       # common sample grid
    a: np.ndarray                       # values of column a on z (nan where undefined)
    b: np.ndarray
    factor: float | None                # log quantities: 10 ** median |log10(a/b)|
    rel_diff: float | None              # others: median |a-b| / mean(|a|, |b|)
    z_range: tuple[float, float] | None  # overlap of the two columns; None without one


def _sample(col: TieColumn, z: np.ndarray) -> np.ndarray:
    """Value of the interval containing each z, nan outside every interval."""
    out = np.full(z.shape, np.nan)
    for top, bot, v in zip(col.z_top, col.z_bottom, col.values):
        out[(z <= top) & (z >= bot) & np.isnan(out)] = v
    return out


def tie_mismatch(a: TieColumn, b: TieColumn) -> TieMismatch:
    empty = np.empty(0)
    if a.z_top.size == 0 or b.z_top.size == 0:
        return TieMismatch(empty, empty, empty, None, None, None)
    hi = min(float(np.max(a.z_top)), float(np.max(b.z_top)))
    lo = max(float(np.min(a.z_bottom)), float(np.min(b.z_bottom)))
    if not hi > lo:
        return TieMismatch(empty, empty, empty, None, None, None)
    step = max(0.25, (hi - lo) / 400.0)
    z = np.append(np.arange(lo, hi, step), hi)
    va, vb = _sample(a, z), _sample(b, z)
    ok = np.isfinite(va) & np.isfinite(vb)
    factor = rel = None
    if a.quantity == "resistivity":
        ok &= (va > 0) & (vb > 0)
        if ok.any():
            factor = float(10 ** np.median(np.abs(np.log10(va[ok] / vb[ok]))))
    elif ok.any():
        mean = (np.abs(va[ok]) + np.abs(vb[ok])) / 2
        with np.errstate(invalid="ignore", divide="ignore"):
            r = np.abs(va[ok] - vb[ok]) / mean
        r = r[np.isfinite(r)]
        rel = float(np.median(r)) if r.size else None
    return TieMismatch(z, va, vb, factor, rel, (lo, hi))


def mismatch_text(m: TieMismatch) -> str:
    if m.z_range is None or (m.factor is None and m.rel_diff is None):
        return "no depth overlap"
    where = f"median, {m.z_range[0]:.0f}–{m.z_range[1]:.0f} m a.s.l."
    if m.factor is not None:
        return f"×{m.factor:.1f} ({where})"
    return f"{m.rel_diff * 100:.0f} % ({where})"
