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
    ``grid_cell`` and ``fade_mode``."""
    shape = grid_shape(mesh, style.grid_cell)
    grid = grid_model(mesh, topo, shape, style.scale.log, fill_to_ground=True)
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


def curtain_cells(mesh, chainage, rgba, threshold: float | None) -> list[CurtainCell]:
    """``mesh`` (chainage s, elevation z) as 3D cells under ``chainage``'s line; ``rgba``: one
    uint8 row per cell (``ColorScale.rgba``). With a ``threshold`` (the section fades low
    coverage), cells whose finite coverage is below it are left out; without one, every cell
    is kept and ``resolved`` says how it compares with the model's default threshold."""
    verts = np.asarray(mesh.vertices, float)
    xy = np.atleast_2d(chainage.to_xy(verts[:, 0]))
    z = verts[:, 1]
    coverage = None if mesh.coverage is None else np.asarray(mesh.coverage, float)
    cut = threshold
    if cut is None and coverage is not None:
        cut = default_threshold(coverage, getattr(mesh, "coverage_cut", None))
    colours = np.asarray(rgba)
    out = []
    for i, cell in enumerate(np.asarray(mesh.cells, int)):
        cov = math.nan if coverage is None else float(coverage[i])
        resolved = cut is None or not math.isfinite(cov) or cov >= cut
        if threshold is not None and not resolved:
            continue
        if colours.shape[1] > 3 and colours[i][3] == 0:
            continue                        # the section leaves it out (no value, clear)
        ring = [(float(xy[k, 0]), float(xy[k, 1]), float(z[k])) for k in cell if k >= 0]
        ring.append(ring[0])
        r, g, b = (int(c) for c in colours[i][:3])
        out.append(CurtainCell(ring, float(mesh.values[i]), cov, resolved, (r, g, b)))
    return out


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
