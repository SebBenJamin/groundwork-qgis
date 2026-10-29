"""R2 / ResIPy ``f00N_res.dat`` reader (no QGIS/Qt).

Layout verified against ResIPy source (gitlab.com/hkex/resipy, src/resipy/meshTools.py,
Mesh.writeAttr): for 2D meshes, tab-separated, no header, one row per element centroid:
``x  z  value  log10(value)`` (z = elevation); 3D meshes write ``x y z value log10`` (five
columns), which this reader rejects. File name pattern ``f\\d{3}_res.dat`` (R2 iteration
output), N gives the iteration / file index.
"""
from __future__ import annotations

import re
from pathlib import Path

from .base import Reader, ReaderResult, mesh_from_resistivity_points
from .textcols import read_columns

_NAME = re.compile(r"f(\d{3})_res\.dat", re.IGNORECASE)


class R2ResReader(Reader):
    name = "r2_res_dat"
    label = "R2 / ResIPy resistivity (f00N_res.dat)"

    def sniff(self, path: Path) -> bool:
        return _NAME.fullmatch(Path(path).name) is not None

    def read(self, path: Path, **options) -> ReaderResult:
        path = Path(path)
        _header, arr = read_columns(path)
        if arr.shape[1] == 5:
            raise ValueError(f"{path.name}: 5 columns look like a 3D R2 result (x y z rho log rho); "
                             "only 2D sections (4 columns) are supported")
        if arr.shape[1] != 4:
            raise ValueError(f"{path.name}: expected 4 columns (x, z, resistivity, log10), "
                             f"found {arr.shape[1]}")
        mesh, n_masked = mesh_from_resistivity_points(arr[:, 0], arr[:, 1], arr[:, 2], path.name)
        m = _NAME.fullmatch(path.name)
        index = int(m.group(1)) if m else None
        return ReaderResult(mesh, "elevation", {
            "reader": self.name,
            "source_name": path.name,
            "file_index": index,
            "iteration": index,
            "n_points": int(arr.shape[0]),
            "n_masked": n_masked,
        })
