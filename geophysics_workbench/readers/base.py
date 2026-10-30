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
#: z meanings a user can choose; the ``z_kind`` read option wins over the file's own hint
Z_CHOICES = ("elevation", "depth")


def chosen_z_kind(options: dict, guess: str) -> str:
    """The ``z_kind`` read option when it is a user choice (elevation/depth), else
    ``guess`` (what the file itself suggests)."""
    z = options.get("z_kind")
    return z if z in Z_CHOICES else guess


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


def _no_position(a: np.ndarray) -> np.ndarray:
    """True where a coordinate is missing: not finite, or the -9999 fill itself."""
    return ~np.isfinite(a) | (np.abs(a - FILL_VALUE) < 1e-6)


def mesh_from_resistivity_points(x, z, v, name: str,
                                 z_kind: str = "unknown") -> tuple[SectionMesh, int, str]:
    """Mesh of a cell-centre model: ``(mesh, n_masked, reconstruction)``.

    Checks positivity, then rebuilds the real cells when the centres form rows or columns
    (``SectionMesh.from_cell_centres``; ``reconstruction`` is "rows" or "columns"): a
    fill/NaN value keeps its cell, without a value. Otherwise fill/NaN points are dropped
    and the rest triangulated ("delaunay"). Points without a position are always dropped.
    ``z_kind`` "depth" puts the top edge of a row model on the surface. ValueErrors name
    the file."""
    x, z, v = (np.asarray(a, dtype=float) for a in (x, z, v))
    masked = fill_mask(v)
    unplaced = _no_position(x) | _no_position(z)
    n_masked = int((masked | unplaced).sum())
    if (masked | unplaced).all():
        raise ValueError(f"{name}: all {n_masked} values are fill values (-9999) or NaN; nothing to read")
    n_neg = int((v[~(masked | unplaced)] <= 0).sum())
    if n_neg:
        raise ValueError(f"{name}: {n_neg} resistivity value(s) are zero or negative (invalid data)")
    keep = ~unplaced
    v = np.where(masked, np.nan, v)[keep]
    try:
        mesh, kind = SectionMesh.from_cell_centres(x[keep], z[keep], v, z_kind=z_kind)
    except ValueError as exc:
        raise ValueError(f"{name}: {exc}") from None
    return mesh, n_masked, kind
