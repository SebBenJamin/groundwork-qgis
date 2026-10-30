"""The surface a section's depth models hang from: station elevations or a DEM. QGIS-free.

``Profile.metadata["topography"]`` holds the choice, "stations" (the default) or "dem"."""
from __future__ import annotations

import numpy as np

from ..core.model import StationSet

TOPOGRAPHY_SOURCES = ("stations", "dem")


def topo_set(sets: list[StationSet]) -> StationSet | None:
    """The first station set with at least one elevation."""
    for s in sets:
        if len(s.xyz) and np.isfinite(s.xyz[:, 2]).any():
            return s
    return None


def station_line(sets: list[StationSet]) -> tuple[np.ndarray, np.ndarray] | None:
    """(chainage, elevation) of ``topo_set(sets)``, ascending, without missing values."""
    s = topo_set(sets)
    if s is None:
        return None
    ok = np.isfinite(s.xyz[:, 2]) & np.isfinite(s.chainage)
    order = np.argsort(s.chainage[ok], kind="stable")
    return s.chainage[ok][order].astype(float), s.xyz[ok, 2][order].astype(float)


def dem_line(dem: tuple[np.ndarray, np.ndarray] | None) -> tuple[np.ndarray, np.ndarray] | None:
    """DEM samples ``(s, z)`` as a topography line. NaN (nodata) samples are dropped, so
    interpolation bridges gaps and clamps beyond the last valid sample; ``None`` with fewer
    than two valid samples."""
    if dem is None:
        return None
    s, z = (np.asarray(a, dtype=float) for a in dem)
    ok = np.isfinite(s) & np.isfinite(z)
    if ok.sum() < 2:
        return None
    order = np.argsort(s[ok], kind="stable")
    return s[ok][order], z[ok][order]
