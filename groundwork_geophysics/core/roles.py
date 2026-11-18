"""Column roles of a free-form text table and their first guesses (no QGIS/Qt).

A model table has a position (distance along the line, or easting and northing), a vertical
column with its meaning and a value column with its quantity; a positions table has easting
and northing and optionally elevation, number and in-line distance. ``guess_*`` give the first
guess a dialog shows; ``problems`` says what the user still has to choose.

A table is anything with ``names``, ``n_columns``, ``numeric(col)`` and ``is_numeric(col)``,
as ``readers.texttable.TextTable`` has. Header names are matched case-insensitively on the
whole word after removing a trailing unit in brackets ("Easting [m]", "Northing (m)") and
everything but letters, digits and ``_``.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

import numpy as np

NONE = -1                                   # "(none)" entry of the optional column combos
_HEADER_NAMES = {
    "number": {"nr", "no", "num", "number", "electrode", "elektrode", "station", "id"},
    "x": {"x", "east", "easting", "rechts", "rechtswert", "e"},
    "y": {"y", "north", "northing", "hoch", "hochwert", "n"},
    "z": {"z", "elev", "elevation", "height", "höhe", "hoehe", "alt", "altitude", "h"},
    "distance": {"distance", "dist", "station", "profil", "profilmeter", "x"},
    "depth": {"depth", "tiefe", "d"},
    "value": {"rho", "res", "resistivity", "widerstand", "r"},
    "inline": {"inline", "chainage"},
}
_STATION_ROLES = ("number", "x", "y", "z")
# in a model table a bare x is the distance and a bare y a vertical candidate, not map axes
_EASTING = _HEADER_NAMES["x"] - {"x"}
_NORTHING = _HEADER_NAMES["y"] - {"y"}
_ELEVATION = _HEADER_NAMES["z"] - {"z"}     # a bare z says nothing about its meaning

VERTICAL_KINDS = (("Elevation", "elevation"), ("Depth below surface", "depth"),
                  ("Local height", "local"))
QUANTITIES = (("Resistivity (ohm.m)", "resistivity", "ohm.m"),
              ("P-wave velocity (m/s)", "p_velocity", "m/s"), ("Other", "", ""))
POSITIONS = ("distance", "map")
WGS84 = "EPSG:4326"

_COORDINATE = 10_000.0                      # above this, a pair of columns looks projected
_LOG_TOL = 0.02                             # as readers.base.is_log10_pair


_UNIT = re.compile(r"\s*(\[[^\]]*\]|\([^)]*\))\s*$")     # "Easting [m]", "Northing (m)"


def _word(token: str) -> str:
    """The header name as matched: a trailing bracketed unit removed, lower case, letters,
    digits and ``_`` only."""
    return re.sub(r"[^\wäöüß]", "", _UNIT.sub("", token).lower())


def _is_depth_name(word: str) -> bool:
    return word in _HEADER_NAMES["depth"] or "depth" in word or "tiefe" in word


def guess_columns(header: list[str] | None, ncols: int) -> dict[str, int]:
    """Column index per role (number, x, y, z) from header names, else by position.
    A positional guess never reuses a column that a header name claimed for another role."""
    if ncols >= 4:
        guess = {"number": 0, "x": 1, "y": 2, "z": 3}
    else:
        guess = {"number": NONE, "x": 0, "y": min(1, ncols - 1), "z": 2 if ncols == 3 else NONE}
    if header:
        matched = {}
        for i, token in enumerate(header):
            word = _word(token)
            for role in _STATION_ROLES:
                if word in _HEADER_NAMES[role] and role not in matched:
                    matched[role] = i
        claimed = set(matched.values())
        for role in guess:
            if role in matched:
                guess[role] = matched[role]
            elif guess[role] in claimed:
                guess[role] = NONE
    return guess


def looks_like_degrees(xy: np.ndarray) -> bool:
    """Longitude/latitude rather than projected metres: every |x| <= 180, every |y| <= 90
    and the whole set spans less than 1 unit."""
    xy = np.asarray(xy, dtype=float)[:, :2]
    if not len(xy) or not np.all(np.isfinite(xy)):
        return False
    return bool(np.all(np.abs(xy[:, 0]) <= 180) and np.all(np.abs(xy[:, 1]) <= 90)
                and np.ptp(xy, axis=0).max() < 1.0)


def _index(v) -> int | None:
    return None if v is None else int(v)


def _review(table, roles) -> list[str]:
    """Messages for ``roles``: (label, column or None, message when missing or None when
    the role is optional, whether the role's other settings are complete)."""
    out: list[str] = []
    seen: list[tuple[str, int]] = []

    def note(msg):
        if msg not in out:
            out.append(msg)

    for label, col, missing, complete in roles:
        if col is None or not 0 <= col < table.n_columns:
            if missing:
                note(missing)
            continue
        if not table.is_numeric(col):
            note(f"The {label} column ({table.names[col]}) cannot be a text column")
        else:
            other = next((lab for lab, c in seen if c == col), None)
            if other:
                note(f"The {label} column cannot also be the {other} column")
        seen.append((label, col))
        if not complete:
            note(missing)
    return out


@dataclass(frozen=True)
class ModelColumns:
    position: str = "distance"          # "distance" (along the line) or "map"
    distance: int | None = None
    easting: int | None = None
    northing: int | None = None
    crs: str = ""                       # of easting and northing; "" = the project CRS
    vertical: int | None = None
    vertical_kind: str = ""             # a value of VERTICAL_KINDS; "" = not chosen
    value: int | None = None
    quantity: str = "resistivity"       # "" until an "Other" quantity is named
    unit: str = "ohm.m"
    log10: bool = False
    #: optional per-cell coverage (as in the file, often log): fades unresolved cells
    coverage: int | None = None

    def __post_init__(self):
        if self.position not in POSITIONS:
            raise ValueError(f"unknown position {self.position!r}")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ModelColumns":
        return cls(position=str(d.get("position", "distance")),
                   distance=_index(d.get("distance")), easting=_index(d.get("easting")),
                   northing=_index(d.get("northing")), crs=str(d.get("crs", "")),
                   vertical=_index(d.get("vertical")),
                   vertical_kind=str(d.get("vertical_kind", "")),
                   value=_index(d.get("value")),
                   quantity=str(d.get("quantity", "resistivity")),
                   unit=str(d.get("unit", "ohm.m")), log10=bool(d.get("log10", False)),
                   coverage=_index(d.get("coverage")))

    def _roles(self) -> list[tuple[str, int | None]]:
        if self.position == "map":
            pos = [("easting", self.easting), ("northing", self.northing)]
        else:
            pos = [("distance", self.distance)]
        return pos + [("vertical", self.vertical), ("value", self.value)]

    def used(self) -> list[int]:
        """The assigned columns: position first, then vertical and value; the optional
        coverage last."""
        out = [c for _, c in self._roles() if c is not None]
        return out + ([self.coverage] if self.coverage is not None else [])

    def problems(self, table) -> list[str]:
        """What is missing or wrong, as messages for the user; empty when complete."""
        missing = {"easting": "Choose the easting and northing columns",
                   "northing": "Choose the easting and northing columns",
                   "distance": "Choose the distance column",
                   "vertical": "Choose the vertical column and what it means",
                   "value": "Choose the value column"}
        kinds = {k for _, k in VERTICAL_KINDS}
        out = _review(table, [(label, col, missing[label],
                               label != "vertical" or self.vertical_kind in kinds)
                              for label, col in self._roles()])
        if not self.quantity.strip():
            out.append("Type the name of the quantity")
        return out


@dataclass(frozen=True)
class PositionColumns:
    easting: int | None
    northing: int | None
    crs: str = ""                       # "" = the project CRS
    elevation: int | None = None
    number: int | None = None
    inline: int | None = None           # distance along the line, in the data's metres

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PositionColumns":
        return cls(easting=_index(d.get("easting")), northing=_index(d.get("northing")),
                   crs=str(d.get("crs", "")), elevation=_index(d.get("elevation")),
                   number=_index(d.get("number")), inline=_index(d.get("inline")))

    def _roles(self) -> list[tuple[str, int | None]]:
        return [("easting", self.easting), ("northing", self.northing),
                ("elevation", self.elevation), ("number", self.number),
                ("in-line distance", self.inline)]

    def used(self) -> list[int]:
        """The assigned columns: easting, northing, elevation, number, in-line distance."""
        return [c for _, c in self._roles() if c is not None]

    def names_number(self, table) -> bool:
        """The number column holds text (all names, or numbers with a few named points such
        as ``Base``): the numbers are read from point names, so no row is dropped unseen."""
        n = self.number
        return n is not None and 0 <= n < table.n_columns and table.has_text(n)

    def problems(self, table) -> list[str]:
        """What is missing or wrong, as messages for the user; empty when complete. Only the
        number column may be a text column (of point names)."""
        required = "Choose the easting and northing columns"
        names = self.names_number(table)
        return _review(table, [(label, col, required if label in ("easting", "northing")
                                else None, True) for label, col in self._roles()
                               if not (names and label == "number")])


class _Columns:
    """What the guesses need to know about each column of a table."""

    def __init__(self, table):
        self.words = [_word(n) for n in table.names]
        self.values = [table.numeric(c) for c in range(table.n_columns)]
        self.numeric = [c for c in range(table.n_columns) if table.is_numeric(c)]

    def finite(self, c: int) -> np.ndarray:
        v = self.values[c]
        return v[np.isfinite(v)]

    def varies(self, c: int) -> bool:
        v = self.finite(c)
        return bool(v.size) and float(np.ptp(v)) > 0

    def coordinate(self, c: int) -> bool:
        v = self.finite(c)
        return bool(v.size) and bool(np.all(np.abs(v) > _COORDINATE))

    def whole(self, c: int) -> bool:
        v = self.finite(c)
        return bool(v.size) and bool(np.all(v == np.round(v)))

    def named(self, names, cols, taken=()) -> int | None:
        return next((c for c in cols if c not in taken and self.words[c] in names), None)

    def log_pairs(self) -> dict[int, int]:
        """log10 column -> its linear column, for each numeric column that is log10 of a
        varying positive column in every row (at least two) where both hold a number."""
        pairs: dict[int, int] = {}
        for lin in self.numeric:
            if lin in pairs or not self.varies(lin):
                continue
            v = self.values[lin]
            for lg in self.numeric:
                if lg == lin or lg in pairs or lg in pairs.values():
                    continue
                w = self.values[lg]
                ok = np.isfinite(v) & (v > 0) & np.isfinite(w)
                if ok.sum() >= 2 and np.all(np.abs(np.log10(v[ok]) - w[ok]) <= _LOG_TOL):
                    pairs[lg] = lin
                    break
        return pairs

    def map_pair(self, east, north, cols) -> tuple[int | None, int | None]:
        """Easting and northing: the named ones, completed from ``cols`` whose values look
        like projected coordinates. (None, None) unless both exist and not both are fixed."""
        coords = [c for c in cols if self.coordinate(c) and c not in (east, north)]
        if east is None and coords:
            east = coords.pop(0)
        if north is None and coords:
            north = coords.pop(0)
        if east is None or north is None or east == north:
            return None, None
        if not (self.varies(east) or self.varies(north)):
            return None, None
        return east, north

    def crs(self, east: int | None, north: int | None) -> str:
        """EPSG:4326 when the easting and northing look like degrees, else ""."""
        if east is None or north is None:
            return ""
        xy = np.column_stack([self.values[east], self.values[north]])
        xy = xy[np.isfinite(xy).all(axis=1)]
        return WGS84 if looks_like_degrees(xy) else ""

    def vertical_kind(self, c: int) -> str:
        """The meaning of vertical column ``c``: "depth" or "elevation" from its name; without
        a name hint "depth" when every value is >= 0 and the smallest is nearer 0 than the
        spread; otherwise "" (the user chooses)."""
        word = self.words[c]
        if _is_depth_name(word):
            return "depth"
        if word in _ELEVATION:
            return "elevation"
        v = self.finite(c)
        lo, hi = float(v.min()), float(v.max())
        return "depth" if 0 <= lo <= hi - lo else ""


def guess_model_columns(table) -> ModelColumns:
    """First guess of a model table's roles. Header names first; then by content: a
    constant column is never a position or vertical, of a log10 pair the linear column is
    the value, and two columns of projected-looking coordinates suggest map coordinates.
    Unnamed roles are filled in column order: position first, value last, vertical between."""
    cols = _Columns(table)
    logs = cols.log_pairs()
    free = [c for c in cols.numeric if c not in logs and cols.varies(c)]
    taken: set[int] = set()

    value = cols.named(_HEADER_NAMES["value"], cols.numeric)
    value = logs.get(value, value)
    if value is not None:
        taken.add(value)
    east, north = cols.map_pair(cols.named(_EASTING, cols.numeric, taken),
                                cols.named(_NORTHING, cols.numeric, taken),
                                [c for c in cols.numeric if c not in taken and c not in logs])
    position = "distance" if east is None else "map"
    distance = None
    if position == "map":
        taken |= {east, north}
    else:
        distance = cols.named(_HEADER_NAMES["distance"], free, taken)
        if distance is not None:
            taken.add(distance)
    vertical = next((c for c in free if c not in taken and _is_depth_name(cols.words[c])), None)
    for names in (_HEADER_NAMES["z"], {"y"}):          # a bare y only without a better name
        if vertical is None:
            vertical = cols.named(names, free, taken)
    if vertical is not None:
        taken.add(vertical)

    rest = [c for c in free if c not in taken]
    if position == "distance" and distance is None and rest:
        distance = rest.pop(0)
    if value is None and rest:
        value = rest.pop()
    if vertical is None and rest:
        vertical = rest.pop(0)
    return ModelColumns(position=position, distance=distance, easting=east, northing=north,
                        crs=cols.crs(east, north), vertical=vertical,
                        vertical_kind="" if vertical is None else cols.vertical_kind(vertical),
                        value=value)


#: header words of a column of point names (``ERT03_15``), whose numbers are the electrodes
NAME_HEADERS = {"name", "punkt", "point", "pkt", "pt", "bez", "bezeichnung", "label", "id",
                "station", "nr", "number"}
_DATE = re.compile(r"^\d{1,4}[-./]\d{1,2}[-./]\d{1,4}")


def _name_column(table, cols: _Columns, taken=()) -> int | None:
    """A column of point names: a column with text cells (also numbers with a few named
    points) by header word, else the first text column where more than half of the filled
    cells hold a digit and no cell looks like a date or a time."""
    text = [c for c in range(table.n_columns) if c not in cols.numeric]
    mixed = [c for c in range(table.n_columns) if c not in taken and table.has_text(c)]
    named = cols.named(NAME_HEADERS, mixed)
    if named is not None:
        return named
    for c in text:
        cells = [row[c].strip() for row in table.cells if row[c].strip()]
        if not cells or any(":" in v or _DATE.match(v) for v in cells):
            continue
        if sum(any(ch.isdigit() for ch in v) for v in cells) * 2 > len(cells):
            return c
    return None


def guess_position_columns(table) -> PositionColumns:
    """First guess of a positions table's roles from header names; easting and northing
    otherwise from projected-looking values, else by position as ``guess_columns`` does.
    Without any header name, a whole-number column just before the easting is the number
    and the column after the northing the elevation. Degrees preselect EPSG:4326."""
    cols = _Columns(table)
    nums = cols.numeric
    taken: set[int] = set()
    found: dict[str, int | None] = {}
    for role in ("number", "x", "y", "z", "inline"):
        found[role] = cols.named(_HEADER_NAMES[role], nums, taken)
        if found[role] is not None:
            taken.add(found[role])
    east, north = cols.map_pair(found["x"], found["y"], [c for c in nums if c not in taken])
    number, elevation = found["number"], found["z"]
    if all(c is None for c in found.values()):
        if east is None and len(nums) >= 2:
            g = guess_columns(None, len(nums))
            east, north = nums[g["x"]], nums[g["y"]]
        if east is not None:
            before = [c for c in nums if c < east]
            after = [c for c in nums if c > north]
            number = before[-1] if before and cols.whole(before[-1]) else None
            elevation = after[0] if after else None
    if number is None:
        number = _name_column(table, cols, {east, north, elevation, found["inline"]})
    return PositionColumns(easting=east, northing=north, crs=cols.crs(east, north),
                           elevation=elevation, number=number, inline=found["inline"])
