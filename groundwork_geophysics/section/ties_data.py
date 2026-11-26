"""Profile ties for the section snapshot: where another profile crosses (or nearly meets)
this one, the columns of its visible models at that point. QGIS-free."""
from __future__ import annotations

from dataclasses import replace
from typing import Callable

import numpy as np

from ..core.context import tie_hits
from ..core.model import Profile
from ..core.ties import Tie, TieColumn
from .data import SectionLayer, layer_name


def tie_column(layer: SectionLayer, s: float) -> TieColumn:
    """``layer``'s column at chainage ``s``, top to bottom. On a shared cell edge
    ``column_at`` returns both neighbours (and may return zero-thickness cuts through a
    corner): zero-thickness entries are dropped, and of identical intervals the first kept."""
    z_top, z_bottom, values = layer.mesh.column_at(s)
    keep = np.flatnonzero(z_top > z_bottom)
    if keep.size:
        _u, first = np.unique(np.column_stack([z_top[keep], z_bottom[keep]]), axis=0,
                              return_index=True)
        keep = keep[np.sort(first)]
    d, scale = layer.dataset, layer.style.scale
    return TieColumn(layer_name(d), z_top[keep].copy(), z_bottom[keep].copy(),
                     values[keep].copy(), None if scale is None else replace(scale),
                     d.quantity, d.unit)


def build_ties(profile_id: str, profiles: list[Profile], near_miss: float,
               layers_of: Callable[[str], list[SectionLayer]]) -> list[Tie]:
    """One Tie per ``tie_hits`` hit of profile ``profile_id`` against each other one of
    ``profiles``, sorted by chainage; ``[]`` when ``profile_id`` is not among them.
    ``layers_of(other_id)`` is called only for profiles that tie; its visible layers with a
    mesh give the columns."""
    profile = next((p for p in profiles if p.id == profile_id), None)
    if profile is None:
        return []
    out = []
    for other in (p for p in profiles if p.id != profile_id):
        hits = tie_hits(profile.xy, other.xy, near_miss)
        if not hits:
            continue
        # models only: measured data and misfit pseudosections are not ground columns
        layers = [la for la in layers_of(other.id) if la.style.visible and la.mesh is not None
                  and la.mesh.readings is None]
        for hit in hits:                        # a shared stretch: one tie at its middle
            out.append(Tie(hit.s, other.id, other.name, hit.s_other, hit.distance,
                           [tie_column(la, hit.s_other) for la in layers], hit.stretch))
    out.sort(key=lambda t: t.s)
    return out
