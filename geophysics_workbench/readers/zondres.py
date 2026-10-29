"""ZondRes2D model XYZ export reader (no QGIS/Qt).

Layout (from a real user file): header ``#X<TAB>Z<TAB>log_Rho<TAB>Rho<TAB>X,m<TAB>Y,m``;
column 0 = profile x, 1 = Z, 3 = resistivity (ohm.m; column 2 is its log10). Further
columns (world X/Y in metres) are ignored but flagged in the provenance.
Could not verify against Zond software documentation; based on the sample header only.
"""
from __future__ import annotations

from pathlib import Path

from ..core.section_mesh import SectionMesh
from .base import Reader, ReaderResult
from .textcols import read_columns, sniff_columns

_TEXT_SUFFIXES = {".dat", ".txt", ".xyz"}


class ZondResReader(Reader):
    name = "zondres_xyz"
    label = "ZondRes2D model (XYZ text)"

    def sniff(self, path: Path) -> bool:
        probe = sniff_columns(path)
        if probe is None:
            return False
        header, arr = probe
        if arr.shape[1] < 4:
            return False
        if header is not None and header[0].lstrip("#").strip().upper() == "X":
            return True
        return Path(path).suffix.lower() in _TEXT_SUFFIXES

    def read(self, path: Path, **options) -> ReaderResult:
        path = Path(path)
        header, arr = read_columns(path)
        if arr.shape[1] < 4:
            raise ValueError(f"{path.name}: expected at least 4 columns (x, z, log rho, rho), "
                             f"found {arr.shape[1]}")
        try:
            mesh = SectionMesh.from_points(arr[:, 0], arr[:, 1], arr[:, 3])
        except ValueError as exc:
            raise ValueError(f"{path.name}: {exc}") from None
        is_depth = header is not None and "depth" in " ".join(header).lower()
        return ReaderResult(mesh, "depth" if is_depth else "unknown", {
            "reader": self.name,
            "source_name": path.name,
            "has_world_xy": arr.shape[1] >= 6,
            "header": header,
            "n_points": int(arr.shape[0]),
        })
