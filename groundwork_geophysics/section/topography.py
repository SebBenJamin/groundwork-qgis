"""The surface a section's depth models hang from. QGIS-free.

Every profile has exactly one (``Surface``), the first of: the station elevations or the DEM
(``Profile.metadata["topography"]`` holds the choice, "stations", the default, or "dem"); the
top edge of an elevation model; the top edge of a local-height model, its highest point at 0;
a flat line at 0. The last two are "local" (no real heights) until the profile has a
reference height, ``metadata["reference_height"] = {"s": chainage, "z": height}``, which
shifts them so the surface passes through it."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.model import StationSet

TOPOGRAPHY_SOURCES = ("stations", "dem")
SURFACE_KINDS = ("stations", "dem", "model", "local_model", "flat")
#: surface kinds without real heights: shifted by the reference height, local without one
LOCAL_KINDS = ("local_model", "flat")


@dataclass
class Surface:
    """A profile's surface: ``line`` (s ascending, z), what it comes from (``kind``, one of
    ``SURFACE_KINDS``) and, for a local kind, the ``shift`` already added to the line to
    meet the reference height (``referenced``)."""
    line: tuple[np.ndarray, np.ndarray]
    kind: str
    shift: float = 0.0
    referenced: bool = False

    def __post_init__(self):
        if self.kind not in SURFACE_KINDS:
            raise ValueError(f"surface kind must be one of {SURFACE_KINDS}, got {self.kind!r}")

    @property
    def has_reference(self) -> bool:
        return self.referenced

    @property
    def local(self) -> bool:
        """No real heights: a local model's top or the flat line, without a reference."""
        return self.kind in LOCAL_KINDS and not self.referenced


def reference_height(metadata: dict) -> tuple[float, float] | None:
    """(chainage, height) of the profile's reference height; None when unset or unusable."""
    ref = metadata.get("reference_height")
    try:
        s, z = float(ref["s"]), float(ref["z"])
    except (KeyError, TypeError, ValueError):
        return None
    return (s, z) if np.isfinite(s) and np.isfinite(z) else None


def local_surface(line: tuple[np.ndarray, np.ndarray], kind: str,
                  metadata: dict) -> Surface:
    """A ``LOCAL_KINDS`` surface, shifted to the profile's reference height when it has
    one (shift = reference z - line at reference s)."""
    ref = reference_height(metadata)
    if ref is None:
        return Surface(line, kind)
    shift = float(ref[1] - np.interp(ref[0], *line))
    return Surface((line[0], line[1] + shift), kind, shift, True)


def flat_line(length: float) -> tuple[np.ndarray, np.ndarray]:
    """0 from chainage 0 to ``length``."""
    return np.array([0.0, max(float(length), 0.0)]), np.zeros(2)


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


def station_labels(numbers: np.ndarray) -> list[str]:
    """Label the first station and every station whose number is a multiple of 10."""
    numbers = np.asarray(numbers, dtype=int)
    first = int(numbers.min()) if len(numbers) else None
    return [str(n) if (n % 10 == 0 or n == first) else "" for n in numbers.tolist()]


def station_marks(sets: list[StationSet], electrodes=None
                  ) -> tuple[list[tuple[float, str]], np.ndarray]:
    """The station ticks of a section, from ``topo_set(sets)`` (else the first set):
    ``[(chainage, label), ...]`` and the measured elevations aligned with them (nan where
    a station has none). The ticks are drawn at the measured heights whatever surface the
    models hang from, so a DEM that disagrees with them shows (spec 4.2). Without a
    station set, the derived ``electrodes`` (``core.layout.Electrodes``), with no heights."""
    st = topo_set(sets) or (sets[0] if sets else None)
    if st is None:
        if electrodes is None:
            return [], np.empty(0)
        s = np.asarray(electrodes.chainage, dtype=float)
        return (list(zip(s.tolist(), station_labels(electrodes.numbers))),
                np.full(len(s), np.nan))
    z = (st.xyz[:, 2].astype(float) if len(st.xyz) == len(st.chainage)
         else np.full(len(st.chainage), np.nan))
    return list(zip(st.chainage.astype(float).tolist(), station_labels(st.numbers))), z.copy()


def measured_line(stations: list[tuple[float, str]], heights: np.ndarray | None
                  ) -> tuple[np.ndarray, np.ndarray] | None:
    """(s, z) of the ``stations`` (as in the snapshot) that have a measured height,
    ascending; None with fewer than two."""
    if heights is None or len(heights) != len(stations):
        return None
    s = np.array([st[0] for st in stations], dtype=float)
    z = np.asarray(heights, dtype=float)
    ok = np.isfinite(s) & np.isfinite(z)
    if ok.sum() < 2:
        return None
    order = np.argsort(s[ok], kind="stable")
    return s[ok][order], z[ok][order]


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
