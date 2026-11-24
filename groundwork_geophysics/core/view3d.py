"""Geometry for the QGIS 3D view (pure NumPy): a model's cells as vertical rings standing
under the profile line, its smooth field as points and its contour lines as 3D lines there,
and a borehole's log intervals as vertical segments at its map position. Colours come in
from the section's colour scale and interval style."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

from .gridding import (FADE_ALPHA, Grid, contour_lines, default_threshold, fade_band,
                       grid_model, grid_shape, next_to_empty, soft_coverage_alpha)


@dataclass(frozen=True)
class FieldPoints:
    xyz: np.ndarray             # (n, 3) map position and elevation
    rgb: np.ndarray             # (n, 3) uint8, the section colour
    value: np.ndarray           # (n,) the model value


def field_grid(mesh, topo, style, threshold: float | None) -> Grid:
    """The section's smooth grid of ``mesh`` (as the panel draws it in smooth mode), with nan
    where the section shows nothing: next to empty space and, with ``threshold`` (the fade
    is on), where the soft fade makes a node faint or blank. ``style``: its ``scale``,
    ``grid_cell``, ``interpolation`` and ``fade_mode``."""
    shape = grid_shape(mesh, style.grid_cell)
    grid = grid_model(mesh, topo, shape, style.scale.log, fill_to_ground=True,
                      interp=getattr(style, "interpolation", None))
    drop = next_to_empty(grid, mesh)
    if threshold is not None and getattr(mesh, "coverage", None) is not None:
        cov = grid_model(mesh, topo, shape, False, values=mesh.coverage, fill_to_ground=True)
        alpha = soft_coverage_alpha(cov.values, threshold, style.fade_mode,
                                    fade_band(mesh.coverage))
        floor = 0.0 if style.fade_mode == "blank" else FADE_ALPHA
        drop |= alpha < (floor + 1.0) / 2
    return replace(grid, values=np.where(drop, np.nan, grid.values))


def field_points(grid: Grid, chainage, scale, spacing: float = 0.05) -> FieldPoints:
    """The grid's drawn nodes as points under ``chainage``'s line, thinned so they are at
    least ``spacing`` apart along and across; nan values (and values <= 0 on a log scale)
    are left out."""
    ds = float(grid.s[1] - grid.s[0]) if len(grid.s) > 1 else 1.0
    dz = float(grid.z[1] - grid.z[0]) if len(grid.z) > 1 else 1.0
    step_s = max(1, int(math.ceil(spacing / ds - 1e-9))) if spacing > 0 else 1
    step_z = max(1, int(math.ceil(spacing / dz - 1e-9))) if spacing > 0 else 1
    s, z = grid.s[::step_s], grid.z[::step_z]
    values = grid.values[::step_z, ::step_s]
    keep = np.isfinite(values)
    if scale.log:
        keep &= values > 0
    S, Z = np.meshgrid(s, z)
    v = values[keep]
    xy = np.atleast_2d(chainage.to_xy(S[keep])).reshape(-1, 2)
    return FieldPoints(np.column_stack([xy, Z[keep]]),
                       np.asarray(scale.rgba(v))[:, :3].astype(np.uint8), v.astype(float))


def field_contours(grid: Grid, chainage, scale, levels) -> list[tuple[float, np.ndarray]]:
    """(level, (k, 3) x/y/z) per contour polyline of the grid, under ``chainage``'s line."""
    out = []
    for level, lines in contour_lines(grid, levels, scale.log):
        for line in lines:
            xy = np.atleast_2d(chainage.to_xy(line[:, 0])).reshape(-1, 2)
            out.append((level, np.column_stack([xy, line[:, 1]])))
    return out


def curtain_gap(length: float) -> float:
    """How far each face of a curtain stands back from its profile's plane: 0.2 % of the
    profile's length, 5 cm to 50 cm (enough for the graphics card to tell the faces from an
    interpretation drawn in the plane, small next to the curtain)."""
    return float(min(0.5, max(0.05, 0.002 * length)))


def left_normals(chainage, s) -> np.ndarray:
    """(n, 2) unit vectors to the left of the line at chainages ``s`` (at a bend: between
    the two legs)."""
    s = np.atleast_1d(np.asarray(s, float))
    d = (np.atleast_2d(chainage.to_xy(s + 1e-3)) - np.atleast_2d(chainage.to_xy(s - 1e-3)))
    d /= np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-12)[:, None]
    return np.column_stack([-d[:, 1], d[:, 0]])


