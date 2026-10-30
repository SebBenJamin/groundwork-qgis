"""2D section meshes (triangles/quads in x, z) with vectorised internals (no QGIS/Qt)."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable

import numpy as np
from matplotlib.path import Path
from scipy.spatial import Delaunay

from .cell_centres import cell_boxes, quads


def _vertex_edge_scale(pts: np.ndarray, simplices: np.ndarray) -> np.ndarray:
    """Median length of the unique Delaunay edges incident to each vertex (vectorised)."""
    n = len(pts)
    e = np.sort(np.concatenate([simplices[:, [0, 1]], simplices[:, [1, 2]], simplices[:, [2, 0]]]).astype(np.int64), axis=1)
    e = np.unique(e[:, 0] * n + e[:, 1])
    a, b = e // n, e % n
    length = np.linalg.norm(pts[a] - pts[b], axis=1)
    vert = np.concatenate([a, b])
    ln = np.concatenate([length, length])
    order = np.lexsort((ln, vert))
    vert, ln = vert[order], ln[order]
    count = np.bincount(vert, minlength=n)
    start = np.cumsum(count) - count
    scale = np.full(n, np.inf)                       # vertices without edges are unused
    has = count > 0
    lo = start[has] + (count[has] - 1) // 2
    hi = start[has] + count[has] // 2
    scale[has] = 0.5 * (ln[lo] + ln[hi])
    return scale


SLIVER_ANGLE = 170.0    # degrees: a boundary triangle this obtuse is convex-hull filling


def _peel_hull_slivers(pts: np.ndarray, simplices: np.ndarray,
                       max_angle: float = SLIVER_ANGLE) -> np.ndarray:
    """Drop near-collinear triangles from the mesh boundary, repeatedly.

    Delaunay fills the convex hull: where the outer row of points is not convex (the deepest
    row under a hill, the top row in a hollow) it bridges the row with slivers whose three
    corners are almost in line. They are thin but lie outside the data, and the edge-length
    rule keeps them where the rows are coarse. Peeling only boundary triangles never opens
    holes inside the model; peeling repeats because removing one layer exposes the next."""
    p = pts[simplices]
    a, b = np.roll(p, -1, axis=1) - p, np.roll(p, 1, axis=1) - p
    norm = np.linalg.norm(a, axis=2) * np.linalg.norm(b, axis=2)
    with np.errstate(invalid="ignore", divide="ignore"):
        cos = (a * b).sum(axis=2) / norm
    # zero-length edges (duplicate points) count as slivers
    sliver = (np.nan_to_num(cos, nan=-1.0) <= np.cos(np.radians(max_angle))).any(axis=1)
    if not sliver.any():
        return simplices
    # neighbour across each edge (-1 on the boundary); an edge is shared by at most two
    n, t = len(pts), len(simplices)
    e = np.sort(np.stack([simplices[:, [0, 1]], simplices[:, [1, 2]], simplices[:, [2, 0]]],
                         axis=1).astype(np.int64), axis=2)
    key = (e[..., 0] * n + e[..., 1]).ravel()
    order = np.argsort(key, kind="stable")
    pair = np.nonzero(key[order][1:] == key[order][:-1])[0]
    first, second = order[pair], order[pair + 1]
    nb = np.full(3 * t, -1, dtype=np.int64)
    nb[first], nb[second] = second // 3, first // 3
    nb = nb.reshape(t, 3)
    keep = np.ones(t, dtype=bool)
    stack = list(np.nonzero(sliver & (nb < 0).any(axis=1))[0])
    while stack:                                   # visits slivers only
        i = stack.pop()
        if not keep[i]:
            continue
        keep[i] = False
        stack.extend(j for j in nb[i] if j >= 0 and keep[j] and sliver[j])
    return simplices[keep]


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
        """Delaunay mesh of scattered points. With an explicit max_edge, triangles with
        a longer edge are dropped. By default a local rule is used: a triangle is
        dropped when its longest edge exceeds 3 x the largest per-vertex scale of its
        corners (median length of the Delaunay edges at that vertex). Either way,
        near-collinear slivers on the boundary (convex-hull filling) are then peeled off."""
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
        p = pts[simplices]                                           # (t, 3, 2)
        edges = np.linalg.norm(p - np.roll(p, 1, axis=1), axis=2)    # (t, 3)
        longest = edges.max(axis=1)
        if max_edge is None:
            # local criterion: meshes that coarsen with depth keep their deep cells
            scale = _vertex_edge_scale(pts, simplices)
            keep = longest <= 3.0 * scale[simplices].max(axis=1)
        else:
            keep = longest <= max_edge
        simplices = _peel_hull_slivers(pts, simplices[keep])
        if len(simplices) == 0:
            raise ValueError("All triangles were filtered out; increase max_edge or check the points")
        vv = v[simplices]
        vals = np.exp(np.log(vv).mean(axis=1)) if quantity == "resistivity" else vv.mean(axis=1)
        cells = np.column_stack([simplices, np.full(len(simplices), -1)])
        return cls(pts, cells, vals, **kw)

    @classmethod
    def from_cell_centres(cls, x, z, v, z_kind: str = "unknown",
                          **kw) -> tuple["SectionMesh", str]:
        """Mesh of a model given as one value per cell centre: ``(mesh, reconstruction)``.

        Centres in rows of constant z (else columns of constant x) become their real
        rectangular cells (``core.cell_centres``); a nan value keeps its quad, without
        colour. For a depth model the top row's upper edge is the surface (depth 0).
        Otherwise the finite points are triangulated by ``from_points``."""
        x, z, v = (np.asarray(a, dtype=float).ravel() for a in (x, z, v))
        if not (x.size == z.size == v.size):
            raise ValueError("x, z and v must have the same length")
        found = cell_boxes(x, z, depth=(z_kind == "depth")) if x.size >= 4 else None
        if found is None:
            ok = np.isfinite(v)
            return cls.from_points(x[ok], z[ok], v[ok], **kw), "delaunay"
        kind, boxes = found
        good = v[np.isfinite(v)]
        if kw.get("quantity", "resistivity") == "resistivity" and not np.all(good > 0):
            raise ValueError("Resistivity values must be positive (the log-mean needs v > 0)")
        verts, cells = quads(boxes)
        return cls(verts, cells, v, **kw), kind

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

    def column_at(self, s: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """``(z_top, z_bottom, values)`` of every cell the vertical line x = s crosses,
        sorted top to bottom (empty arrays when there are none; nan cells are kept).
        Each cell's closed ring is cut with x = s; an edge lying on x = s hits at both ends."""
        c = self.cells
        ring = self.vertices[np.where(c >= 0, c, c[:, :1])]          # (m, 4, 2); triangle pad = vertex 0
        p0, p1 = ring, np.roll(ring, -1, axis=1)                     # edges i -> i+1, closing the ring
        dx = p1[..., 0] - p0[..., 0]
        d0, d1 = p0[..., 0] - s, p1[..., 0] - s
        tol = 1e-9 * max(1.0, abs(s))
        on = (np.abs(d0) <= tol) & (np.abs(d1) <= tol)               # edge lies on the line
        cross = (d0 * d1 <= 0) & ~on & (dx != 0)
        with np.errstate(invalid="ignore", divide="ignore"):
            zc = p0[..., 1] + (s - p0[..., 0]) / dx * (p1[..., 1] - p0[..., 1])
        z_lo = np.minimum(np.where(cross, zc, np.inf), np.where(on, np.minimum(p0[..., 1], p1[..., 1]), np.inf)).min(1)
        z_hi = np.maximum(np.where(cross, zc, -np.inf), np.where(on, np.maximum(p0[..., 1], p1[..., 1]), -np.inf)).max(1)
        hit = np.isfinite(z_lo) & np.isfinite(z_hi)
        order = np.argsort(-z_hi[hit], kind="stable")
        return z_hi[hit][order], z_lo[hit][order], self.values[hit][order]
