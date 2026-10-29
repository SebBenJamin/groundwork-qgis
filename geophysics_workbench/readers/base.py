"""Reader interface and result type (no QGIS/Qt)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..core.section_mesh import SectionMesh

Z_KINDS = ("elevation", "depth", "unknown")


@dataclass
class ReaderResult:
    mesh: SectionMesh
    z_kind: str                      # "elevation" | "depth" | "unknown"
    provenance: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.z_kind not in Z_KINDS:
            raise ValueError(f"z_kind must be one of {Z_KINDS}, got {self.z_kind!r}")


class Reader:
    """Turns an inversion-software output file into a SectionMesh in profile space."""

    name: str = ""
    label: str = ""

    def sniff(self, path: Path) -> bool:
        """Cheap check (reads at most a few KB) whether this reader likely handles the file.
        Must never raise."""
        raise NotImplementedError

    def read(self, path: Path, **options) -> ReaderResult:
        """Read the file. Raises ValueError with a readable message for unusable content."""
        raise NotImplementedError


FILL_VALUE = -9999.0


def fill_mask(v) -> np.ndarray:
    """True where a value is a ResIPy-style fill (-9999) or not finite."""
    v = np.asarray(v, dtype=float)
    return ~np.isfinite(v) | (v <= FILL_VALUE + 1e-6)


def is_log10_pair(arr: np.ndarray, value_col: int, log_col: int, tol: float = 0.02) -> bool:
    """True when column ``log_col`` is log10 of column ``value_col`` in every row with a
    usable (positive, non-fill) value, and there is at least one such row. Used to tell
    R2 (x z rho log10) from ZondRes2D (x z log10 rho) text by content."""
    a = np.asarray(arr, dtype=float)
    if a.ndim != 2 or a.shape[1] <= max(value_col, log_col):
        return False
    v, lg = a[:, value_col], a[:, log_col]
    ok = ~fill_mask(v) & (v > 0) & np.isfinite(lg)
    if not ok.any():
        return False
    return bool(np.all(np.abs(np.log10(v[ok]) - lg[ok]) <= tol))


def mesh_from_resistivity_points(x, z, v, name: str) -> tuple[SectionMesh, int]:
    """Drop fill/NaN points, check positivity, triangulate. Returns (mesh, n_masked).
    ValueErrors name the file."""
    x, z, v = (np.asarray(a, dtype=float) for a in (x, z, v))
    bad = fill_mask(v) | ~np.isfinite(x) | ~np.isfinite(z)
    n_masked = int(bad.sum())
    if bad.all():
        raise ValueError(f"{name}: all {n_masked} values are fill values (-9999) or NaN; nothing to read")
    x, z, v = x[~bad], z[~bad], v[~bad]
    n_neg = int((v <= 0).sum())
    if n_neg:
        raise ValueError(f"{name}: {n_neg} resistivity value(s) are zero or negative (invalid data)")
    try:
        return SectionMesh.from_points(x, z, v), n_masked
    except ValueError as exc:
        raise ValueError(f"{name}: {exc}") from None
