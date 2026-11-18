"""Where the borehole viewer puts its columns, and its zoomable view (no QGIS/Qt).

Two spacings: **even** (a correlation panel, columns in chainage order with equal gaps, x in
pixels) and **true distance** (columns centred on their chainage, x in metres). One vertical
scale for every column; ``z`` is elevation, or minus the depth below the collar in depth
mode, so it always grows upward. Overlapping columns are never pushed apart."""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from .context import collar_height

FIT_MARGIN = 0.06


@dataclass(frozen=True)
class ColumnPlace:
    index: int          # position in the list the layout was made from
    x: float            # even: left edge in px; true distance: centre chainage in metres
    width: float        # px


def column_depth(p) -> float:
    """How deep a borehole's column reaches: its deepest interval or its total depth."""
    return max([iv.bottom for iv in p.log] + [p.total_depth or 0.0])


def layout_even(widths_px: list[float], gap_px: float = 24) -> list[ColumnPlace]:
    out, x = [], 0.0
    for i, w in enumerate(widths_px):
        out.append(ColumnPlace(i, x, w))
        x += w + gap_px
    return out


def layout_true(chainages: list[float], widths_px: list[float]) -> list[ColumnPlace]:
    return [ColumnPlace(i, float(s), w) for i, (s, w) in enumerate(zip(chainages, widths_px))]


@dataclass(frozen=True)
class ViewTransform:
    """Layout units -> pixels: ``px = (x - x0) * x_scale``, ``py = (z0 - z) * z_scale``."""
    x0: float
    x_scale: float      # px per layout unit
    z0: float           # z at the top edge
    z_scale: float      # px per metre

    def to_px(self, x: float, z: float) -> tuple[float, float]:
        return (x - self.x0) * self.x_scale, (self.z0 - z) * self.z_scale

    def from_px(self, px: float, py: float) -> tuple[float, float]:
        return self.x0 + px / self.x_scale, self.z0 - py / self.z_scale

    def zoom_at(self, px: float, py: float, factor_x: float, factor_z: float) -> "ViewTransform":
        """Zoomed by the factors, keeping the point under (px, py) where it is."""
        x, z = self.from_px(px, py)
        xs, zs = self.x_scale * factor_x, self.z_scale * factor_z
        return ViewTransform(x - px / xs, xs, z + py / zs, zs)

    def panned(self, dx_px: float, dy_px: float) -> "ViewTransform":
        return replace(self, x0=self.x0 - dx_px / self.x_scale,
                       z0=self.z0 + dy_px / self.z_scale)


def vertical_exaggeration(t: ViewTransform) -> float:
    """Only meaningful when x is in metres (true distance)."""
    return t.z_scale / t.x_scale


def fit(extent_x: tuple, extent_z: tuple, size_px: tuple, keep_ve: float | None) -> ViewTransform:
    """A view showing both extents inside ``size_px`` with a small margin; with ``keep_ve``
    the vertical exaggeration is fixed (true distance), else each axis fills the view."""
    w, h = (max(1.0, float(v)) * (1 - 2 * FIT_MARGIN) for v in size_px)
    dx = max(extent_x[1] - extent_x[0], 1e-6)
    dz = max(extent_z[1] - extent_z[0], 1e-6)
    xs, zs = w / dx, h / dz
    if keep_ve:
        xs = min(xs, zs / keep_ve)
        zs = xs * keep_ve
    x0 = (extent_x[0] + extent_x[1]) / 2 - size_px[0] / 2 / xs
    z0 = (extent_z[0] + extent_z[1]) / 2 + size_px[1] / 2 / zs
    return ViewTransform(x0, xs, z0, zs)


def extent_z(points, axis: str, surface_z: Callable[[float], float | None]):
    """The vertical extent of the columns: in depth mode (0, deepest depth) in metres below
    the collar (the viewer draws z = -depth); in elevation mode (lowest bottom, highest
    collar), leaving out boreholes without any height. ``None`` when nothing can be drawn."""
    if axis == "depth":
        depths = [column_depth(p) for p in points]
        return (0.0, max(depths)) if depths else None
    lows, highs = [], []
    for p in points:
        top = collar_height(p.z_top, None, surface_z(p.s))[0]
        if top is None:
            continue
        lows.append(top - column_depth(p))
        highs.append(top)
    return (min(lows), max(highs)) if lows else None


def spread_texts(layers: list[tuple[float, float]], height: float, lo: float,
                 hi: float) -> list[float | None]:
    """Where each layer text goes in one column: its centre y (px), keeping the order, no two
    closer than ``height``, all inside ``lo..hi``; ``None`` for a text left out. ``layers`` are
    the texts' layers as (y_top, y_bottom), top to bottom. When ``lo..hi`` cannot hold them
    all, the texts of the thinnest layers are left out."""
    keep = list(range(len(layers)))
    while keep and len(keep) * height > hi - lo:
        keep.remove(min(keep, key=lambda i: (abs(layers[i][1] - layers[i][0]), -i)))
    ys = [(layers[i][0] + layers[i][1]) / 2 for i in keep]
    for k in range(len(ys)):
        ys[k] = max(ys[k], lo + height / 2, ys[k - 1] + height if k else ys[k])
    for k in reversed(range(len(ys))):
        ys[k] = min(ys[k], hi - height / 2, ys[k + 1] - height if k + 1 < len(ys) else ys[k])
    for k in range(len(ys)):
        ys[k] = max(ys[k], lo + height / 2)
    out: list[float | None] = [None] * len(layers)
    for i, y in zip(keep, ys):
        out[i] = y
    return out


def even_gap(widths_px: list[float], room_px: float, gap_px: float = 40,
             min_gap_px: float = 12) -> float:
    """The gap between evenly spaced columns that makes them fit ``room_px``, never wider than
    ``gap_px`` nor narrower than ``min_gap_px`` (``gap_px`` for one column or none)."""
    if len(widths_px) < 2:
        return gap_px
    gap = (room_px - sum(widths_px)) / (len(widths_px) - 1)
    return max(min_gap_px, min(gap_px, gap))
