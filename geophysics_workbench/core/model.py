"""Profile, station set and dataset model. QGIS-free; pure NumPy/stdlib."""
from __future__ import annotations

import hashlib
import os
import uuid
from dataclasses import dataclass, field

import numpy as np

from .chainage import Chainage


def _new_id() -> str:
    return uuid.uuid4().hex


@dataclass
class Profile:
    id: str
    name: str
    xy: np.ndarray
    crs_authid: str
    metadata: dict = field(default_factory=dict)

    @property
    def chainage(self) -> Chainage:
        return Chainage(self.xy)

    def reversed(self) -> "Profile":
        return Profile(self.id, self.name, np.asarray(self.xy, dtype=float)[::-1].copy(),
                       self.crs_authid, dict(self.metadata))


@dataclass
class StationSet:
    id: str
    profile_id: str
    name: str
    method: str
    numbers: np.ndarray
    xyz: np.ndarray
    chainage: np.ndarray
    offset: np.ndarray
    metre0: float
    warnings: list[str] = field(default_factory=list)
    #: each station's distance in the model file's own in-line metres; NaN where unknown
    inline: np.ndarray | None = None

    def __post_init__(self):
        n = len(self.numbers)
        if self.inline is None:
            self.inline = np.full(n, np.nan)
        else:
            self.inline = np.asarray(self.inline, dtype=float)
            if self.inline.shape != (n,):
                raise ValueError(f"inline has {self.inline.size} values for {n} stations")

    @property
    def direction(self) -> int:
        """+1 when station numbers grow with chainage, -1 when they are numbered against
        the profile direction (station 1 at the far end). Derived, not stored."""
        return numbering_direction(self.numbers, self.chainage)


def numbering_direction(numbers: np.ndarray, chainage: np.ndarray) -> int:
    """Sign of chainage against station number (covariance); +1 when undetermined."""
    n = np.asarray(numbers, dtype=float)
    s = np.asarray(chainage, dtype=float)
    ok = np.isfinite(n) & np.isfinite(s)
    if ok.sum() < 2:
        return 1
    n, s = n[ok], s[ok]
    return -1 if float(np.sum((n - n.mean()) * (s - s.mean()))) < 0 else 1


@dataclass
class Dataset:
    id: str
    profile_id: str
    station_set_id: str
    kind: str
    source_path: str
    source_mtime: float
    source_sha1: str
    reader: str
    reader_options: dict
    provenance: dict
    version: int = 1
    parent_id: str | None = None
    quantity: str = "resistivity"
    unit: str = "ohm.m"
    name: str = ""


def x_to_chainage(x_data: np.ndarray, station_set: StationSet,
                  chainage_offset: float = 0.0) -> np.ndarray:
    """Map data-file metres to profile chainage: ``metre0 + direction * (x + offset)``.
    Data metres count from station 1 in the numbering direction, so a station set
    numbered against the profile direction mirrors the model."""
    return (station_set.metre0
            + station_set.direction * (np.asarray(x_data, dtype=float) + chainage_offset))


def data_to_chainage(x_data: np.ndarray, station_set: StationSet, dataset: Dataset) -> np.ndarray:
    """``x_to_chainage`` with the dataset's ``chainage_offset`` reader option."""
    return x_to_chainage(x_data, station_set,
                         dataset.reader_options.get("chainage_offset", 0.0))


def _as_xyz(xyz: np.ndarray) -> np.ndarray:
    a = np.asarray(xyz, dtype=float)
    if a.ndim != 2 or a.shape[1] not in (2, 3):
        raise ValueError("xyz must have shape (n, 2) or (n, 3)")
    if a.shape[1] == 2:
        a = np.column_stack([a, np.full(len(a), np.nan)])
    return a


def attach_station_set(profile: Profile, name: str, method: str, xyz: np.ndarray,
                       numbers: np.ndarray | None = None, tolerance: float = 5.0,
                       inline: np.ndarray | None = None) -> StationSet:
    """Project stations onto ``profile``; warn about those further than ``tolerance`` off it.
    ``inline``: each station's distance in the model file's own metres (NaN where unknown)."""
    xyz = _as_xyz(xyz)
    nums = np.arange(1, len(xyz) + 1) if numbers is None else np.asarray(numbers, dtype=int)
    if len(nums) != len(xyz):
        raise ValueError("numbers and xyz differ in length")
    s, off = profile.chainage.project(xyz[:, :2])
    warnings = [f"station {n}: {o:.1f} m off line"
                for n, o in zip(nums, off) if abs(o) > tolerance]
    metre0 = float(s[np.argmin(nums)]) if len(nums) else 0.0
    return StationSet(_new_id(), profile.id, name, method, nums, xyz, s, off, metre0, warnings,
                      inline)


def profile_from_stations(name: str, crs_authid: str, xyz: np.ndarray,
                          numbers: np.ndarray | None = None,
                          method: str = "ert") -> tuple[Profile, StationSet]:
    """Profile whose geometry is the station polyline, in station-number order when
    ``numbers`` are given (input order otherwise)."""
    xyz = _as_xyz(xyz)
    if numbers is not None:
        numbers = np.asarray(numbers, dtype=int)
        if len(numbers) != len(xyz):
            raise ValueError("numbers and xyz differ in length")
        order = np.argsort(numbers, kind="stable")
        xyz, numbers = xyz[order], numbers[order]
    profile = Profile(_new_id(), name, xyz[:, :2].copy(), crs_authid)
    return profile, attach_station_set(profile, name, method, xyz, numbers)


def profile_from_line(name: str, crs_authid: str, xy: np.ndarray, spacing: float,
                      method: str = "ert", first_number: int = 1,
                      from_end: bool = False) -> tuple[Profile, StationSet]:
    """Profile from a line with stations every ``spacing`` m from its start. ``from_end``
    numbers the stations from the line's last vertex: the profile is ``reversed()``."""
    if spacing <= 0:
        raise ValueError("spacing must be positive")
    profile = Profile(_new_id(), name, np.asarray(xy, dtype=float).copy(), crs_authid)
    if from_end:
        profile = profile.reversed()
    ch = profile.chainage
    s = np.arange(0.0, ch.length + 1e-9, spacing)
    pts = ch.to_xy(s)
    xyz = np.column_stack([pts, np.full(len(s), np.nan)])
    numbers = first_number + np.arange(len(s))
    return profile, attach_station_set(profile, name, method, xyz, numbers)


def file_fingerprint(path: str) -> tuple[float, str]:
    """(mtime, sha1 hex) of a file."""
    sha = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha.update(chunk)
    return os.stat(path).st_mtime, sha.hexdigest()
