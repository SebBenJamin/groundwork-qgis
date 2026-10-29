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
