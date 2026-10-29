"""Station-file columns for the new-profile dialog: guessing the column roles and turning
the chosen columns into station coordinates and numbers. No widgets."""
from __future__ import annotations

import re

import numpy as np

NONE = -1                                   # "(none)" entry of the optional column combos
_HEADER_NAMES = {
    "number": {"nr", "no", "num", "number", "electrode", "elektrode", "station", "id"},
    "x": {"x", "east", "easting", "rechts", "rechtswert", "e"},
    "y": {"y", "north", "northing", "hoch", "hochwert", "n"},
    "z": {"z", "elev", "elevation", "height", "höhe", "hoehe", "alt", "altitude", "h"},
}


def guess_columns(header: list[str] | None, ncols: int) -> dict[str, int]:
    """Column index per role (number, x, y, z) from header names, else by position.
    A positional guess never reuses a column that a header name claimed for another role."""
    if ncols >= 4:
        guess = {"number": 0, "x": 1, "y": 2, "z": 3}
    else:
        guess = {"number": NONE, "x": 0, "y": min(1, ncols - 1), "z": 2 if ncols == 3 else NONE}
    if header:
        matched = {}
        for i, token in enumerate(header):
            word = re.sub(r"[^\wäöüß]", "", token.lower())
            for role, names in _HEADER_NAMES.items():
                if word in names and role not in matched:
                    matched[role] = i
        claimed = set(matched.values())
        for role in guess:
            if role in matched:
                guess[role] = matched[role]
            elif guess[role] in claimed:
                guess[role] = NONE
    return guess


def looks_like_degrees(xy: np.ndarray) -> bool:
    """Longitude/latitude rather than projected metres: every |x| <= 180, every |y| <= 90
    and the whole set spans less than 1 unit."""
    xy = np.asarray(xy, dtype=float)[:, :2]
    if not len(xy) or not np.all(np.isfinite(xy)):
        return False
    return bool(np.all(np.abs(xy[:, 0]) <= 180) and np.all(np.abs(xy[:, 1]) <= 90)
                and np.ptp(xy, axis=0).max() < 1.0)


def _chosen(col) -> bool:
    return col not in (None, NONE)


def stations_from_columns(arr: np.ndarray, cx, cy, cn, cz,
                          crs_authid: str) -> tuple[np.ndarray, np.ndarray | None]:
    """(xyz, numbers or None) from the chosen columns of a station table, rows sorted by
    number when a number column is chosen. Raises ValueError with a message for the user."""
    if cx is None or cy is None or cx == cy:
        raise ValueError("Choose two different columns for X and Y")
    for label, col in (("electrode number", cn), ("Z", cz)):
        if _chosen(col) and col in (cx, cy):
            raise ValueError(f"The {label} column cannot also be the X or Y column")
    if _chosen(cn) and cn == cz:
        raise ValueError("The electrode number column cannot also be the Z column")
    z = arr[:, cz] if _chosen(cz) else np.full(len(arr), np.nan)
    xyz = np.column_stack([arr[:, cx], arr[:, cy], z])
    if looks_like_degrees(xyz):
        raise ValueError("The station coordinates look like longitude/latitude in degrees. "
                         f"Coordinates must be in {crs_authid}, the workbench project's "
                         "CRS; convert the file first (e.g. in QGIS).")
    numbers = None
    if _chosen(cn):
        numbers = arr[:, cn]
        if not np.all(np.isfinite(numbers)) or np.any(numbers != np.round(numbers)):
            raise ValueError("Electrode numbers must be whole numbers")
        numbers = numbers.astype(int)
        order = np.argsort(numbers, kind="stable")      # the line follows the numbering
        xyz, numbers = xyz[order], numbers[order]
    if len(xyz) < 2:
        raise ValueError("A profile needs at least 2 stations")
    return xyz, numbers
