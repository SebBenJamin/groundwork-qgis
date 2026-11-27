"""Gridded display of section models: smooth fields, contour lines, coverage fade (no QGIS)."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


FADE_ALPHA = 0.25


def coverage_alpha(coverage, threshold: float, mode: str) -> np.ndarray:
    """Per-cell alpha factor: 1 where coverage >= threshold (or unknown), else 0.25 for
    "fade" and 0 for "blank"."""
    c = np.asarray(coverage, float)
    low = np.isfinite(c) & (c < threshold)
    return np.where(low, 0.0 if mode == "blank" else FADE_ALPHA, 1.0)


def soft_coverage_alpha(coverage, threshold: float, mode: str, band: float) -> np.ndarray:
    """Like ``coverage_alpha`` but soft: a smoothstep from the low alpha (``FADE_ALPHA``, or
    0 for "blank") at ``threshold - band/2`` to 1 at ``threshold + band/2``, so the faded
    part of a smooth field has no hard, blocky edge. ``band`` 0: the hard step."""
    if not band > 0:
        return coverage_alpha(coverage, threshold, mode)
    c = np.asarray(coverage, float)
    low = 0.0 if mode == "blank" else FADE_ALPHA
    t = np.clip((c - (threshold - band / 2)) / band, 0.0, 1.0)
    t = t * t * (3.0 - 2.0 * t)
    return np.where(np.isfinite(c), low + (1.0 - low) * t, 1.0)


def fade_band(coverage) -> float:
    """Width of the soft fade: a tenth of the coverage's 5-95 % spread (0 without data)."""
    c = np.asarray(coverage, float)
    c = c[np.isfinite(c)]
    if c.size < 2:
        return 0.0
    return float(0.1 * (np.percentile(c, 95) - np.percentile(c, 5)))


def default_threshold(coverage, cut: float | None = None) -> float:
    """Default coverage threshold: the file's own ``cut`` when it gives a finite one, else
    the 10th percentile of the finite values (0.0 if none)."""
    if cut is not None and np.isfinite(cut):
        return float(cut)
    c = np.asarray(coverage, float)
    c = c[np.isfinite(c)]
    return float(np.percentile(c, 10)) if c.size else 0.0


#: ``Grid.cell`` of nodes above the ground (masked by the topography, not "outside")
ABOVE_GROUND = -2


@dataclass
class Grid:
    s: np.ndarray           # (nx,) chainage of the grid columns
    z: np.ndarray           # (nz,) elevation of the grid rows, ascending
    values: np.ndarray      # (nz, nx) model values, nan where nothing is drawn
    cell: np.ndarray        # (nz, nx) mesh cell under each node, -1 outside the mesh,
    #                         ABOVE_GROUND above the topography
    note: str = ""          # why the chosen method fell back to linear ("" when it did not)
    fitted: dict = field(default_factory=dict)      # what the method fitted (kriging)


def next_to_empty(grid, mesh) -> np.ndarray:
    """Nodes next to a node outside the mesh or in a cell without a value: their pixel
    would reach half a grid cell into it, so they are left out (the field stops just short
    of empty space instead of overshooting into it). The ground is handled by the clip."""
    cell = grid.cell
    empty = (cell == -1) | ((cell >= 0) & ~np.isfinite(mesh.values[np.maximum(cell, 0)]))
    pad = np.pad(empty, 1, constant_values=True)
    near = pad[:-2, 1:-1] | pad[2:, 1:-1] | pad[1:-1, :-2] | pad[1:-1, 2:]
    return near & ~empty


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


#: the most nodes a smooth field is gridded with; a finer typed cell is enlarged to fit
MAX_GRID_NODES = 250_000


def _shape_and_cap(mesh, cell: float | None, max_nodes: int) -> tuple[int, int, bool]:
    smin, smax, zmin, zmax = mesh.bounds()
    width, height = max(smax - smin, 1e-9), max(zmax - zmin, 1e-9)
    if cell is None or cell <= 0:
        cell = _auto_cell(mesh, width)
    nx, nz = int(np.ceil(width / cell)) + 1, int(np.ceil(height / cell)) + 1
    capped = False
    while nx * nz > max_nodes:
        capped = True
        cell *= np.sqrt(nx * nz / max_nodes) * 1.01
        nx, nz = int(np.ceil(width / cell)) + 1, int(np.ceil(height / cell)) + 1
    return max(nx, 2), max(nz, 2), capped