def two_faces(ring_s, ring_z, chainage, gap: float) -> tuple[list, list]:
    """A curtain cell (a ring in chainage and elevation) as two closed 3D rings, one per
    side: the ring that faces the right of the line (counter-clockwise in (s, z)) stands
    ``gap`` to the left, its reversed copy facing left stands ``gap`` to the right. With
    back faces hidden, each side then sees a face behind the plane, so whatever is drawn in
    the plane (the interpretation) is always in front."""
    s, z = np.asarray(ring_s, float), np.asarray(ring_z, float)
    if len(s) > 1 and s[0] == s[-1] and z[0] == z[-1]:
        s, z = s[:-1], z[:-1]
    area = float(np.sum(s * np.roll(z, -1) - np.roll(s, -1) * z))
    if area < 0:                                   # clockwise: turn it round
        s, z = s[::-1], z[::-1]
    xy = np.atleast_2d(chainage.to_xy(s)).reshape(-1, 2)
    left = left_normals(chainage, s) * gap
    front = [(float(x), float(y), float(h)) for (x, y), h in zip(xy + left, z)]
    back = [(float(x), float(y), float(h)) for (x, y), h in zip(xy - left, z)]
    back = [back[0]] + back[:0:-1]
    return front + front[:1], back + back[:1]


def bend_chainages(chainage, share: float = 0.01, least: float = 0.3) -> list[float]:
    """Chainages of the line's real bends: its vertices kept by Douglas-Peucker with a
    tolerance of ``share`` of its length (at least ``least`` m), so electrode jitter along
    a straight line does not count."""
    xy = chainage.xy
    cum = np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]
    tol = max(least, share * cum[-1])
    keep, stack = set(), [(0, len(xy) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        d = xy[b] - xy[a]
        rel = xy[a + 1:b] - xy[a]
        dist = np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0]) / (np.hypot(*d) or 1.0)
        i = int(np.argmax(dist))
        if dist[i] > tol:
            keep.add(a + 1 + i)
            stack += [(a, a + 1 + i), (a + 1 + i, b)]
    return [float(cum[i]) for i in sorted(keep)]


