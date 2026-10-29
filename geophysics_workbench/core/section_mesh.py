"""2D section meshes (triangles/quads in x, z) with vectorised internals (no QGIS/Qt)."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np
from matplotlib.path import Path
from scipy.spatial import Delaunay, cKDTree


@dataclass
class SectionMesh:
    vertices: np.ndarray            # (n, 2) [x, z]
    cells: np.ndarray               # (m, 4) int, -1 padding in column 3 for triangles
    values: np.ndarray              # (m,)
    quantity: str = "resistivity"
    unit: str = "ohm.m"
    _bbox: np.ndarray | None = field(default=None, init=False, repr=False, compare=False)

    def __post_init__(self):
        self.vertices = np.asarray(self.vertices, dtype=float)
        self.cells = np.asarray(self.cells, dtype=int)
        self.values = np.asarray(self.values, dtype=float)
        if self.vertices.ndim != 2 or self.vertices.shape[1] != 2:
            raise ValueError(f"vertices must have shape (n, 2), got {self.vertices.shape}")
        if self.cells.ndim != 2 or self.cells.shape[1] != 4:
            raise ValueError(f"cells must have shape (m, 4), got {self.cells.shape}")
        if self.values.shape != (self.cells.shape[0],):
            raise ValueError(f"values must have shape ({self.cells.shape[0]},), got {self.values.shape}")

    # -- construction ---------------------------------------------------
    @classmethod
    def from_points(cls, x, z, v, max_edge: float | None = None, **kw) -> "SectionMesh":
        """Delaunay mesh of scattered points; triangles with an edge longer than
        max_edge (default 3 x median nearest-neighbour distance) are dropped."""
        x, z, v = (np.asarray(a, dtype=float).ravel() for a in (x, z, v))
        if not (x.size == z.size == v.size):
            raise ValueError("x, z and v must have the same length")
        if x.size < 3:
            raise ValueError("Need at least 3 points to build a mesh")
        pts = np.column_stack([x, z])
        quantity = kw.get("quantity", "resistivity")
        if quantity == "resistivity" and not np.all(v > 0):
            raise ValueError("Resistivity values must be positive (the log-mean needs v > 0)")
        try:
            simplices = Delaunay(pts).simplices
        except Exception as exc:  # scipy QhullError for collinear/degenerate input
            raise ValueError("Points are collinear or degenerate; cannot triangulate") from exc
        if max_edge is None:
            d, _ = cKDTree(pts).query(pts, k=2)
            max_edge = 3.0 * float(np.median(d[:, 1]))
        p = pts[simplices]                                           # (t, 3, 2)
        edges = np.linalg.norm(p - np.roll(p, 1, axis=1), axis=2)    # (t, 3)
        simplices = simplices[edges.max(axis=1) <= max_edge]
        vv = v[simplices]
        vals = np.exp(np.log(vv).mean(axis=1)) if quantity == "resistivity" else vv.mean(axis=1)
        cells = np.column_stack([simplices, np.full(len(simplices), -1)])
        return cls(pts, cells, vals, **kw)

    # -- transforms -----------------------------------------------------
    def with_x(self, fn: Callable[[np.ndarray], np.ndarray]) -> "SectionMesh":
        verts = self.vertices.copy()
        verts[:, 0] = fn(verts[:, 0])
        return replace(self, vertices=verts)

    def depth_to_elevation(self, surface_s, surface_z) -> "SectionMesh":
        """z_elev = interp(x, surface_s, surface_z) - |z|. Beyond the ends of the
        surface profile np.interp clamps to the end elevations."""
        verts = self.vertices.copy()
        verts[:, 1] = np.interp(verts[:, 0], surface_s, surface_z) - np.abs(verts[:, 1])
        return replace(self, vertices=verts)

    # -- queries --------------------------------------------------------
    def bounds(self) -> tuple[float, float, float, float]:
        used = self.vertices[np.unique(self.cells[self.cells >= 0])]
        return (float(used[:, 0].min()), float(used[:, 0].max()),
                float(used[:, 1].min()), float(used[:, 1].max()))

    def _cell_bboxes(self) -> np.ndarray:
        if self._bbox is None:
            c = self.cells
            xy = self.vertices[np.where(c >= 0, c, c[:, :1])]        # pad -1 with first vertex
            self._bbox = np.column_stack([xy[..., 0].min(1), xy[..., 0].max(1),
                                          xy[..., 1].min(1), xy[..., 1].max(1)])
        return self._bbox

    def value_at(self, x: float, z: float) -> float:
        """Value of the cell containing (x, z), nan outside. Points on a shared edge
        may return either neighbour."""
        b = self._cell_bboxes()
        cand = np.nonzero((b[:, 0] <= x) & (x <= b[:, 1]) & (b[:, 2] <= z) & (z <= b[:, 3]))[0]
        tol = 1e-9 * max(1.0, abs(x), abs(z))
        for i in cand:
            row = self.cells[i]
            path = Path(self.vertices[row[row >= 0]])
            # the sign of `radius` that grows the polygon depends on its winding
            if path.contains_point((x, z)) or path.contains_point((x, z), radius=tol) \
                    or path.contains_point((x, z), radius=-tol):
                return float(self.values[i])
        return float("nan")

    def polygons(self) -> list[np.ndarray]:
        """Per-cell vertex arrays (k, 2), k = 3 or 4, in cell order."""
        tri = self.cells[:, 3] < 0
        out: list = [None] * len(self.cells)
        for idx, polys in ((np.nonzero(~tri)[0], self.vertices[self.cells[~tri]]),
                           (np.nonzero(tri)[0], self.vertices[self.cells[tri][:, :3]])):
            for i, poly in zip(idx, polys):
                out[i] = poly
        return out
