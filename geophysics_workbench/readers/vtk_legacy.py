"""Legacy ASCII VTK unstructured-grid reader (ResIPy, pyGIMLi exports; no QGIS/Qt).

Layout verified against ResIPy source (gitlab.com/hkex/resipy, src/resipy/meshTools.py,
Mesh.vtk): ``# vtk DataFile Version 3.0``, title, ``ASCII``, ``DATASET UNSTRUCTURED_GRID``,
``POINTS n double`` (x y z per line), ``CELLS n size`` (``k i0 .. ik-1`` per line),
``CELL_TYPES n`` (ALL types on ONE line, space separated), ``CELL_DATA n`` with
``SCALARS name double 1`` + ``LOOKUP_TABLE default`` + all values on ONE line, then a
``POINT_DATA`` section. Nodes may be tab/space separated and NaN is replaced by -9999.
Because layouts differ in line breaks, the body is parsed as a token stream. Only
cell types 5 (triangle) and 9 (quad) are supported; the VTK 5.1 OFFSETS/CONNECTIVITY
cell layout is not.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..core.section_mesh import SectionMesh
from .base import Reader, ReaderResult, fill_mask
from .textcols import decode_bytes

_TRIANGLE, _QUAD = 5, 9


class _Tokens:
    def __init__(self, tokens: list[str], name: str):
        self.t, self.i, self.name = tokens, 0, name

    def peek(self) -> str | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def next(self) -> str:
        if self.i >= len(self.t):
            raise ValueError(f"{self.name}: unexpected end of file")
        self.i += 1
        return self.t[self.i - 1]

    def expect(self, word: str) -> None:
        got = self.next()
        if got.upper() != word:
            raise ValueError(f"{self.name}: expected {word}, found {got!r}")

    def floats(self, n: int) -> np.ndarray:
        chunk = self.t[self.i:self.i + n]
        if len(chunk) < n:
            raise ValueError(f"{self.name}: unexpected end of file")
        self.i += n
        try:
            return np.array(chunk, dtype=float)
        except ValueError:
            raise ValueError(f"{self.name}: non-numeric value in data block") from None


class VtkLegacyReader(Reader):
    name = "vtk_legacy"
    label = "Legacy VTK unstructured grid (ASCII)"

    def sniff(self, path: Path) -> bool:
        try:
            with open(path, "rb") as fh:
                head = fh.read(256)
            return decode_bytes(head).lstrip().lower().startswith("# vtk datafile")
        except Exception:
            return False

    def read(self, path: Path, **options) -> ReaderResult:
        path = Path(path)
        text = decode_bytes(path.read_bytes())
        lines = text.split("\n", 3)
        if len(lines) < 4 or not lines[0].strip().lower().startswith("# vtk datafile"):
            raise ValueError(f"{path.name}: not a legacy VTK file (missing '# vtk DataFile' header)")
        if lines[2].strip().upper() != "ASCII":
            raise ValueError(f"{path.name}: only ASCII legacy VTK files are supported "
                             f"(found {lines[2].strip()!r})")
        tk = _Tokens(lines[3].split(), path.name)
        tk.expect("DATASET")
        kind = tk.next().upper()
        if kind != "UNSTRUCTURED_GRID":
            raise ValueError(f"{path.name}: dataset {kind} is not supported (need UNSTRUCTURED_GRID)")

        points = cells = types = None
        arrays: dict[str, np.ndarray] = {}
        while tk.peek() is not None:
            word = tk.next().upper()
            if word == "POINTS":
                n = int(tk.next()); tk.next()
                points = tk.floats(3 * n).reshape(n, 3)
            elif word == "CELLS":
                n, size = int(tk.next()), int(tk.next())
                flat = tk.floats(size).astype(int)
                cells, pos = [], 0
                for _ in range(n):
                    k = int(flat[pos]); cells.append(flat[pos + 1:pos + 1 + k]); pos += k + 1
            elif word == "CELL_TYPES":
                types = tk.floats(int(tk.next())).astype(int)
            elif word == "CELL_DATA":
                n_data = int(tk.next())
                self._read_cell_data(tk, n_data, arrays)
                break                                   # POINT_DATA etc. is not needed
        if points is None or cells is None or types is None:
            raise ValueError(f"{path.name}: POINTS, CELLS and CELL_TYPES sections are required")
        if len(types) != len(cells):
            raise ValueError(f"{path.name}: {len(cells)} cells but {len(types)} cell types")
        for t in sorted(set(types.tolist())):
            if t not in (_TRIANGLE, _QUAD):
                raise ValueError(f"{path.name}: unsupported VTK cell type {t} "
                                 "(only 5=triangle and 9=quad are supported)")
        conn = np.full((len(cells), 4), -1, dtype=int)
        for c, (cell, t) in enumerate(zip(cells, types)):
            need = 3 if t == _TRIANGLE else 4
            if len(cell) != need:
                raise ValueError(f"{path.name}: cell {c} of type {t} has {len(cell)} vertices")
            conn[c, :need] = cell
        if conn.size and (conn.max() >= len(points)):
            raise ValueError(f"{path.name}: cell refers to a point beyond the {len(points)} points")

        if not arrays:
            raise ValueError(f"{path.name}: no CELL_DATA scalar arrays found")
        names = list(arrays)
        want = options.get("array")
        if want is not None:
            if want not in arrays:
                raise ValueError(f"{path.name}: array {want!r} not found; available: {', '.join(names)}")
            chosen = want
        else:
            chosen = next((n for n in names if "resist" in n.lower()), names[0])
        values = arrays[chosen]
        if len(values) != len(cells):
            raise ValueError(f"{path.name}: array {chosen!r} has {len(values)} values for {len(cells)} cells")

        masked = fill_mask(values)                 # -9999 fill / NaN: keep the cell, value NaN
        values = np.where(masked, np.nan, values)
        axes = options.get("axes") or self._auto_axes(points, path.name)
        i, j = axes
        verts = points[:, [i, j]]
        is_res = "resist" in chosen.lower()
        mesh = SectionMesh(verts, conn, values,
                           quantity="resistivity" if is_res else chosen,
                           unit="ohm.m" if is_res else "")
        return ReaderResult(mesh, "elevation", {
            "reader": self.name,
            "source_name": path.name,
            "array_names": names,
            "array": chosen,
            "axes": (int(i), int(j)),
            "n_cells": int(len(cells)),
            "n_masked": int(masked.sum()),
        })

    @staticmethod
    def _read_cell_data(tk: _Tokens, n: int, arrays: dict) -> None:
        while tk.peek() is not None:
            word = tk.peek().upper()
            if word == "SCALARS":
                tk.next()
                name = tk.next(); tk.next()
                ncomp = 1
                if tk.peek() is not None and tk.peek().upper() != "LOOKUP_TABLE":
                    ncomp = int(tk.next())
                tk.expect("LOOKUP_TABLE"); tk.next()
                data = tk.floats(n * ncomp)
                if ncomp == 1:
                    arrays[name] = data
            elif word == "FIELD":
                tk.next(); tk.next()
                for _ in range(int(tk.next())):
                    tk.next()
                    ncomp, ntup = int(tk.next()), int(tk.next()); tk.next()
                    tk.floats(ncomp * ntup)
            else:                                        # POINT_DATA, VECTORS, ... : stop
                return

    @staticmethod
    def _auto_axes(points: np.ndarray, name: str) -> tuple[int, int]:
        rng = np.ptp(points, axis=0)
        used = [a for a in range(3) if rng[a] > 1e-9 * max(1.0, rng.max())]
        if len(used) != 2:
            raise ValueError(f"{name}: expected a 2D section (exactly two point axes with extent), "
                             f"found {len(used)}; pass axes=(i, j) to choose")
        return used[0], used[1]
