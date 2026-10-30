"""What third-party context lies under the cursor on a section. QGIS-free."""
from __future__ import annotations

import numpy as np

from ..core.context import ContextItems
from .readout import format_value, unit_label

MINUS = "\u2212"


def _signed(value: float) -> str:
    return f"{MINUS if value < 0 else '+'}{abs(value):.1f}"


def strip_start(points, tie_s: float, strip_width_s: float,
                column_half_width_s: float) -> float:
    """Chainage of a tie strip's left edge. The strip goes just right of the tie line;
    where a borehole column stands there it moves to the nearest free slot instead: left
    of the line when that is free, else just past the columns (a column centred on the
    line blocks both sides), on the nearer side, the right on a draw. Shared by
    ``context_render.draw_ties`` and the readout so both agree. Metres of chainage."""
    cols = [(p.s - column_half_width_s, p.s + column_half_width_s)
            for p in points if p.kind == "borehole" and p.log]

    def blocker(a: float, b: float):
        return next((c for c in cols if c[0] < b and c[1] > a), None)

    right = tie_s                           # left edge of a strip right of the line
    while (c := blocker(right, right + strip_width_s)) is not None:
        right = c[1]
    left = tie_s                            # right edge of a strip left of the line
    while (c := blocker(left - strip_width_s, left)) is not None:
        left = c[0]
    return right if right - tie_s <= tie_s - left else left - strip_width_s


def _dem_line(items: ContextItems, s: float, stations) -> str | None:
    if items.dem is None or len(items.dem[0]) < 1:
        return None
    ds, dz = (np.asarray(a, float) for a in items.dem)
    ok = np.isfinite(ds) & np.isfinite(dz)
    if not ok.any() or not ds[ok].min() <= s <= ds[ok].max():
        return None
    height = float(np.interp(s, ds[ok], dz[ok]))
    # a NaN neighbour means "no data" at s: the DEM line is left out there
    below = ds <= s
    above = ds >= s
    if below.any() and above.any():
        if not (np.isfinite(dz[below][np.argmax(ds[below])])
                and np.isfinite(dz[above][np.argmin(ds[above])])):
            return None
    text = f"DEM {height:.1f} m"
    if stations is not None and len(stations[0]) > 1 and stations[0][0] <= s <= stations[0][-1]:
        gap = float(np.interp(s, *stations)) - height
        text += f" (stations {_signed(gap)} m)"
    return text


def context_hits(items: ContextItems, s: float, z: float, tol_s: float,
                 column_half_width_s: float, strip_width_s: float | None = None,
                 surface=None, stations=None) -> list[str]:
    """Readout lines for the context at the cursor (s, z), in the order band, crossing,
    borehole, tie, DEM. ``tol_s`` and the widths are metres of chainage (the dock converts
    its pixel and millimetre sizes); ``surface`` is the drawn topography, which a borehole
    without its own top elevation hangs from; ``stations`` is the station line."""
    if strip_width_s is None:
        strip_width_s = 2.0 * column_half_width_s
    lines: list[str] = []
    for seg in items.band:
        if seg.s0 <= s <= seg.s1:
            lines.append(f"Surface geology: {seg.label}")
            break
    for c in items.crossings:
        if abs(s - c.s) <= tol_s:
            kind = "powerline" if c.kind == "powerline" else "line"
            lines.append(f"Crossing: {c.label} ({kind}, {c.angle_deg:.0f}\u00b0)")
    for p in items.points:
        if p.kind != "borehole" or abs(s - p.s) > column_half_width_s:
            continue
        if p.z_top is not None:
            z_top = float(p.z_top)
        elif surface is not None and len(surface[0]) > 0:
            z_top = float(np.interp(p.s, *surface))
        else:
            continue
        depth = z_top - z
        for iv in p.log:
            if iv.top <= depth <= iv.bottom:
                lines.append(f"Borehole {p.label} ({p.offset:+.0f} m): "
                             f"{iv.top:.1f}\u2013{iv.bottom:.1f} m {iv.lithology}")
                break
    for tie in items.ties:
        start = strip_start(items.points, tie.s, strip_width_s, column_half_width_s)
        if not start <= s <= start + strip_width_s or not tie.columns:
            continue
        col = tie.columns[0]
        for top, bot, v in zip(col.z_top, col.z_bottom, col.values):
            if bot <= z <= top and np.isfinite(v):
                unit = unit_label(col.unit)
                lines.append(f"Tie {tie.other_name}: {format_value(float(v))}"
                             + (f" {unit}" if unit else ""))
                break
    dem = _dem_line(items, s, stations)
    if dem is not None:
        lines.append(dem)
    return lines
