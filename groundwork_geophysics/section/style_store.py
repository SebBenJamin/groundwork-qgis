"""The section styles of the models (colour scale, display mode, contours, interpolation,
coverage fade, opacity, shown or not; for reflection sections the clip and the display
options) and the drawing order of each profile's layers, kept in the QGIS project so they
survive saving and reopening; a style copied from one model to every model of the same
method."""
from __future__ import annotations

import json
from dataclasses import asdict, replace

from ..core.colors import ColorScale
from ..core.interpolators import Interpolation
from ..core.plates import ModelLook, model_look_from_dict
from ..core.trace_section import DisplayGain
from ..ids import LEGACY_ID

SCOPE = LEGACY_ID
STYLES_KEY = "section_styles"
#: profile id -> its dataset ids in drawing order, bottom first (JSON object)
ORDER_KEY = "section_layer_order"


def look_of(dataset_id: str, style) -> ModelLook:
    """``style`` (a ``LayerStyle``) as a ``ModelLook`` (plain data, as plates keep it)."""
    return ModelLook(dataset_id, style.visible, style.opacity,
                     asdict(style.scale) if style.scale is not None else None,
                     style.mode, style.contour_step, style.grid_cell,
                     style.fade_coverage, style.coverage_threshold, style.fade_mode,
                     style.shown, list(style.contour_major), list(style.contour_minor),
                     None if style.interpolation.is_linear else style.interpolation.to_dict(),
                     style.clip_percent,
                     style.gain.to_dict() if style.gain.active() or style.gain.show_muted
                     else None, style.contour_colour, style.contour_width)


def styled(style, look: ModelLook):
    """``style`` with what ``look`` says (a stored scale that is no longer valid: the
    style's own)."""
    scale = style.scale
    if look.scale:
        try:
            scale = ColorScale(**look.scale)
        except (TypeError, ValueError):
            pass
    return replace(style, visible=look.visible, opacity=look.opacity, mode=look.mode,
                   scale=scale, contour_step=look.contour_step,
                   contour_major=tuple(look.contour_major),
                   contour_minor=tuple(look.contour_minor), grid_cell=look.grid_cell,
                   interpolation=Interpolation.from_dict(look.interpolation),
                   fade_coverage=look.fade_coverage,
                   coverage_threshold=look.coverage_threshold, fade_mode=look.fade_mode,
                   shown=look.shown if look.shown is not None else style.shown,
                   clip_percent=look.clip_percent, gain=DisplayGain.from_dict(look.gain),
                   contour_colour=look.contour_colour, contour_width=look.contour_width)


def styles_to_json(styles: dict) -> str:
    return json.dumps([asdict(look_of(i, s)) for i, s in sorted(styles.items())])


def styles_from_json(text: str) -> dict:
    """dataset id -> ``LayerStyle``; anything unusable is left out (never raises)."""
    from .data import LayerStyle
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    out = {}
    for d in data if isinstance(data, list) else []:
        look = model_look_from_dict(d)
        if look is not None:
            out[look.dataset_id] = styled(LayerStyle(), look)
    return out


def save_styles(project, styles: dict) -> None:
    """Write ``styles`` into ``project`` (marks it changed only when they changed)."""
    text = styles_to_json(styles)
    if project.readEntry(SCOPE, STYLES_KEY, "")[0] != text:
        project.writeEntry(SCOPE, STYLES_KEY, text)


def load_styles(project) -> dict:
    return styles_from_json(project.readEntry(SCOPE, STYLES_KEY, "")[0])


def layer_orders_to_json(orders: dict) -> str:
    """profile id -> dataset ids in drawing order, bottom first (profiles without one left
    out)."""
    return json.dumps({k: list(v) for k, v in sorted(orders.items()) if v})


def layer_orders_from_json(text: str) -> dict:
    """profile id -> dataset ids, bottom first; anything unusable is left out (never
    raises). An older project has no entry: no order, layers drawn as they were added."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {k: list(v) for k, v in data.items()
            if isinstance(k, str) and isinstance(v, list) and v
            and all(isinstance(i, str) for i in v)}


def save_layer_orders(project, orders: dict) -> None:
    """Write the layer orders into ``project`` beside the styles (marks it changed only when
    they changed)."""
    text = layer_orders_to_json(orders)
    if project.readEntry(SCOPE, ORDER_KEY, "{}")[0] != text:
        project.writeEntry(SCOPE, ORDER_KEY, text)


def load_layer_orders(project) -> dict:
    return layer_orders_from_json(project.readEntry(SCOPE, ORDER_KEY, "")[0])


def same_method(store, dataset_id: str) -> list:
    """The other datasets, on every profile, of the same method (dataset type) and the same
    quantity and unit as ``dataset_id``: an ERT model's style never goes to a refraction
    model."""
    datasets = [d for p in store.profiles() for d in store.datasets(p.id)]
    source = next((d for d in datasets if d.id == dataset_id), None)
    if source is None:
        return []
    return [d for d in datasets if d.id != dataset_id and d.kind == source.kind
            and d.quantity == source.quantity and d.unit == source.unit]


def applied(source, target):
    """``target`` (a ``LayerStyle``) with ``source``'s look; whether it is shown stays."""
    copy = replace(source, scale=None if source.scale is None else replace(source.scale))
    return replace(copy, visible=target.visible)
