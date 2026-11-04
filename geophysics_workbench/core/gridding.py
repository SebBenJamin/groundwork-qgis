"""Gridded display of section models: smooth fields, contour lines, coverage fade (no QGIS)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def default_threshold(coverage) -> float:
    """Default coverage threshold: the 10th percentile of the finite values (0.0 if none)."""
    c = np.asarray(coverage, float)
    c = c[np.isfinite(c)]
    return float(np.percentile(c, 10)) if c.size else 0.0


@dataclass
class Grid:
    s: np.ndarray           # (nx,) chainage of the grid columns
    z: np.ndarray           # (nz,) elevation of the grid rows, ascending
    values: np.ndarray      # (nz, nx) model values, nan where nothing is drawn
    cell: np.ndarray        # (nz, nx) mesh cell under each node, -1 outside the mesh


def _longest_edges(mesh) -> np.ndarray:
    """Longest edge of each mesh cell (triangles have -1 in column 3)."""
    v, c = mesh.vertices, mesh.cells
    k = np.where(c[:, 3] >= 0, 4, 3)
    longest = np.zeros(len(c))
    for j in range(4):
        valid = j < k
        nxt = np.where(j + 1 < k, c[:, (j + 1) % 4], c[:, 0])
        d = np.hypot(*(v[nxt[valid]] - v[c[valid, j]]).T)
        longest[valid] = np.maximum(longest[valid], d)
    return longest


def grid_shape(mesh, cell: float | None, max_nodes: int = 250_000) -> tuple[int, int]:
    """(nx, nz) of a grid over the mesh. The automatic cell is the median edge of the 5 %
    smallest mesh cells, at least 1/400 of the mesh width; the node count is capped by
    enlarging the cell."""
    smin, smax, zmin, zmax = mesh.bounds()
    width, height = max(smax - smin, 1e-9), max(zmax - zmin, 1e-9)
    if cell is None or cell <= 0:
        size = np.sort(_longest_edges(mesh))
        cell = max(float(np.median(size[:max(1, len(size) // 20)])), width / 400)
    nx, nz = int(np.ceil(width / cell)) + 1, int(np.ceil(height / cell)) + 1
    while nx * nz > max_nodes:
        cell *= np.sqrt(nx * nz / max_nodes) * 1.01
        nx, nz = int(np.ceil(width / cell)) + 1, int(np.ceil(height / cell)) + 1
    return max(nx, 2), max(nz, 2)


def _to_log(v: np.ndarray) -> np.ndarray:
    return np.log10(np.where(v > 0, v, np.nan))


def grid_model(mesh, topo, shape, log: bool, values=None) -> Grid:
    """The mesh's values (or ``values`` per cell) on a regular grid. Cell values are
    averaged onto the mesh vertices and interpolated linearly inside each cell (in log10
    when ``log``). Nodes outside every cell, in a cell without a value, or above ``topo``
    (s, z) stay nan: never extrapolates past the mesh or bridges gaps."""
    import matplotlib.tri as mtri

    nx, nz = shape
    smin, smax, zmin, zmax = mesh.bounds()
    s, z = np.linspace(smin, smax, nx), np.linspace(zmin, zmax, nz)
    S, Z = np.meshgrid(s, z)
    c = mesh.cells
    quad = c[:, 3] >= 0
    tris = np.vstack([c[:, :3], c[quad][:, [0, 2, 3]]])
    tri_cell = np.concatenate([np.arange(len(c)), np.flatnonzero(quad)])
    finder = mtri.Triangulation(mesh.vertices[:, 0], mesh.vertices[:, 1], tris).get_trifinder()
    t = finder(S.ravel(), Z.ravel())
    cell = np.where(t >= 0, tri_cell[np.maximum(t, 0)], -1).reshape(S.shape)

    v = np.asarray(mesh.values if values is None else values, float)
    v = _to_log(v) if log else v
    # cell values averaged onto the mesh vertices, then linear inside each mesh triangle:
    # covers the whole mesh, never bridges gaps or notches (no interpolation across cells
    # that do not touch)
    ok = c >= 0
    idx = c[ok]
    vals = np.repeat(v, 4).reshape(c.shape)[ok]
    fin = np.isfinite(vals)
    n = len(mesh.vertices)
    total = np.bincount(idx[fin], weights=vals[fin], minlength=n)
    count = np.bincount(idx[fin], minlength=n)
    vert = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    tri_mesh = mtri.Triangulation(mesh.vertices[:, 0], mesh.vertices[:, 1], tris)
    out = np.full(S.shape, np.nan)
    inside = cell >= 0
    if np.isfinite(vert).any():
        filled = np.where(np.isfinite(vert), vert, 0.0)
        interp = mtri.LinearTriInterpolator(tri_mesh, filled, trifinder=finder)
        smooth = np.ma.filled(interp(S[inside], Z[inside]).astype(float), np.nan)
        out[inside] = smooth
    own = v[cell[inside]]
    corner_nan = np.zeros(len(tris), bool)
    corner_nan |= ~np.isfinite(vert[tris]).all(axis=1)
    bad = corner_nan[np.maximum(t.reshape(S.shape)[inside], 0)]
    out[inside] = np.where(bad, own, out[inside])          # next to empty cells: own value
    out[inside] = np.where(np.isfinite(own), out[inside], np.nan)      # empty cells stay empty
    if topo is not None and len(topo[0]) >= 2:
        out[Z > np.interp(S, np.asarray(topo[0], float), np.asarray(topo[1], float)) + 1e-9] = \
            np.nan
    if log:
        out = np.power(10.0, out)
    return Grid(s, z, out, cell)


def _nice(x: float) -> float:
    e = np.floor(np.log10(x))
    for m in (1, 2, 5, 10):
        if m * 10 ** e >= x * (1 - 1e-9):
            return float(m * 10 ** e)
    return float(10 ** (e + 1))


def default_levels(scale, step: float | None) -> list[float]:
    """Contour levels inside the scale's range: 1-2-5 per decade (log) or about eight nice
    steps (linear); ``step`` overrides (decades on a log scale, units otherwise)."""
    lo, hi = scale.vmin, scale.vmax
    eps = 1e-9
    if scale.log:
        a, b = np.log10(lo), np.log10(hi)
        if step:
            ks = range(int(np.ceil(a / step - eps)), int(np.floor(b / step + eps)) + 1)
            return [float(10 ** (k * step)) for k in ks]
        out = []
        for d in range(int(np.floor(a)), int(np.ceil(b)) + 1):
            for m in (1, 2, 5):
                v = m * 10.0 ** d
                if lo * (1 - eps) <= v <= hi * (1 + eps):
                    out.append(float(v))
        return out
    step = step or _nice((hi - lo) / 8)
    ks = range(int(np.ceil(lo / step - eps)), int(np.floor(hi / step + eps)) + 1)
    return [float(round(k * step, 12)) for k in ks]


def contour_lines(grid: Grid, levels, log: bool) -> list[tuple[float, list[np.ndarray]]]:
    """Each level's polylines, as (k, 2) arrays of (s, z)."""
    import contourpy

    vals = _to_log(grid.values) if log else grid.values
    gen = contourpy.contour_generator(grid.s, grid.z, np.ma.masked_invalid(vals),
                                      name="serial", line_type="Separate")
    out = []
    for level in levels:
        if log and level <= 0:
            continue
        lines = gen.lines(float(np.log10(level)) if log else float(level))
        out.append((float(level), [np.asarray(x, float) for x in lines if len(x) >= 2]))
    return out
