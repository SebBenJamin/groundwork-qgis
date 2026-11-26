"""SEG-Y sections read through the library segyio (no QGIS/Qt).

Groundwork never takes SEG-Y apart itself: segyio opens the file, reads the binary and trace
headers and hands over the samples, which are kept exactly as it returns them (float32 for IBM
and IEEE floats, the file's integer type otherwise). The one thing done here is choosing ASCII or
EBCDIC for the 3200-byte text header: segyio always decodes it as EBCDIC, which garbles the ASCII
headers some programs write, so those 3200 bytes are read as they are and the choice made here.

segyio is an optional library, installed on the user's request (``libs``); it is imported inside
the functions, and a missing segyio is reported as ``libs.MissingLibrary("segyio")``.

Trace positions come from a trace spacing, from a pair of header fields (CDP, source or group X
and Y, put on the profile line with ``xy_to_distance(easting, northing) -> (chainage, offset,
beyond)``), or from a coordinate file listing trace numbers with easting and northing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import libs
from ..core.trace_section import TraceSection
from .base import Reader, ReaderResult
from .texttable import TableOptions, guess_options, read_table, select_rows

#: header pairs that can hold trace positions, in the order they are proposed
POSITION_FIELDS = ("cdp", "source", "group")
POSITIONS = ("spacing", "map", "table")
_XY = {"cdp": ("CDP_X", "CDP_Y"), "source": ("SourceX", "SourceY"), "group": ("GroupX", "GroupY")}
_FIELD_NAMES = {"cdp": "CDP", "source": "source", "group": "group (receiver)"}
SUFFIXES = (".sgy", ".segy")
#: share of printable ASCII bytes from which a text header counts as ASCII rather than EBCDIC
_ASCII_SHARE = 0.9
_TEXT_SIZE = 3200
_VELOCITY = re.compile(r"(?i)sound\s+velocity\D*(\d+(?:\.\d+)?)\s*m/s")
# coordinate units (trace header bytes 89-90): 0/1 length, 2 arc seconds, 3 degrees, 4 packed DMS
_ARC_SECONDS, _DEGREES, _PACKED_DMS = 2, 3, 4


@dataclass
class SegyInfo:
    """What the headers of a SEG-Y file say (no samples read)."""
    n_traces: int
    n_samples: int
    step: float                    # seconds, from the file's headers (0.0 when the file says 0)
    first: float                   # seconds: the delay recording time of trace 1
    endian: str                    # "big" | "little"
    sample_format: int
    text: str                      # the text header, 40 lines (trailing blanks removed), decoded
    positions: dict                # field -> ((x0, y0), (x1, y1)) for fields whose positions change
    velocity: float | None         # only from a text line naming a sound velocity in m/s
    unstacked: bool                # looks like gathers: offsets varying, or CDP numbers repeating
    geographic: bool = False       # positions are degrees (x = longitude)
    volume: bool = False           # inline and crossline numbers both vary: a 3D volume
    numbers_from_cdp: bool = False  # the CDP field holds one distinct number per trace
    n_inlines: int = 1
    n_crosslines: int = 1
    #: position fields whose X or Y has one value on every trace: distances along the line
    #: (Carfax: source X 4…560, Y 0) rather than map coordinates
    flat: tuple = ()


@dataclass
class _Headers:
    """The per-trace header numbers the reader needs besides ``SegyInfo``."""
    coords: dict = field(default_factory=dict)   # field -> (n, 2) float, scalar and units applied
    cdp: np.ndarray | None = None
    units: int = 0


def _segyio():
    """The segyio module; ``MissingLibrary("segyio")`` when it is not installed."""
    try:
        libs.ensure_on_path()
    except Exception:          # outside QGIS (plain Python, tests) there is no profile folder
        pass
    try:
        import segyio
    except ImportError:
        raise libs.MissingLibrary("segyio") from None
    return segyio


def _open(segyio, path: Path):
    """``(file, endian)``: opened big-endian, else little-endian; ValueError when segyio cannot
    open it either way."""
    reason = ""
    for endian in ("big", "little"):
        try:
            return segyio.open(str(path), "r", ignore_geometry=True, endian=endian), endian
        except RuntimeError as exc:
            reason = reason or (str(exc).strip() or type(exc).__name__)
    raise ValueError(f"{path.name}: segyio cannot read this file ({reason}). "
                     "Re-export it as standard SEG-Y.")


def decode_text(raw: bytes) -> str:
    """A 3200-byte text header as 40 lines: ASCII when at least 90 % of the bytes are printable
    ASCII and ASCII blanks are at least as many as "@" (the EBCDIC blank), else
    EBCDIC (cp037). Control characters become blanks; trailing blanks are removed."""
    raw = bytes(raw)
    printable = sum(1 for b in raw if 32 <= b < 127 or b in (9, 10, 13))
    # the EBCDIC blank (0x40) is the printable ASCII "@": a mostly blank EBCDIC header would pass
    # the share alone, so the ASCII blank must also be at least as common as the EBCDIC one
    ascii_text = (bool(raw) and printable >= _ASCII_SHARE * len(raw)
                  and raw.count(b" ") >= raw.count(b"@"))
    text = raw.decode("ascii", errors="replace") if ascii_text else raw.decode("cp037")
    text = "".join(c if c >= " " and c != "\x7f" else " " for c in text).ljust(_TEXT_SIZE)
    return "\n".join(text[i:i + 80].rstrip() for i in range(0, _TEXT_SIZE, 80))


def stated_velocity(text: str) -> float | None:
    """The sound velocity in m/s a text line states, None when no line does."""
    for line in text.splitlines():
        m = _VELOCITY.search(line)
        if m:
            return float(m.group(1))
    return None


def _scaled(values: np.ndarray, scalar: np.ndarray) -> np.ndarray:
    """Header coordinates with the SEG-Y scalar applied: negative divides by its size, positive
    multiplies, 0 counts as 1."""
    v = values.astype(np.float64)
    s = scalar.astype(np.float64)
    return np.where(s < 0, v / np.where(s < 0, -s, 1.0), v * np.where(s > 0, s, 1.0))


def _scan(segyio, f, path: Path, endian: str) -> tuple[SegyInfo, _Headers]:
    """Read the headers of an open file (no samples)."""
    tf = segyio.TraceField

    def column(name):
        return np.asarray(f.attributes(getattr(tf, name))[:]).reshape(-1)

    n = int(f.tracecount)
    scalar = column("SourceGroupScalar")
    units = int(column("CoordinateUnits")[0]) if n else 0
    geographic = units in (_ARC_SECONDS, _DEGREES)
    heads = _Headers(units=units)
    positions = {}
    flat = []
    for name in POSITION_FIELDS:
        raw = np.column_stack([column(_XY[name][0]), column(_XY[name][1])])
        if not raw.any() or len(np.unique(raw, axis=0)) < 2:
            continue                                     # all zero or never changing
        if len(np.unique(raw[:, 0])) < 2 or len(np.unique(raw[:, 1])) < 2:
            flat.append(name)
        xy = _scaled(raw, scalar[:, None])
        if units == _ARC_SECONDS:
            xy = xy / 3600.0
        heads.coords[name] = xy
        positions[name] = ((float(xy[0, 0]), float(xy[0, 1])), (float(xy[-1, 0]), float(xy[-1, 1])))
    cdp = column("CDP")
    heads.cdp = cdp
    n_cdp = len(np.unique(cdp))
    offsets = column("offset")
    # gathers: offsets that vary, or CDP numbers that repeat. One offset for every trace is a
    # single-channel survey (the Innomar sub-bottom profiles write 1 in every trace)
    unstacked = bool((offsets.any() and len(np.unique(offsets)) > 1) or (cdp.any() and n_cdp < n))
    n_il, n_xl = len(np.unique(column("INLINE_3D"))), len(np.unique(column("CROSSLINE_3D")))
    with path.open("rb") as fh:                          # the text header only (see above)
        text = decode_text(fh.read(_TEXT_SIZE))
    delay = float(column("DelayRecordingTime")[0]) if n else 0.0
    info = SegyInfo(
        n_traces=n, n_samples=len(f.samples),
        step=float(segyio.tools.dt(f, fallback_dt=0.0)) / 1e6, first=delay / 1000.0,
        endian=endian, sample_format=int(f.bin[segyio.BinField.Format]), text=text,
        positions=positions, velocity=stated_velocity(text), unstacked=unstacked,
        geographic=geographic, volume=n_il > 1 and n_xl > 1,
        numbers_from_cdp=bool(n_cdp == n and cdp.any()), n_inlines=n_il, n_crosslines=n_xl,
        flat=tuple(flat))
    return info, heads


def inspect(path) -> SegyInfo:
    """What the file's headers say (no samples are read)."""
    return _headers(path)[0]


