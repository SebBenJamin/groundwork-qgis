"""Which QGIS layers supply third-party context on a section (QGIS-free).

The settings refer to layers by QGIS layer id, so they are kept in the QGIS project (as JSON),
not in the workbench GeoPackage. ``from_json`` never raises: anything unusable falls back to
the defaults, field by field."""
from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field, fields

VERSION = 4
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
    depth_field: str = ""               # numeric field: draw a stick this deep (m)


@dataclass
class CurveField:
    field: str
    unit: str = ""


@dataclass
class CurveTableSetting:
    """A table of log curves: one row per depth (metres below the collar), linked by id."""
    layer_id: str
    id_field: str = ""
    depth_field: str = ""
    curves: list = field(default_factory=list)          # [CurveField]


def curve_key(layer_id: str, field_name: str) -> str:
    """The key of one curve (a value field of a curve table) in styles and section options."""
    return f"{layer_id}:{field_name}"


#: allowed ranges of the section options; values outside fall back to the default
COLUMN_PX_RANGE = (6, 80)
OPACITY_RANGE = (0.1, 1.0)


@dataclass
class BoreholeSetting:
    layer_id: str
    id_field: str
    elevation_field: str = ""
    log_layer_id: str = ""
    log_id_field: str = ""
    top_field: str = ""
    bottom_field: str = ""
    lithology_field: str = ""           # the interval's text (shown as layer text)
    total_depth_field: str = ""         # optional: depth of a borehole without intervals
    curve_tables: list = field(default_factory=list)    # [CurveTableSetting]
    # how the section draws this entry's columns
    column_px: int = 16
    opacity: float = 1.0
    layer_text: bool = False
    section_curves: list = field(default_factory=list)  # [curve_key]


@dataclass
class BandSetting:
    """One strip of surface polygons (geology, soil, land use) above the ground."""
    layer_id: str
    label_field: str
    title: str = ""                   # "" = the layer's name
    shown: bool = True


@dataclass
class ContextSettings:
    line_layers: list = field(default_factory=list)
    point_layers: list = field(default_factory=list)
    boreholes: list = field(default_factory=list)       # [BoreholeSetting]
    bands: list = field(default_factory=list)          # [BandSetting], top strip first
    dem_layer_id: str = ""
    buffer: float = 25.0
    near_miss: float = 10.0
    dem_tolerance: float = 1.0

    def shown_bands(self) -> list:
        return [b for b in self.bands if b.shown]

    def to_json(self) -> str:
        data = asdict(self)
        # the first entry also under the 0.2-0.4 key, so an older plugin still shows it
        data["borehole"] = data["boreholes"][0] if data["boreholes"] else None
        shown = self.shown_bands()                      # likewise the first shown strip as ``band``
        data["band"] = asdict(shown[0]) if shown else None
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
        if isinstance(data.get("boreholes"), list):
            out.boreholes = _items(data["boreholes"], BoreholeSetting)
        else:                                           # v2: one borehole layer
            legacy = _item(data.get("borehole"), BoreholeSetting)
            out.boreholes = [legacy] if legacy is not None else []
        if isinstance(data.get("bands"), list):
            out.bands = _items(data["bands"], BandSetting)
        else:                                           # v3: one band
            legacy_band = _item(data.get("band"), BandSetting)
            out.bands = [legacy_band] if legacy_band is not None else []
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
        if f.name == "column_px":
            if _number_in(value, COLUMN_PX_RANGE):
                kwargs[f.name] = int(value)
            continue
        if f.name == "opacity":
            if _number_in(value, OPACITY_RANGE):
                kwargs[f.name] = float(value)
            continue
        if f.name == "curve_tables":
            kwargs[f.name] = _items(value, CurveTableSetting)
            continue
        if f.name == "curves":
            kwargs[f.name] = [c for c in (_curve(v) for v in (value or [])
                                          if isinstance(value, list)) if c is not None]
            continue
        if f.name == "section_curves":
            kwargs[f.name] = [v for v in value if isinstance(v, str)] \
                    if isinstance(value, list) else []
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


def _number_in(value, bounds) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and bounds[0] <= value <= bounds[1])


def _curve(data) -> CurveField | None:
    if not isinstance(data, dict) or not isinstance(data.get("field"), str)             or not data["field"]:
        return None
    unit = data.get("unit")
    return CurveField(data["field"], unit if isinstance(unit, str) else "")


def _items(data, kind) -> list:
    if not isinstance(data, list):
        return []
    return [item for item in (_item(d, kind) for d in data) if item is not None]
