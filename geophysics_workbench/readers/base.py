"""Reader interface and result type (no QGIS/Qt)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

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
