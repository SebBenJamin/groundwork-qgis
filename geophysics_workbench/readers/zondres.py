"""ZondRes2D model XYZ export reader (no QGIS/Qt).

Layout (from a real user file): header ``#X<TAB>Z<TAB>log_Rho<TAB>Rho<TAB>X,m<TAB>Y,m``;
column 0 = profile x, 1 = Z, 3 = resistivity (ohm.m; column 2 is its log10). Further
columns (world X/Y in metres) are ignored but flagged in the provenance. Detected by
content: column 2 is log10 of column 3 (R2 files have it the other way round).
Could not verify against Zond software documentation; based on the sample header only.
"""
from __future__ import annotations

from pathlib import Path

from .base import Reader, ReaderResult, is_log10_pair, mesh_from_resistivity_points
from .textcols import read_columns, sniff_columns


class ZondResReader(Reader):
    name = "zondres_xyz"
    label = "ZondRes2D model (XYZ text)"

    def sniff(self, path: Path) -> bool:
        probe = sniff_columns(path)
        if probe is None:
            return False
        _header, arr = probe
        return arr.shape[1] >= 4 and is_log10_pair(arr, 3, 2)

    def read(self, path: Path, **options) -> ReaderResult:
        path = Path(path)
        header, arr = read_columns(path)
        if arr.shape[1] < 4:
            raise ValueError(f"{path.name}: expected at least 4 columns (x, z, log rho, rho), "
                             f"found {arr.shape[1]}")
        mesh, n_masked = mesh_from_resistivity_points(arr[:, 0], arr[:, 1], arr[:, 3], path.name)
        is_depth = header is not None and "depth" in " ".join(header).lower()
        return ReaderResult(mesh, "depth" if is_depth else "unknown", {
            "reader": self.name,
            "source_name": path.name,
            "has_world_xy": arr.shape[1] >= 6,
            "header": header,
            "n_points": int(arr.shape[0]),
            "n_masked": n_masked,
        })
