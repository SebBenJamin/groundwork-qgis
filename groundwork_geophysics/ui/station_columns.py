"""Station-file columns for the new-profile dialog: turning the chosen columns into station
coordinates and numbers (the column-role guesses are in ``core.roles``). No widgets."""
from __future__ import annotations

import numpy as np

# the column-role guesses live in core.roles; re-exported for the dialogs and tests
from ..core.roles import NONE, guess_columns, looks_like_degrees  # noqa: F401


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
                         f"Coordinates must be in {crs_authid}, the Groundwork project's "
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