def grid_shape(mesh, cell: float | None, max_nodes: int = MAX_GRID_NODES) -> tuple[int, int]:
    """(nx, nz) of a grid over the mesh. The automatic cell is a quarter of the median
    longest edge of the 5 % smallest mesh cells, at least 1/1500 of the mesh width; the node
    count is capped by enlarging the cell."""
    nx, nz, _capped = _shape_and_cap(mesh, cell, max_nodes)
    return nx, nz


def grid_cell_used(mesh, cell: float, max_nodes: int = MAX_GRID_NODES) -> float:
    """The grid cell a smooth field of ``mesh`` is drawn with for a typed ``cell`` (m): the
    typed one, or the node spacing of the capped grid when the typed one needs more than
    ``max_nodes`` nodes."""
    nx, nz, capped = _shape_and_cap(mesh, cell, max_nodes)
    if not capped:
        return float(cell)
    smin, smax, zmin, zmax = mesh.bounds()
    return float(max((smax - smin) / (nx - 1), (zmax - zmin) / (nz - 1)))


def _auto_cell(mesh, width: float) -> float:
    """The automatic grid cell of ``mesh`` (see ``grid_shape``), worked out once per mesh."""
    memo = getattr(mesh, "_memo", {})
    if "auto_cell" not in memo:
        size = np.sort(_longest_edges(mesh))
        # finer than the mesh, so the field looks smooth; never absurdly fine
        memo["auto_cell"] = max(float(np.median(size[:max(1, len(size) // 20)])) / 4,
                                width / 1500)
    return memo["auto_cell"]


def width_of(verts: np.ndarray) -> float:
    return float(np.ptp(verts[:, 0])) if len(verts) else 0.0


def _merged(mesh) -> tuple[np.ndarray, np.ndarray]:
    """Vertices with coincident points merged, and the cells renumbered (-1 kept). Some
    readers (R2) store every cell with its own corners; merged, the cells connect, so
    values blend across their edges and the triangulation is valid."""
    v = mesh.vertices
    tol = 1e-9 * max(float(np.ptp(v)) if len(v) else 1.0, 1.0)
    _u, first, inverse = np.unique(np.round(v / tol), axis=0, return_index=True,
                                   return_inverse=True)
    c = mesh.cells
    renum = np.where(c >= 0, inverse.ravel()[np.maximum(c, 0)], -1)
    return v[first], renum


#: candidate (triangle, node) pairs tested at once by ``locate_nodes``: bounds its memory
_LOCATE_CHUNK = 4_000_000


def locate_nodes(verts: np.ndarray, tris: np.ndarray, s: np.ndarray, z: np.ndarray
                 ) -> tuple[np.ndarray, np.ndarray]:
    """For each node of the regular grid ``s`` x ``z`` (row by row, z outer): the triangle
    of ``tris`` it lies in (-1 outside every one) and its barycentric weights (n, 3) there.
    Each triangle tests only the nodes inside its bounding box; a node on an edge shared by
    two triangles takes either (the linear values agree there)."""
    nx, nz = len(s), len(z)
    t = np.full(nx * nz, -1, dtype=np.int64)
    w = np.zeros((nx * nz, 3))
    if not len(tris) or nx < 1 or nz < 1:
        return t, w
    ds = (s[-1] - s[0]) / (nx - 1) if nx > 1 else 1.0
    dz = (z[-1] - z[0]) / (nz - 1) if nz > 1 else 1.0
    ds, dz = (d if d > 0 else 1.0 for d in (ds, dz))
    ax, az = verts[tris[:, 0], 0], verts[tris[:, 0], 1]
    bx, bz = verts[tris[:, 1], 0], verts[tris[:, 1], 1]
    cx, cz = verts[tris[:, 2], 0], verts[tris[:, 2], 1]
    xs, zs = np.stack([ax, bx, cx]), np.stack([az, bz, cz])
    i0 = np.clip(np.ceil((xs.min(0) - s[0]) / ds - 1e-9), 0, nx).astype(np.int64)
    i1 = np.clip(np.floor((xs.max(0) - s[0]) / ds + 1e-9), -1, nx - 1).astype(np.int64)
    j0 = np.clip(np.ceil((zs.min(0) - z[0]) / dz - 1e-9), 0, nz).astype(np.int64)
    j1 = np.clip(np.floor((zs.max(0) - z[0]) / dz + 1e-9), -1, nz - 1).astype(np.int64)
    ni, nj = np.maximum(i1 - i0 + 1, 0), np.maximum(j1 - j0 + 1, 0)
    n = ni * nj
    det = (bz - cz) * (ax - cx) + (cx - bx) * (az - cz)
    ends = np.cumsum(n)
    k0 = 0
    while k0 < len(tris):
        before = int(ends[k0 - 1]) if k0 else 0
        k1 = max(int(np.searchsorted(ends, before + _LOCATE_CHUNK, side="right")), k0 + 1)
        nn = n[k0:k1]
        total = int(nn.sum())
        if total:
            tri = np.repeat(np.arange(k0, k1), nn)
            off = np.arange(total) - np.repeat(np.cumsum(nn) - nn, nn)
            ii = i0[tri] + off % ni[tri]
            jj = j0[tri] + off // ni[tri]
            px, pz = s[ii] - cx[tri], z[jj] - cz[tri]
            l1 = ((bz - cz)[tri] * px + (cx - bx)[tri] * pz) / det[tri]
            l2 = ((cz - az)[tri] * px + (ax - cx)[tri] * pz) / det[tri]
            l3 = 1.0 - l1 - l2
            ok = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9)
            node = jj[ok] * nx + ii[ok]
            t[node] = tri[ok]
            w[node] = np.column_stack([l1[ok], l2[ok], l3[ok]])
        k0 = k1
    return t, w


def _triangles(mesh) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(merged vertices, renumbered cells, triangles, the cell of each triangle) of
    ``mesh``: quads split in two, triangles without an area left out. Once per mesh."""
    memo = getattr(mesh, "_memo", {})
    if "triangles" not in memo:
        verts, c = _merged(mesh)
        quad = c[:, 3] >= 0
        tris = np.vstack([c[:, :3], c[quad][:, [0, 2, 3]]])
        tri_cell = np.concatenate([np.arange(len(c)), np.flatnonzero(quad)])
        p0, p1, p2 = (verts[tris[:, k]] for k in range(3))
        area = np.abs((p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1])
                      - (p2[:, 0] - p0[:, 0]) * (p1[:, 1] - p0[:, 1]))
        good = area > 1e-12 * max(width_of(verts), 1.0) ** 2
        memo["triangles"] = (verts, c, tris[good], tri_cell[good])
    return memo["triangles"]


def _located(mesh, verts, tris, s, z) -> tuple[np.ndarray, np.ndarray]:
    """``locate_nodes`` for ``mesh``'s grid; the last grid is kept, so the coverage of a
    fade (same mesh, same grid) and the 3D view's grid reuse it."""
    memo = getattr(mesh, "_memo", {})
    key = (len(s), float(s[0]), float(s[-1]), len(z), float(z[0]), float(z[-1]))
    hit = memo.get("located")
    if hit is None or hit[0] != key:
        hit = (key, *locate_nodes(verts, tris, s, z))
        memo["located"] = hit
    return hit[1], hit[2]


def _to_log(v: np.ndarray) -> np.ndarray:
    return np.log10(np.where(v > 0, v, np.nan))


def cell_centres(mesh) -> np.ndarray:
    """(n, 2) mean of each cell's own corners (a triangle's -1 left out). Once per mesh."""
    memo = getattr(mesh, "_memo", {})
    if "centres" not in memo:
        c = mesh.cells
        corners = mesh.vertices[np.maximum(c, 0)]                  # (n, 4, 2)
        own = (c >= 0)[..., None]
        memo["centres"] = (corners * own).sum(axis=1) / own.sum(axis=1)
    return memo["centres"]


def cell_aspect(mesh) -> float:
    """Median cell width over median cell height: the default anisotropy of the gridding
    methods (inversion meshes are wider than tall where the ground is layered)."""
    v, c = mesh.vertices, mesh.cells
    corners = v[np.maximum(c, 0)]
    own = (c >= 0)[..., None]
    big, small = np.where(own, corners, -np.inf), np.where(own, corners, np.inf)
    size = big.max(axis=1) - small.min(axis=1)                    # (n, 2) width, height
    w, h = float(np.median(size[:, 0])), float(np.median(size[:, 1]))
    return max(w / h, 1e-3) if h > 0 else 1.0


def _scattered(mesh, v, nodes, interp) -> tuple[np.ndarray, dict]:
    """``interp``'s values at ``nodes`` (m, 2) from the cell centres with a value ``v``
    (already in log10 on a log scale), and what it fitted. ValueError when it fails."""
    from .interpolators import estimate_anisotropy, interpolate
    ok = np.isfinite(v)
    if not ok.any():
        raise ValueError("no cell has a value")
    points = cell_centres(mesh)[ok]
    aniso = interp.anisotropy
    if aniso is None:           # Auto: kriging reads it from the data, the others the cells
        aniso = (estimate_anisotropy(points, v[ok], interp.variogram)
                 if interp.method == "kriging" else cell_aspect(mesh))
    out, fitted = interpolate(points, v[ok], nodes, interp, aniso)
    if not np.isfinite(out).all():
        raise ValueError("it gave values that are not numbers")
    return out, fitted


def grid_model(mesh, topo, shape, log: bool, values=None,
               fill_to_ground: bool = False, interp=None) -> Grid:
    """The mesh's values (or ``values`` per cell) on a regular grid. Cell values are
    averaged onto the mesh vertices and interpolated linearly inside each cell (in log10
    when ``log``). Nodes outside every cell, in a cell without a value, or above ``topo``
    (s, z) stay nan: never extrapolates past the mesh or bridges gaps.

    ``interp`` (``core.interpolators.Interpolation``, None = linear) chooses another method:
    the cell centres are interpolated onto the nodes that lie in a cell with a value; the
    masks stay the same. A method that fails falls back to linear and says why in
    ``Grid.note``."""
    nx, nz = shape
    smin, smax, zmin, zmax = mesh.bounds()
    s = np.linspace(smin, smax, nx)
    has_topo = topo is not None and len(topo[0]) >= 2
    if has_topo:
        ts, tz = np.asarray(topo[0], float), np.asarray(topo[1], float)
    top = zmax
    if fill_to_ground and has_topo:     # room for the field between mesh top and ground
        top = max(zmax, float(np.interp(s, ts, tz).max()))
    dz = (zmax - zmin) / max(nz - 1, 1)
    if top > zmax and dz > 0:
        nz += int(np.ceil((top - zmax) / dz))
        top = zmin + dz * (nz - 1)
    z = np.linspace(zmin, top, nz)
    S, Z = np.meshgrid(s, z)
    verts, c, tris, tri_cell = _triangles(mesh)
    if not len(tris):
        raise ValueError("cannot grid this mesh: it has no cell with an area")
    t, weights = _located(mesh, verts, tris, s, z)
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
    n = len(verts)
    total = np.bincount(idx[fin], weights=vals[fin], minlength=n)
    count = np.bincount(idx[fin], minlength=n)
    vert = np.where(count > 0, total / np.maximum(count, 1), np.nan)
    out = np.full(S.shape, np.nan)
    inside = cell >= 0
    if np.isfinite(vert).any():
        filled = np.where(np.isfinite(vert), vert, 0.0)
        flat = inside.ravel()
        out[inside] = (weights[flat] * filled[tris[t[flat]]]).sum(axis=1)
    own = v[cell[inside]]
    corner_nan = np.zeros(len(tris), bool)
    corner_nan |= ~np.isfinite(vert[tris]).all(axis=1)
    bad = corner_nan[np.maximum(t.reshape(S.shape)[inside], 0)]
    out[inside] = np.where(bad, own, out[inside])          # next to empty cells: own value
    out[inside] = np.where(np.isfinite(own), out[inside], np.nan)      # empty cells stay empty
    note, fitted = "", {}
    if interp is not None and not interp.is_linear:
        # another method: the same nodes (in a cell with a value), other values
        nodes = inside & np.isfinite(out)
        try:
            new, fitted = _scattered(mesh, v, np.column_stack([S[nodes], Z[nodes]]), interp)
            out[nodes] = new
        except (ValueError, np.linalg.LinAlgError, MemoryError) as exc:
            from .interpolators import METHOD_NAMES
            why = "not enough memory" if isinstance(exc, MemoryError) else str(exc)
            note = (f"{METHOD_NAMES.get(interp.method, interp.method)} could not be used "
                    f"here ({why}): the field is gridded linearly instead.")
    if fill_to_ground and has_topo:
        # flat-topped cells leave steps under the ground line: fill each column upward from
        # its top valid node to the ground (the surface layer reaches the surface)
        valid = np.isfinite(out) & (cell >= 0)
        rows = np.arange(len(z))[:, None]
        top_row = np.where(valid.any(axis=0), np.max(np.where(valid, rows, -1), axis=0), -1)
        ground = np.interp(S, ts, tz)
        cols = np.arange(len(s))
        src_val = out[np.maximum(top_row, 0), cols]
        src_cell = cell[np.maximum(top_row, 0), cols]
        fill = (rows > top_row[None, :]) & (top_row[None, :] >= 0) & (Z <= ground + 1e-9)
        out = np.where(fill, src_val[None, :], out)
        cell = np.where(fill, src_cell[None, :], cell)
    if has_topo:
        above = Z > np.interp(S, ts, tz) + 1e-9
        out[above] = np.nan
        cell = np.where(above, ABOVE_GROUND, cell)
    if log:
        out = np.power(10.0, out)
    return Grid(s, z, out, cell, note, fitted)


def _nice(x: float) -> float:
    e = np.floor(np.log10(x))
    for m in (1, 2, 5, 10):
        if m * 10 ** e >= x * (1 - 1e-9):
            return float(m * 10 ** e)
    return float(10 ** (e + 1))


MAX_LEVELS = 100


def default_levels(scale, step: float | None) -> list[float]:
    """Contour levels inside the scale's range: 1-2-5 per decade (log) or about eight nice
    steps (linear); ``step`` overrides (decades on a log scale, units otherwise). Never more
    than MAX_LEVELS: a too small step is widened (a tiny step would stall drawing)."""
    lo, hi = scale.vmin, scale.vmax
    eps = 1e-9
    if scale.log:
        a, b = np.log10(lo), np.log10(hi)
        if step:
            step = max(step, (b - a) / (MAX_LEVELS - 1))
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
    step = max(step, (hi - lo) / (MAX_LEVELS - 1))
    ks = range(int(np.ceil(lo / step - eps)), int(np.floor(hi / step + eps)) + 1)
    return [float(round(k * step, 12)) for k in ks]


def contour_levels(scale, step: float | None, major=(), minor=()) -> list[tuple[float, bool]]:
    """(level, major) pairs to draw. Typed ``major`` / ``minor`` levels (the model's unit)
    win over the automatic ones: inside the scale's range, sorted, repeats merged (a level
    in both lists is major), at most MAX_LEVELS (majors kept first). Without typed levels,
    ``default_levels`` - all major, as before."""
    if not major and not minor:
        return [(v, True) for v in default_levels(scale, step)]
    lo, hi = min(scale.vmin, scale.vmax), max(scale.vmin, scale.vmax)
    picked: list[tuple[float, bool]] = []
    for values, is_major in ((major, True), (minor, False)):
        for v in values:
            v = float(v)
            if not np.isfinite(v) or not lo <= v <= hi:
                continue
            if any(abs(v - w) <= 1e-9 * max(abs(v), abs(w), 1.0) for w, _ in picked):
                continue
            picked.append((v, is_major))
    picked = sorted(picked, key=lambda p: not p[1])[:MAX_LEVELS]   # majors first when capping
    return sorted(picked)


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