def picture_strip(alpha, s0: float, s1: float, z0: float, z1: float, extra_s, step: float,
                  max_columns: int = 400) -> tuple[np.ndarray, np.ndarray]:
    """The strip of triangles a section picture hangs on: columns at ``extra_s`` (the line's
    bends) and about every ``step`` m (at most ``max_columns``), each from the lowest to the
    highest painted texel of the picture (``alpha``: (rows, columns), row 0 at ``z1``) over
    s0..s1, z0..z1. Returns (n, 4) rows of (s, z, u, v), bottom then top per column (v from
    the picture's top), and the triangles between neighbouring columns."""
    alpha = np.asarray(alpha)
    h, w = alpha.shape
    count = int(min(max_columns, max(2, (s1 - s0) / step + 1)))
    inner = [float(s) for s in extra_s if s0 < s < s1]
    ss = np.unique(np.r_[np.linspace(s0, s1, count), inner])
    rows_painted = alpha > 0
    out = []
    for s in ss:
        col = int(np.clip(round((s - s0) / (s1 - s0) * (w - 1)), 0, w - 1))
        rows = np.flatnonzero(rows_painted[:, max(0, col - 2):col + 3].any(axis=1))
        top, bottom = (rows[0] - 1, rows[-1] + 1) if rows.size else (h // 2, h // 2 - 1)
        z_top = z1 - max(top, 0) / h * (z1 - z0)
        z_bottom = z1 - min(bottom + 1, h) / h * (z1 - z0)
        u = (s - s0) / (s1 - s0)
        for z in (z_bottom, z_top):
            out.append((s, z, u, (z1 - z) / (z1 - z0)))
    tris = []
    for i in range(len(ss) - 1):
        a, b, c, d = 2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3      # a, c bottom; b, d top
        tris += [(a, c, d), (a, d, b)]
    return np.asarray(out, float), np.asarray(tris, np.uint32).reshape(-1, 3)


@dataclass(frozen=True)
class CurtainCell:
    ring: list                  # closed [(x, y, z)], the first point repeated last
    value: float
    coverage: float             # nan when the model has none (or the cell's is unknown)
    resolved: bool              # coverage at or above the threshold, or unknown
    rgb: tuple
    #: with a gap: the cell as two closed rings, one per side (see ``two_faces``)
    faces: tuple = ()
    #: the section fades it (below the threshold, fade mode "fade"): drawn see-through
    faded: bool = False


@dataclass(frozen=True)
class BoreholeInterval:
    x: float
    y: float
    z_top: float
    z_bottom: float
    top: float                  # depth below the collar (m)
    bottom: float
    text: str
    rgb: tuple


@dataclass(frozen=True)
class CurtainArrays:
    """A model's curtain cells as arrays (``curtain_arrays``), one row per kept cell."""
    index: np.ndarray           # (k,) the mesh cells kept
    points: np.ndarray          # (k,) points of each closed ring: 4 (triangle) or 5 (quad)
    ring: np.ndarray            # (k, 5, 3) closed rings (x, y, z), padded with their last point
    front: np.ndarray | None    # (k, 5, 3) with a gap: the face that stands gap to the left
    back: np.ndarray | None     # (k, 5, 3) and its reversed copy gap to the right
    value: np.ndarray
    coverage: np.ndarray        # nan when the model has none
    resolved: np.ndarray        # bool
    rgb: np.ndarray             # (k, 3) uint8
    faded: np.ndarray           # bool


def curtain_arrays(mesh, chainage, rgba, threshold: float | None, gap: float = 0.0,
                   keep_faded: bool = False) -> CurtainArrays:
    """``mesh`` (chainage s, elevation z) as 3D cells under ``chainage``'s line; ``rgba``: one
    uint8 row per cell (``ColorScale.rgba``). With a ``threshold`` (the section fades low
    coverage), cells whose finite coverage is below it are left out, or with ``keep_faded``
    (the section fades rather than blanks them) kept and marked ``faded``; without one, every
    cell is kept and ``resolved`` says how it compares with the model's default threshold.
    Cells the section leaves out (no value, clear) are left out. With a ``gap``, each cell
    also comes as two faces standing that far back on either side (see ``two_faces``)."""
    verts = np.asarray(mesh.vertices, float)
    xy = np.atleast_2d(chainage.to_xy(verts[:, 0]))
    z = verts[:, 1]
    cells = np.asarray(mesh.cells, int)
    cov = (np.full(len(cells), np.nan) if mesh.coverage is None
           else np.asarray(mesh.coverage, float))
    cut = threshold
    if cut is None and mesh.coverage is not None:
        cut = default_threshold(cov, getattr(mesh, "coverage_cut", None))
    with np.errstate(invalid="ignore"):
        resolved = np.ones(len(cells), bool) if cut is None else ~np.isfinite(cov) | (cov >= cut)
    faded = ~resolved if threshold is not None else np.zeros(len(cells), bool)
    keep = ~faded | keep_faded
    colours = np.asarray(rgba)
    if colours.shape[1] > 3:
        keep &= colours[:, 3] != 0              # the section leaves it out (no value, clear)
    index = np.flatnonzero(keep)
    c = cells[index]
    quad = c[:, 3] >= 0

    def rings(order_quad, order_tri, at):
        idx = np.where(quad[:, None], order_quad, order_tri)
        return np.stack([at[idx, 0], at[idx, 1], z[idx]], axis=-1)

    ring = rings(c[:, [0, 1, 2, 3, 0]], c[:, [0, 1, 2, 0, 0]], xy)
    front = back = None
    if gap > 0:                                 # per vertex, so neighbours share it
        side = left_normals(chainage, verts[:, 0]) * gap
        corner = np.where(quad[:, None], c[:, :4], c[:, [0, 1, 2, 2]])
        s_, z_ = verts[corner, 0], verts[corner, 1]
        area = np.sum(s_ * np.roll(z_, -1, 1) - np.roll(s_, -1, 1) * z_, axis=1)
        cw = (area < 0)[:, None]                # counter-clockwise in (s, z): faces right
        o = np.where(quad[:, None], np.where(cw, c[:, [3, 2, 1, 0]], c[:, :4]),
                     np.where(cw, c[:, [2, 1, 0, 0]], c[:, [0, 1, 2, 0]]))
        front = rings(o[:, [0, 1, 2, 3, 0]], o[:, [0, 1, 2, 0, 0]], xy + side)
        back = rings(o[:, [0, 3, 2, 1, 0]], o[:, [0, 2, 1, 0, 0]], xy - side)
    return CurtainArrays(index, np.where(quad, 5, 4), ring, front, back,
                         np.asarray(mesh.values, float)[index], cov[index], resolved[index],
                         colours[index, :3].astype(np.uint8), faded[index])


_WKB_MULTIPOLYGON_Z, _WKB_POLYGON_Z = 1006, 1003
#: cells whose WKB records are built at once (bounds the memory of a huge curtain)
_WKB_CHUNK = 20_000


def faces_wkb(a: CurtainArrays) -> list[bytes]:
    """Each kept cell of ``a`` as a MultiPolygon Z of its two faces, in ISO WKB
    (little-endian); without faces (no gap) an empty MultiPolygon Z. Built a few thousand
    cells at a time in NumPy, one record type per ring size."""
    k = len(a.index)
    out: list[bytes] = [b""] * k
    if a.front is None:
        empty = np.array([(1, _WKB_MULTIPOLYGON_Z, 0)],
                         dtype=[("o", "u1"), ("t", "<u4"), ("n", "<u4")]).tobytes()
        return [empty] * k
    for n in np.unique(a.points):
        face = [("o", "u1"), ("t", "<u4"), ("r", "<u4"), ("n", "<u4"), ("p", "<f8", (int(n), 3))]
        dtype = np.dtype([("o", "u1"), ("t", "<u4"), ("n", "<u4"), ("f", face), ("b", face)])
        same = np.flatnonzero(a.points == n)
        for start in range(0, len(same), _WKB_CHUNK):
            rows = same[start:start + _WKB_CHUNK]
            rec = np.zeros(len(rows), dtype=dtype)
            rec["o"], rec["t"], rec["n"] = 1, _WKB_MULTIPOLYGON_Z, 2
            for name, pts in (("f", a.front), ("b", a.back)):
                rec[name]["o"], rec[name]["t"], rec[name]["r"] = 1, _WKB_POLYGON_Z, 1
                rec[name]["n"] = n
                rec[name]["p"] = pts[rows, :int(n)]
            raw, size = memoryview(rec).cast("B"), dtype.itemsize
            for j, row in enumerate(rows.tolist()):
                out[row] = bytes(raw[j * size:(j + 1) * size])
    return out


def curtain_cells(mesh, chainage, rgba, threshold: float | None,
                  gap: float = 0.0, keep_faded: bool = False) -> list[CurtainCell]:
    """``curtain_arrays`` as one ``CurtainCell`` per kept cell."""
    a = curtain_arrays(mesh, chainage, rgba, threshold, gap, keep_faded)

    def points(arr, k):
        return [tuple(float(v) for v in p) for p in arr[k, :int(a.points[k])]]
    return [CurtainCell(points(a.ring, k), float(a.value[k]), float(a.coverage[k]),
                        bool(a.resolved[k]), tuple(int(v) for v in a.rgb[k]),
                        () if a.front is None else (points(a.front, k), points(a.back, k)),
                        bool(a.faded[k]))
            for k in range(len(a.index))]


def borehole_intervals(point, surface_z: float | None, colour_of) -> list[BoreholeInterval]:
    """``point``'s log intervals (a gathered borehole) as vertical segments at its map
    position, from its collar height (else ``surface_z``) down. ``colour_of(text, symbol)``
    gives an interval's (r, g, b) as the section draws it. A borehole without intervals but
    with a total depth is one segment (``colour_of("", None)``); one without a map position
    or any height gives nothing."""
    x, y = getattr(point, "x", None), getattr(point, "y", None)
    collar = point.z_top if point.z_top is not None else surface_z
    if x is None or y is None or collar is None or not math.isfinite(collar):
        return []
    rows = [(iv.top, iv.bottom, iv.text, colour_of(iv.text, iv.symbol)) for iv in point.log]
    if not rows and point.total_depth:
        rows = [(0.0, float(point.total_depth), "", colour_of("", None))]
    return [BoreholeInterval(float(x), float(y), collar - top, collar - bottom, top, bottom,
                             text, tuple(rgb))
            for top, bottom, text, rgb in rows if bottom > top]
