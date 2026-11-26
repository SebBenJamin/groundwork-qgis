"""What the header of a radar file says, shared by the GSSI and pulseEKKO readers (no QGIS/Qt).

Everything is in SI units: times in seconds, distances in metres, velocity in m/s. The readers
fill ``RadarInfo`` from the file alone; nothing here is estimated from the samples (time zero
from the data is ``core.trace_section.first_arrival``'s job). The trace positions a read asks
for (``position`` "file", "spacing" or "table") are worked out here for both readers.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..core.trace_section import C_M_PER_NS

#: how a read places the traces: the file's own distances, a spacing, or a coordinate file
POSITIONS = ("file", "spacing", "table")
#: the speed of light in m/s
LIGHT = C_M_PER_NS * 1e9
NANOSECOND = 1e-9


@dataclass
class RadarInfo:
    """What a radar file's headers say (no samples read)."""
    n_traces: int
    n_samples: int
    step: float                    # s between samples
    window: float                  # s, the recorded time range
    first: float                   # s, time of the first sample relative to the file's own zero
    time_zero: float | None        # s, only when the file states it
    velocity: float | None         # m/s, only from a dielectric the file states
    dielectric: float | None
    antenna: str                   # as the file names it, e.g. "270MHz"
    frequency_mhz: float | None
    trace_step: float | None       # m between traces, None without a distance from the file
    start: float                   # m, distance of the first trace
    length: float | None           # m, first to last trace
    positions: dict = field(default_factory=dict)  # as SegyInfo.positions; {} without map fixes
    notes: list = field(default_factory=list)      # plain sentences the user should know
    bits: int = 16                 # bits per stored sample
    #: the traces' map positions share positions or run back along the line
    #: (``track.repeats``); False while a reader reads no map positions
    repeats: bool = False


def velocity_from_dielectric(dielectric) -> float | None:
    """The radar velocity (m/s) of a relative dielectric constant: c / sqrt(eps); None when the
    value is missing, not finite or below 1."""
    try:
        eps = float(dielectric)
    except (TypeError, ValueError):
        return None
    if not (math.isfinite(eps) and eps >= 1.0):
        return None
    return LIGHT / math.sqrt(eps)


def no_wheel_message(name: str) -> str:
    return f"{name}: this file was recorded without a distance wheel; enter the trace spacing."


def _positive(value, what: str, name: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = float("nan")
    if not (math.isfinite(v) and v > 0):
        raise ValueError(f"{name}: the {what} must be greater than 0.")
    return v


def check_position(options: dict, name: str) -> str:
    """The ``position`` option (default "file"); ValueError for an unknown one."""
    position = options.get("position") or "file"
    if position not in POSITIONS:
        raise ValueError(f"{name}: unknown trace position {position!r}; expected one of "
                         f"{', '.join(POSITIONS)}")
    return position


def trace_x(path: Path, options: dict, file_x, n: int, provenance: dict) -> np.ndarray:
    """Distance of each of ``n`` traces as ``options`` ask: ``position`` "file" (``file_x``,
    the file's own distances, None when the file has none), "spacing" (``spacing`` m apart
    from 0) or "table" (the coordinate file, as the SEG-Y reader reads it; trace numbers
    1..n; ``xy_to_distance`` puts the positions on the line)."""
    name = path.name
    position = check_position(options, name)
    provenance["position"] = position
    if position == "file":
        if file_x is None:
            raise ValueError(no_wheel_message(name))
        return np.asarray(file_x, dtype=np.float64)
    if position == "spacing":
        return np.arange(n, dtype=np.float64) * _positive(options.get("spacing"),
                                                          "trace spacing", name)
    from .segy import SegyReader                 # the coordinate file is read as for SEG-Y
    return SegyReader._table_x(path, options, np.arange(1, n + 1), options.get("xy_to_distance"),
                               provenance)


def provenance_of(reader: str, name: str, info: RadarInfo) -> dict:
    """The provenance both radar readers record."""
    return {"reader": reader, "source_name": name, "n_traces": info.n_traces,
            "n_samples": info.n_samples, "step": info.step, "window": info.window,
            "antenna": info.antenna, "frequency_mhz": info.frequency_mhz,
            "trace_step": info.trace_step, "dielectric": info.dielectric,
            "time_zero_file": info.time_zero, "bits": info.bits, "notes": list(info.notes),
            "repeats": info.repeats}


def partner(path: Path, suffix: str) -> Path | None:
    """The file beside ``path`` with the same name and the suffix ``suffix`` (any case);
    None when there is none."""
    stem, want = path.stem.lower(), suffix.lower()
    exact = path.with_suffix(suffix)
    if exact.is_file():
        return exact
    try:
        for p in path.parent.iterdir():
            if p.stem.lower() == stem and p.suffix.lower() == want and p.is_file():
                return p
    except OSError:
        return None
    return None