def _headers(path) -> tuple[SegyInfo, _Headers]:
    path = Path(path)
    segyio = _segyio()
    f, endian = _open(segyio, path)
    with f:
        return _scan(segyio, f, path, endian)


def _numbers(info: SegyInfo, heads: _Headers) -> np.ndarray:
    """The number of each trace: the CDP field when it holds one number per trace, else 1..n."""
    return heads.cdp.copy() if info.numbers_from_cdp else np.arange(1, info.n_traces + 1)


def volume_message(name: str, info: SegyInfo) -> str:
    """What is said about a 3D volume, which Groundwork does not show."""
    return (f"{name}: this is a 3D volume ({info.n_inlines} inlines × {info.n_crosslines} "
            "crosslines). Groundwork shows 2D sections.")


def trace_numbers(path) -> np.ndarray:
    """The number of each trace as a coordinate file lists it (headers only)."""
    return _numbers(*_headers(path))


def map_positions(path, options: dict) -> np.ndarray:
    """Easting and northing (n, 2) of each trace as a read with ``options`` places them:
    ``position`` "map" (the ``xy_field`` header pair, repeated fixes spread out) or "table"
    (the coordinate file). Headers only, no samples; ValueError as the reader says it."""
    path = Path(path)
    info, heads = _headers(path)
    position = options.get("position")
    if position == "map":
        xy_field = options.get("xy_field")
        if xy_field not in heads.coords:
            raise ValueError(f"{path.name}: the file has no positions in the "
                             f"{_FIELD_NAMES.get(xy_field, str(xy_field))} fields that change "
                             "along the line.")
        return spread_fixes(heads.coords[xy_field])
    if position == "table":
        given = options.get("positions_file")
        if not given:
            raise ValueError(f"{path.name}: choose the coordinate file with the trace positions")
        table_path = Path(given)
        if not table_path.is_absolute():
            table_path = path.parent / table_path
        return table_positions(table_path, options.get("positions_table") or {},
                               options.get("positions_columns") or {}, _numbers(info, heads))
    raise ValueError(f"{path.name}: the traces are not placed by map positions")


