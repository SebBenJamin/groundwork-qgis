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


def data_to_chainage(x_data: np.ndarray, station_set: StationSet, dataset: Dataset) -> np.ndarray:
    """Map data-file metres to profile chainage."""
    return (np.asarray(x_data, dtype=float) + station_set.metre0
            + dataset.reader_options.get("chainage_offset", 0.0))


def _as_xyz(xyz: np.ndarray) -> np.ndarray:
    a = np.asarray(xyz, dtype=float)
    if a.ndim != 2 or a.shape[1] not in (2, 3):
        raise ValueError("xyz must have shape (n, 2) or (n, 3)")
    if a.shape[1] == 2:
        a = np.column_stack([a, np.full(len(a), np.nan)])
    return a


def attach_station_set(profile: Profile, name: str, method: str, xyz: np.ndarray,
                       numbers: np.ndarray | None = None, tolerance: float = 5.0) -> StationSet:
    """Project stations onto ``profile``; warn about those further than ``tolerance`` off it."""
    xyz = _as_xyz(xyz)
    nums = np.arange(1, len(xyz) + 1) if numbers is None else np.asarray(numbers, dtype=int)
    if len(nums) != len(xyz):
        raise ValueError("numbers and xyz differ in length")
    s, off = profile.chainage.project(xyz[:, :2])
    warnings = [f"station {n}: {o:.1f} m off line"
                for n, o in zip(nums, off) if abs(o) > tolerance]
    metre0 = float(s[np.argmin(nums)]) if len(nums) else 0.0
    return StationSet(_new_id(), profile.id, name, method, nums, xyz, s, off, metre0, warnings)


def profile_from_stations(name: str, crs_authid: str, xyz: np.ndarray,
                          numbers: np.ndarray | None = None,
                          method: str = "ert") -> tuple[Profile, StationSet]:
    """Profile whose geometry is the station polyline (in input order)."""
    xyz = _as_xyz(xyz)
    profile = Profile(_new_id(), name, xyz[:, :2].copy(), crs_authid)
    return profile, attach_station_set(profile, name, method, xyz, numbers)


def profile_from_line(name: str, crs_authid: str, xy: np.ndarray, spacing: float,
                      method: str = "ert", first_number: int = 1) -> tuple[Profile, StationSet]:
    """Profile from a line with stations every ``spacing`` m from its start."""
    if spacing <= 0:
        raise ValueError("spacing must be positive")
    profile = Profile(_new_id(), name, np.asarray(xy, dtype=float).copy(), crs_authid)
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
