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


def dem_line(dem: tuple[np.ndarray, np.ndarray] | None,
             stations: tuple[np.ndarray, np.ndarray] | None = None
             ) -> tuple[np.ndarray, np.ndarray] | None:
    """DEM samples ``(s, z)`` as a topography line. A NaN sample (nodata, or off the raster)
    takes the ``stations`` line's elevation at the same s: the DEM is used where it has data
    and the stations elsewhere, so no flat surface is invented past the raster's edge.
    Without a station line NaN samples are dropped. ``None`` when the DEM has no valid
    sample or fewer than two samples remain."""
    if dem is None:
        return None
    s, z = (np.asarray(a, dtype=float) for a in dem)
    keep = np.isfinite(s)
    s, z = s[keep], z[keep].copy()
    missing = ~np.isfinite(z)
    if missing.all():
        return None
    if stations is not None:
        z[missing] = np.interp(s[missing], *stations)
    else:
        s, z = s[~missing], z[~missing]
    if len(s) < 2:
        return None
    order = np.argsort(s, kind="stable")
    return s[order], z[order]
