"""Report plates as plain data, and the fit-to-page maths (no QGIS/Qt).

A plate has stacked section frames; each frame shows one profile with its own look (which
models, their colour scale, display mode and opacity, the interpretation version, boreholes,
field notes, context), kept with the plate so restyling the section panel never changes a
delivered plate. Fit to page: the largest standard scale at which the frame's chainage range
fits its width, and the largest standard VE at which its depth range fits its height; frames
of the same profile share scale, VE and range so features line up."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field

#: standard scales, close enough together that a fitted section fills most of its frame
#: (a 1:100 -> 1:200 jump left half of the frame empty)
SCALES = (100, 125, 150, 200, 250, 300, 400, 500, 750, 1000, 1250, 1500, 2000, 2500, 3000,
          4000, 5000, 7500, 10000, 12500, 15000, 20000, 25000, 30000, 40000, 50000)
VES = (1.0, 1.25, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 15.0, 20.0)


@dataclass
class ModelLook:
    dataset_id: str
    visible: bool = True
    opacity: float = 1.0
    scale: dict | None = None        # ColorScale as a dict (cmap, vmin, vmax, log); None = auto
    mode: str = "cells"
    #: display settings as in the section's Display dialog (None = automatic)
    contour_step: float | None = None
    grid_cell: float | None = None
    fade_coverage: bool = False
    coverage_threshold: float | None = None
    fade_mode: str = "fade"
    shown: str | None = None                            # readings: misfit/measured/calculated
    contour_major: list = field(default_factory=list)   # typed levels (model's unit)
    contour_minor: list = field(default_factory=list)
    #: how the smooth field is gridded (``Interpolation.to_dict``); None = linear
    interpolation: dict | None = None


@dataclass
class FrameLook:
    models: list = field(default_factory=list)          # [ModelLook]
    interp_version: str | None = None                   # None: the latest version
    boreholes: bool = True
    field_notes: bool = True
    context: bool = True


@dataclass
class FrameSpec:
    frame_id: str
    profile_id: str
    look: FrameLook
    s_from: float | None = None
    s_to: float | None = None
    scale: int | None = None        # set by the user: kept, the frame stops fitting itself
    ve: float | None = None


@dataclass
class PlateSpec:
    plate_id: str
    number: str
    title: str
    template: str
    frames: list = field(default_factory=list)          # [FrameSpec]


# -- fit to page ---------------------------------------------------------------------------
def nice_scale(range_m: float, width_mm: float) -> tuple[int, bool]:
    """The largest standard scale (smallest denominator) at which ``range_m`` metres fit
    ``width_mm``; ``(50000, False)`` when even that does not fit."""
    if width_mm <= 0:
        return SCALES[-1], False
    for scale in SCALES:
        if max(range_m, 0.0) * 1000.0 / scale <= width_mm:
            return scale, True
    return SCALES[-1], False


def nice_ve(z_range_m: float, height_mm: float, scale: int) -> float:
    """The largest standard vertical exaggeration at which ``z_range_m`` fits ``height_mm``
    at 1:``scale`` (1 when it does not fit even unexaggerated)."""
    if z_range_m <= 0:
        return VES[-1]
    most = height_mm * scale / (z_range_m * 1000.0)
    return max((v for v in VES if v <= most), default=VES[0])


def frame_fits(range_m: float, z_range_m: float, size_mm, scale: float, ve: float) -> bool:
    """Whether ``range_m`` x ``z_range_m`` fits a frame of ``size_mm`` (width, height) at
    1:``scale`` with vertical exaggeration ``ve``."""
    width, height = size_mm
    return (abs(range_m) * 1000.0 / scale <= width + 1e-6
            and abs(z_range_m) * 1000.0 * ve / scale <= height + 1e-6)


def stack_fit(frames: list, extents: dict, sizes_mm: list) -> list[tuple]:
    """Per frame ``(scale, ve, s0, s1)``. ``extents[frame_id] = (s0, s1, z0, z1)`` of the
    frame's data; ``sizes_mm`` the frames' (width, height). Frames of one profile share
    scale, VE and range (the union of their data, or the range a frame sets); a scale or VE
    the user set on one of them is used for all."""
    groups: dict[str, list[int]] = {}
    for i, f in enumerate(frames):
        groups.setdefault(f.profile_id, []).append(i)
    out: list = [None] * len(frames)
    for indices in groups.values():
        members = [frames[i] for i in indices]
        set_range = next(((f.s_from, f.s_to) for f in members
                          if f.s_from is not None and f.s_to is not None), None)
        exts = [extents.get(f.frame_id) for f in members if extents.get(f.frame_id)]
        s0 = set_range[0] if set_range else min((e[0] for e in exts), default=0.0)
        s1 = set_range[1] if set_range else max((e[1] for e in exts), default=0.0)
        z0 = min((e[2] for e in exts), default=0.0)
        z1 = max((e[3] for e in exts), default=0.0)
        width = min(sizes_mm[i][0] for i in indices)
        height = min(sizes_mm[i][1] for i in indices)
        # a scale at which the range fits the width AND the depth fits the height at VE 1
        # (a finer scale would cut the depth off); the user's own scale is kept
        scale = next((f.scale for f in members if f.scale), None) or \
            max(nice_scale(abs(s1 - s0), width)[0], nice_scale(abs(z1 - z0), height)[0])
        ve = next((f.ve for f in members if f.ve), None) or nice_ve(abs(z1 - z0), height, scale)
        for i in indices:
            out[i] = (scale, ve, s0, s1)
    return out


# -- JSON (project entry) ------------------------------------------------------------------
def plates_to_json(plates: list) -> str:
    return json.dumps([asdict(p) for p in plates])


def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) \
        and math.isfinite(v) else None


def _model(d) -> ModelLook | None:
    if not isinstance(d, dict) or not isinstance(d.get("dataset_id"), str):
        return None
    scale = d.get("scale") if isinstance(d.get("scale"), dict) else None
    def text(key, default):
        return d.get(key) if isinstance(d.get(key), str) else default

    return ModelLook(d["dataset_id"], bool(d.get("visible", True)),
                     _num(d.get("opacity")) if _num(d.get("opacity")) is not None else 1.0,
                     scale, text("mode", "cells"), _num(d.get("contour_step")),
                     _num(d.get("grid_cell")), bool(d.get("fade_coverage", False)),
                     _num(d.get("coverage_threshold")), text("fade_mode", "fade"),
                     text("shown", None), _levels(d.get("contour_major")),
                     _levels(d.get("contour_minor")),
                     d.get("interpolation") if isinstance(d.get("interpolation"), dict)
                     else None)


#: a model's look from its stored dict, or None when unusable (the section styles use it too)
model_look_from_dict = _model


def _levels(v) -> list:
    return [x for x in (_num(i) for i in v) if x is not None] if isinstance(v, list) else []


def _look(d) -> FrameLook:
    d = d if isinstance(d, dict) else {}
    models = [m for m in (_model(x) for x in d.get("models") or []) if m is not None]
    version = d.get("interp_version") if isinstance(d.get("interp_version"), str) else None
    return FrameLook(models, version, bool(d.get("boreholes", True)),
                     bool(d.get("field_notes", True)), bool(d.get("context", True)))


def _frame(d) -> FrameSpec | None:
    if not isinstance(d, dict) or not all(isinstance(d.get(k), str)
                                          for k in ("frame_id", "profile_id")):
        return None
    scale = d.get("scale")
    return FrameSpec(d["frame_id"], d["profile_id"], _look(d.get("look")), _num(d.get("s_from")),
                     _num(d.get("s_to")), int(scale) if _num(scale) else None, _num(d.get("ve")))


def plates_from_json(text: str) -> list[PlateSpec]:
    """Plates from the project entry; anything unusable is left out (never raises)."""
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return []
    out = []
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict) or not all(isinstance(d.get(k), str) for k in
                                              ("plate_id", "number", "title", "template")):
            continue
        frames = [f for f in (_frame(x) for x in d.get("frames") or []) if f is not None]
        out.append(PlateSpec(d["plate_id"], d["number"], d["title"], d["template"], frames))
    return out
