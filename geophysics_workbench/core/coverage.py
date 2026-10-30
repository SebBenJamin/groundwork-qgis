"""Model extent against the stations' chainage coverage (no QGIS/Qt)."""
from __future__ import annotations

import numpy as np

from .model import StationSet

DEFAULT_LIMIT = 5.0     # metres, when the station spacing cannot be computed


def _chainage(station_set: StationSet) -> np.ndarray:
    s = np.asarray(station_set.chainage, dtype=float)
    return s[np.isfinite(s)]


def station_coverage(station_sets: list[StationSet]) -> tuple[float, float] | None:
    """(min, max) station chainage over ``station_sets``; None without stations."""
    s = np.concatenate([_chainage(st) for st in station_sets]) if station_sets else np.empty(0)
    return (float(s.min()), float(s.max())) if s.size else None


def station_overhang(mesh_s_min: float, mesh_s_max: float,
                     station_set: StationSet) -> tuple[float, float]:
    """Metres by which a model spanning chainage ``mesh_s_min`` .. ``mesh_s_max`` (data
    metres already mapped with ``data_to_chainage``, either order) reaches before the
    lowest and beyond the highest station chainage of ``station_set``: ``(start, end)``
    along the profile. ``(0, 0)`` when it lies within the stations or there are none."""
    cover = station_coverage([station_set])
    if cover is None:
        return 0.0, 0.0
    lo, hi = sorted((float(mesh_s_min), float(mesh_s_max)))
    return max(0.0, cover[0] - lo), max(0.0, hi - cover[1])


def overhang_limit(station_set: StationSet) -> float:
    """2 x the median station spacing along the chainage; 5 m when that is unknown."""
    s = np.unique(_chainage(station_set))
    gaps = np.diff(s)
    if not gaps.size or not np.median(gaps) > 0:
        return DEFAULT_LIMIT
    return 2.0 * float(np.median(gaps))


def overhang_message(s_min: float, s_max: float, station_set: StationSet,
                     profile_name: str) -> str:
    """Warning for a model spanning chainage ``s_min`` .. ``s_max`` (either order) when it
    reaches more than ``overhang_limit`` before or beyond ``station_set``; "" otherwise."""
    cover = station_coverage([station_set])
    if cover is None:
        return ""
    start, end = station_overhang(s_min, s_max, station_set)
    limit = overhang_limit(station_set)
    # the low-chainage end holds station 1 unless the stations are numbered backwards
    first, last = "before the first station", "beyond the last station"
    low_word, high_word = (first, last) if station_set.direction > 0 else (last, first)
    parts = [f"{d:.0f} m {word}" for d, word in ((start, low_word), (end, high_word))
             if d > limit]
    if not parts:
        return ""
    lo, hi = sorted((float(s_min), float(s_max)))
    return (f"Model spans {lo:.0f}–{hi:.0f} m along the profile; {profile_name}'s stations "
            f"span {cover[0]:.0f}–{cover[1]:.0f} m ({', '.join(parts)}). "
            "Is this the right profile?")
