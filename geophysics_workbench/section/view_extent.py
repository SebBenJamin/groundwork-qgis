"""What the section panel's "Zoom Full" fits: the box of the data, topography, station
heights and context (borehole logs, tie strips), and the pixels the geology band and the
context labels need above it. The pixel figures come from ``context_render``, which draws
them, so the view and the drawing cannot drift apart."""
from __future__ import annotations

import numpy as np
from qgis.PyQt.QtGui import QFont, QFontMetrics

from .context_render import context_headroom_px, context_z_values, label_font_px
from .topography import station_line

Extent = tuple[float, float, float, float]


def _drawn_context(dock):
    """The open profile's context as the section draws it: a local section leaves out the
    DEM line and the boreholes (``data.without_heights``)."""
    from .data import without_heights
    pid = dock._profile.id
    ctx = dock.provider.context(pid)
    if ctx is not None and dock.provider.is_local(pid):
        ctx = without_heights(ctx)[0]
    return ctx


def data_extent(dock) -> Extent:
    """(s0, s1, z0, z1) of the dock's open profile, in forward chainage and elevation."""
    profile = dock._profile
    s = [0.0, profile.chainage.length]
    z = []
    for layer in dock._current_layers():                 # also fills dock._topo
        if layer.mesh is not None:
            s0, s1, z0, z1 = layer.mesh.bounds()
            s += [s0, s1]
            z += [z0, z1]
    topo = dock._topo
    if topo is not None and len(topo[0]):
        s += [float(topo[0].min()), float(topo[0].max())]
        z += [float(topo[1].min()), float(topo[1].max())]
    stations = station_line(dock.provider.store.station_sets(profile.id))
    if stations is not None and len(stations[1]):        # the ticks sit at measured heights
        z += [float(stations[1].min()), float(stations[1].max())]
    z += context_z_values(_drawn_context(dock), topo)
    z = [v for v in z if np.isfinite(v)] or [-10.0, 0.0]
    zmin, zmax = min(z), max(z)
    if zmax - zmin < 1.0:
        zmin, zmax = zmin - 0.5, zmax + 0.5
    return min(s), max(s), zmin, zmax


def headroom_px(dock) -> float:
    """Pixels above the data top for the geology band and the label rows; 0 without
    context to draw there."""
    ctx = _drawn_context(dock)
    if ctx is None:
        return 0.0
    from .field_notes_render import lanes_px
    labels = bool(ctx.crossings or ctx.points or ctx.ties or ctx.field_notes)
    if not (labels or ctx.band):
        return 0.0
    px_per_mm = dock.canvas.logicalDpiY() / 25.4
    font = QFont(dock.canvas.font())
    font.setPixelSize(label_font_px(px_per_mm))
    return context_headroom_px(px_per_mm, QFontMetrics(font).height(), labels) + \
        lanes_px(px_per_mm, ctx.field_notes)