def spread_fixes(xy) -> np.ndarray:
    """Positions with repeated fixes spread out: the traces between two changes of position
    are placed evenly from one fix to the next; the last run keeps the spacing of the run
    before it. Without a second fix the positions are returned as they are."""
    xy = np.asarray(xy, dtype=np.float64)
    n = len(xy)
    starts = np.flatnonzero(np.r_[True, (np.diff(xy, axis=0) != 0).any(axis=1)])
    if starts.size < 2:
        return xy
    lengths = np.diff(np.r_[starts, n])
    fixes = xy[starts]
    steps = np.empty_like(fixes)
    steps[:-1] = np.diff(fixes, axis=0) / lengths[:-1, None]
    steps[-1] = steps[-2]
    run = np.repeat(np.arange(starts.size), lengths)
    k = (np.arange(n) - starts[run]).astype(np.float64)
    return fixes[run] + k[:, None] * steps[run]


def table_positions(path, table_options: dict, columns: dict, numbers: np.ndarray) -> np.ndarray:
    """Easting and northing (n, 2) of each trace from a coordinate file listing trace numbers.

    Rows are matched to traces by number (``numbers``, one per trace); traces between two
    listed numbers are placed evenly between them, traces outside the listed range continue
    with the step of the nearest pair. ValueError when fewer than two numbers match."""
    path = Path(path)
    try:
        opts = TableOptions.from_dict(table_options) if table_options else guess_options(path)
        cols = [int(columns[k]) for k in ("number", "easting", "northing")]
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"{path.name}: the stored coordinate file settings cannot be used "
                         f"({exc}); add the file again") from None
    tab = read_table(path, opts)
    for i in cols:
        if not 0 <= i < tab.n_columns:
            raise ValueError(f"{path.name}: column {i + 1} is not in the file any more")
    try:
        arr, _skipped, _first = select_rows(tab, cols)
    except ValueError as exc:
        raise ValueError(f"{path.name}: {exc}") from None
    numbers = np.asarray(numbers, dtype=np.float64).reshape(-1)
    trace_of = {}
    for i, v in enumerate(numbers):
        trace_of.setdefault(float(v), i)                 # the first trace with that number
    listed = {trace_of[float(v)]: (e, n) for v, e, n in arr if float(v) in trace_of}
    if len(listed) < 2:
        raise ValueError(f"{path.name}: fewer than two of the file's trace numbers are in the "
                         "coordinate file.")
    t = np.array(sorted(listed), dtype=np.float64)
    xy = np.array([listed[int(i)] for i in t], dtype=np.float64)
    k = np.arange(numbers.size, dtype=np.float64)
    out = np.column_stack([np.interp(k, t, xy[:, 0]), np.interp(k, t, xy[:, 1])])
    before, after = k < t[0], k > t[-1]
    out[before] = xy[0] + (k[before] - t[0])[:, None] * (xy[1] - xy[0]) / (t[1] - t[0])
    out[after] = xy[-1] + (k[after] - t[-1])[:, None] * (xy[-1] - xy[-2]) / (t[-1] - t[-2])
    return out


