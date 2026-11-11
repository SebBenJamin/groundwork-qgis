"""Context lines for the section panel's readout (the dock supplies the plot scale)."""
from __future__ import annotations

from .context_readout import context_hits
from .topography import station_line

TOLERANCE_PX = 4.0
COLUMN_MM = 2.5         # borehole column width without an entry (context_render_points)
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
    return context_hits(ctx, s, z, TOLERANCE_PX * per_px, half_widths(ctx, per_px, per_mm),
                        STRIP_MM * per_mm, surface=dock._topo, stations=stations,
                        right_extent_s=right_extents(ctx, per_px))


def right_extents(ctx, per_px: float):
    """How far a borehole's curve tracks and layer text reach right of its column, in
    metres of chainage, per point (as drawn)."""
    from .context_render_points import right_extent_px
    return lambda p: right_extent_px(ctx, p) * per_px


def half_widths(ctx, per_px: float, per_mm: float):
    """A borehole column's half-width in metres of chainage, per point (as drawn)."""
    def half(p):
        view = ctx.borehole_views.get(p.entry)
        return view.column_px / 2 * per_px if view is not None else COLUMN_MM / 2 * per_mm
    return half


def borehole_hit(dock, s: float, z: float):
    """(entry, label) of the borehole column under (s, z) of the open profile, or ``None``."""
    from .context_readout import borehole_at
    rng, area = dock.canvas.visibleDistanceRange(), dock.canvas.plotArea()
    if area.width() <= 0 or rng.upper() <= rng.lower():
        return None
    per_px = (rng.upper() - rng.lower()) / area.width()
    per_mm = per_px * dock.logicalDpiX() / 25.4
    context_lines(dock, s, z)                   # fills the cached context
    if dock._ctx is None or dock._ctx[0] is None:
        return None
    p = borehole_at(dock._ctx[0], s, z, half_widths(dock._ctx[0], per_px, per_mm), dock._topo,
                    right_extents(dock._ctx[0], per_px))
    return None if p is None else (p.entry, p.label)


def click_details(dock, s: float, z: float) -> list[str]:
    """What a click at (s, z) hits: a borehole column (full log) and interpretation pieces
    (all attributes, including the user's own fields)."""
    from .context_readout import borehole_details
    from .interp_edit import pick_piece

    lines: list[str] = []
    rng, area = dock.canvas.visibleDistanceRange(), dock.canvas.plotArea()
    erng = dock.canvas.visibleElevationRange()
    if area.width() <= 0 or area.height() <= 0 or rng.upper() <= rng.lower():
        return lines
    per_px = (rng.upper() - rng.lower()) / area.width()
    per_px_z = (erng.upper() - erng.lower()) / area.height()
    per_mm = per_px * dock.logicalDpiX() / 25.4
    context_lines(dock, s, z)                   # fills the cached context
    if dock._ctx is not None and dock._ctx[0] is not None:
        lines += borehole_details(dock._ctx[0], s, z,
                                  half_widths(dock._ctx[0], per_px, per_mm), dock._topo,
                                  right_extents(dock._ctx[0], per_px))
    store = dock.provider.store
    version = dock.provider.shown_interp_version()
    if version is not None:
        pieces = store.pieces(version, dock._profile.id)
        hit = pick_piece(pieces, s, z, 3 * per_px * dock.logicalDpiX() / 25.4,
                         3 * per_px_z * dock.logicalDpiX() / 25.4)
        if hit is not None:
            feat = next((f for f in store.features(version) if f.id == hit.piece.feature_id),
                        None)
            if feat is not None:
                if lines:
                    lines.append("")
                title = " · ".join(x for x in (feat.name, feat.type) if x) or "(unnamed)"
                lines.append(f"Interpretation {title} ({hit.piece.kind})")
                for label, value in (("Confidence", feat.confidence), ("Note", feat.note),
                                     ("Author", feat.author), ("Modified", feat.modified)):
                    if value:
                        lines.append(f"  {label}: {value}")
                for k, v in feat.extra.items():
                    if v not in (None, ""):
                        lines.append(f"  {k}: {v}")
    return lines
