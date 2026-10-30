"""Context lines for the section panel's readout (the dock supplies the plot scale)."""
from __future__ import annotations

from .context_readout import context_hits
from .topography import station_line

TOLERANCE_PX = 4.0
COLUMN_MM = 2.5         # borehole column width, as drawn by context_render_points
STRIP_MM = 3.0          # tie strip width, beside the tie line (see context_readout.strip_start)


def context_lines(dock, s: float, z: float) -> list[str]:
    """What third-party context lies under (s, z) of the dock's open profile; the canvas
    distance is forward chainage, as is the provider's context."""
    dock._current_layers()                  # fills the cached drawn topography
    if dock._ctx is None:                   # cached like _layers: no store reads per mouse move
        pid = dock._profile.id
        dock._ctx = (dock.provider.context(pid),
                     station_line(dock.provider.store.station_sets(pid)))
    ctx, stations = dock._ctx
    if ctx is None:
        return []
    rng, area = dock.canvas.visibleDistanceRange(), dock.canvas.plotArea()
    if area.width() <= 0 or rng.upper() <= rng.lower():
        return []
    per_px = (rng.upper() - rng.lower()) / area.width()
    per_mm = per_px * dock.logicalDpiX() / 25.4
    return context_hits(ctx, s, z, TOLERANCE_PX * per_px, COLUMN_MM / 2 * per_mm,
                        STRIP_MM * per_mm, surface=dock._topo, stations=stations)