def _positive(value, what: str, name: str) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = float("nan")
    if not (np.isfinite(v) and v > 0):
        raise ValueError(f"{name}: the {what} must be greater than 0.")
    return v


def _place(xy: np.ndarray, xy_to_distance, name: str, provenance: dict) -> np.ndarray:
    """Chainage of each trace position; offsets and positions past the line ends recorded."""
    if xy_to_distance is None:
        raise ValueError(f"{name}: a section with map positions needs a profile line to place "
                         "it on")
    placed = xy_to_distance(xy[:, 0], xy[:, 1])
    offset = np.asarray(placed[1], dtype=float)
    beyond = np.asarray(placed[2], dtype=bool) if len(placed) > 2 else None
    provenance["max_offset"] = float(np.abs(offset).max()) if offset.size else 0.0
    provenance["n_beyond"] = 0 if beyond is None else int(beyond.sum())
    return np.asarray(placed[0], dtype=np.float64)


class SegyReader(Reader):
    name = "segy"
    label = "SEG-Y (segyio)"

    def sniff(self, path: Path) -> bool:
        """By the name alone (.sgy / .segy); the file is not opened."""
        try:
            return Path(path).suffix.lower() in SUFFIXES
        except Exception:
            return False

    def read(self, path: Path, **options) -> ReaderResult:
        """Options: ``position`` ("spacing" | "map" | "table"), ``spacing``, ``xy_field``,
        ``crs``, ``domain`` ("time" | "depth"), ``sample_step`` and, for "table",
        ``positions_file`` / ``positions_table`` / ``positions_columns``; ``xy_to_distance`` for
        "map" and "table". Other stored options (velocity, zero, datum) are the provider's."""
        path = Path(path)
        name = path.name
        segyio = _segyio()
        position = options.get("position") or "spacing"
        if position not in POSITIONS:
            raise ValueError(f"{name}: unknown trace position {position!r}; expected one of "
                             f"{', '.join(POSITIONS)}")
        domain = options.get("domain") or "time"
        if domain not in ("time", "depth"):
            raise ValueError(f"{name}: unknown sample domain {domain!r}; expected time or depth")
        spacing = None
        if position == "spacing":
            spacing = _positive(options.get("spacing"), "trace spacing", name)
        given_step = options.get("sample_step")
        if given_step is not None:
            given_step = _positive(given_step, "sample step", name)

        f, endian = _open(segyio, path)
        with f:
            info, heads = _scan(segyio, f, path, endian)
            if info.volume:
                raise ValueError(volume_message(name, info))
            if position == "map":
                xy_field = options.get("xy_field")
                if xy_field not in POSITION_FIELDS:
                    raise ValueError(f"{name}: choose which header positions to use "
                                     f"({', '.join(POSITION_FIELDS)})")
                if xy_field not in heads.coords:
                    raise ValueError(f"{name}: the file has no positions in the "
                                     f"{_FIELD_NAMES[xy_field]} fields that change along the line.")
                if heads.units == _PACKED_DMS:
                    raise ValueError(f"{name}: the positions are packed degrees, minutes, "
                                     "seconds; this is not supported.")
            amplitudes = f.trace.raw[:]                  # as segyio returns them

        step_assumed = False
        if given_step is not None:
            step = given_step
        elif info.step <= 0:
            raise ValueError(f"{name}: the file gives no sample step; enter it.")
        elif domain == "time":
            step = info.step
        else:
            # a depth step written in the time field: the common "4000 = 4 m"
            step, step_assumed = info.step * 1000.0, True
        # the delay is in milliseconds; for a depth section its number is read as metres
        first = info.first if domain == "time" else info.first * 1000.0
        n = info.n_traces
        numbers = _numbers(info, heads)

        provenance = {"reader": self.name, "source_name": name, "n_traces": n,
                      "n_samples": info.n_samples, "step": info.step, "first": info.first,
                      "endian": info.endian, "sample_format": info.sample_format,
                      "text": info.text, "unstacked": info.unstacked, "position": position,
                      "domain": domain, "step_assumed": step_assumed,
                      "velocity": info.velocity}
        xy_to_distance = options.get("xy_to_distance")
        if position == "spacing":
            x = np.arange(n, dtype=np.float64) * spacing
        elif position == "map":
            xy = spread_fixes(heads.coords[options["xy_field"]])
            x = _place(xy, xy_to_distance, name, provenance)
        else:
            x = self._table_x(path, options, numbers, xy_to_distance, provenance)

        section = TraceSection(amplitudes, x, first, step, domain, numbers=numbers)
        return ReaderResult(None, "depth", provenance, traces=section)

    @staticmethod
    def _table_x(path: Path, options: dict, numbers, xy_to_distance, provenance) -> np.ndarray:
        """Chainage of each trace from the coordinate file (``position`` "table")."""
        given = options.get("positions_file")
        if not given:
            raise ValueError(f"{path.name}: choose the coordinate file with the trace positions")
        table_path = Path(given)
        if not table_path.is_absolute():
            table_path = path.parent / table_path    # stored by name when it lies beside the file
        xy = table_positions(table_path, options.get("positions_table") or {},
                             options.get("positions_columns") or {}, numbers)
        return _place(xy, xy_to_distance, path.name, provenance)
