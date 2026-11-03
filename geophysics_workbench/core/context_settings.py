"""Which QGIS layers supply third-party context on a section (QGIS-free).

The settings refer to layers by QGIS layer id, so they are kept in the QGIS project (as JSON),
not in the workbench GeoPackage. ``from_json`` never raises: anything unusable falls back to
the defaults, field by field."""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field, fields

VERSION = 2
MAX_DISTANCE = 1e6                                     # metres; the dialog's spin boxes allow the same


@dataclass
class LineLayerSetting:
    layer_id: str
    label_field: str = ""
    colour: str = ""                  # "#rrggbb"; "" = the layer's own symbol colour
    selected_only: bool = False
    checked: bool | None = None       # None = follow map visibility


@dataclass
class PointLayerSetting:
    layer_id: str
    label_field: str = ""


@dataclass
class BoreholeSetting:
    layer_id: str
    id_field: str
    elevation_field: str = ""
    log_layer_id: str = ""
    log_id_field: str = ""
    top_field: str = ""
    bottom_field: str = ""
    lithology_field: str = ""


@dataclass
class BandSetting:
    layer_id: str
    label_field: str


@dataclass
class ContextSettings:
    line_layers: list = field(default_factory=list)
    point_layers: list = field(default_factory=list)
    borehole: BoreholeSetting | None = None
    band: BandSetting | None = None
    dem_layer_id: str = ""
    buffer: float = 25.0
    near_miss: float = 10.0
    dem_tolerance: float = 1.0

    def to_json(self) -> str:
        data = asdict(self)
        data["version"] = VERSION
        return json.dumps(data)

    @classmethod
    def from_json(cls, text: str) -> "ContextSettings":
        try:
            data = json.loads(text)
        except (TypeError, ValueError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        out = cls()
        out.line_layers = _items(data.get("line_layers"), LineLayerSetting)
        version = data.get("version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 2:
            for item in out.line_layers:                # 0.2.0: every saved line row was ticked
                item.checked = True
        out.point_layers = _items(data.get("point_layers"), PointLayerSetting)
        out.borehole = _item(data.get("borehole"), BoreholeSetting)
        out.band = _item(data.get("band"), BandSetting)
        dem = data.get("dem_layer_id")
        out.dem_layer_id = dem if isinstance(dem, str) else ""
        for name in ("buffer", "near_miss", "dem_tolerance"):
            value = data.get(name)
            if (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value) and 0 <= value <= MAX_DISTANCE):
                setattr(out, name, float(value))
        return out


def _item(data, kind):
    """``kind(**data)`` keeping only known, correctly typed string/bool fields; ``None`` when
    ``data`` is not a dict or lacks a required (non-empty) layer id."""
    if not isinstance(data, dict):
        return None
    kwargs = {}
    for f in fields(kind):
        value = data.get(f.name)
        if f.name == "checked":
            if value is None or isinstance(value, bool):
                kwargs[f.name] = value
            continue
        if f.name == "colour":
            if isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                kwargs[f.name] = value
            continue
        want = bool if f.type in ("bool", bool) else str
        if isinstance(value, want):
            kwargs[f.name] = value
    if not kwargs.get("layer_id"):
        return None
    try:
        return kind(**kwargs)
    except TypeError:                                   # a required field is missing
        return None


def _items(data, kind) -> list:
    if not isinstance(data, list):
        return []
    return [item for item in (_item(d, kind) for d in data) if item is not None]
