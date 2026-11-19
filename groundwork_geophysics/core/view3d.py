"""Geometry for the QGIS 3D view (pure NumPy): a model's cells as vertical rings standing
under the profile line, and a borehole's log intervals as vertical segments at its map
position. Colours come in from the section's colour scale and interval style."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .gridding import default_threshold


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
