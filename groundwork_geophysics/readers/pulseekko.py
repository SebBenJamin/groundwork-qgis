"""Sensors & Software pulseEKKO radar lines (.dt1 + .hd), read by Groundwork itself (no
QGIS/Qt, no library).

What is covered, and nothing else: a line as a pair of files with the same name, the text
header ``.hd`` and the trace file ``.dt1``; 2-byte samples; positions in metres. Either file
can be chosen, the other must lie beside it. Refused with a plain message: a missing partner,
a header file without the number of traces, points per trace or time window, traces with
other than 2 bytes per point or another number of points than the header file gives,
positions in other units than metres, and fewer than two whole traces.

The ``.hd`` file is text: a first line (a file mark, "1234" in the real files), a comment, a
date, then ``KEY = value`` lines. Keys used::

    NUMBER OF TRACES      NUMBER OF PTS/TRC     TOTAL TIME WINDOW (ns)
    TIMEZERO AT POINT     STARTING POSITION     STEP SIZE USED
    POSITION UNITS        NOMINAL FREQUENCY (MHz)   SURVEY MODE

The ``.dt1`` file holds the traces one after the other, each a 128-byte header followed by the
samples as little-endian int16. The trace header (byte offset, type, field)::

      0  float32  trace number
      4  float32  position (in POSITION UNITS)
      8  float32  number of points per trace
     12  float32  topographic data
     16  float32  (not used)
     20  float32  number of bytes per point (2)
     24  float32  time window (ns)
     28  float32  number of stacks
     32  float64  x 3  GPS X, Y, Z (not read; see below)
     56  float32  x 6  receiver x, y, z and transmitter x, y, z
     80  float32  time zero adjustment
     84  float32  zero flag (0 data ok, 1 zero data)
     88  float32  (not used)
     92  float32  time of day the trace was recorded (seconds after midnight)
     96  float32  comment flag
    100  char[28] comment

Where the meanings come from: Sensors & Software's pulseEKKO file format description as the
open reader RGPR (readDT1.R, readHD) reads it field by field; USGS Open-File Report 02-166
(GPR_SAMP) for the 128-byte trace header, the int16 samples, the pairing of ``.dt1`` and
``.hd`` by name and "TOTAL TIME WINDOW" as the time per trace. Older descriptions list the GPS
fields as six float32; the two readings differ, so GPS positions are not read: the traces are
placed along the line, and a note says when the GPS bytes are not all zero.

Times: the sample step is TOTAL TIME WINDOW / NUMBER OF PTS/TRC (the real lines: 150 ns /
750 points = 0.2 ns, an interval the instrument offers; RGPR does the same), the first sample
is at 0. Time zero is (TIMEZERO AT POINT − 1) × step: the points are counted from 1, as RGPR
reads them. The real lines' trace headers give a time window (200 ns) other than the header
file (150 ns); the header file's is used, and a note says so.

Positions: the trace headers' positions when they increase from trace to trace, else
STARTING POSITION + i × STEP SIZE USED.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ..core.trace_section import TraceSection
from .base import Reader, ReaderResult
from .radar_info import (NANOSECOND, RadarInfo, check_position, named_after, partner,
                         provenance_of, trace_x)

SUFFIXES = (".dt1", ".hd")
TRACE_HEADER = 128
_BYTES_PER_POINT = 2
_METRES = ("m", "metre", "metres", "meter", "meters")
# float32 word numbers in the trace header (counted from 0)
_POSITION, _POINTS, _BYTES, _WINDOW, _T0_ADJUST = 1, 2, 5, 6, 20
_GPS = slice(32, 56)                       # bytes of the three GPS numbers


def _pair(path: Path) -> tuple[Path, Path]:
    """``(dt1, hd)`` for either file of a line; ValueError when the partner is missing."""
    name = path.name
    if path.suffix.lower() == ".hd":
        dt1 = partner(path, ".DT1")
        if dt1 is None:
            raise ValueError(f"{name}: the trace file {path.stem}.DT1 is missing beside it.")
        return dt1, path
    hd = partner(path, ".HD")
    if hd is None:
        raise ValueError(f"{name}: the header file {path.stem}.HD is missing beside it.")
    return path, hd


def read_hd(path: Path) -> dict:
    """The ``KEY = value`` lines of a header file (keys upper case, values stripped)."""
    out = {}
    for line in Path(path).read_text(encoding="latin-1").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            out.setdefault(" ".join(key.split()).upper(), value.strip())
    return out


def _number(hd: dict, key: str, name: str, required: bool = True):
    value = hd.get(key)
    if value is None or value == "":
        if required:
            raise ValueError(f"{name}: the header file gives no {key}.")
        return None
    try:
        v = float(value.split()[0])
    except (ValueError, IndexError):
        raise ValueError(f"{name}: {key} is not a number ({value!r}).") from None
    if not np.isfinite(v):
        raise ValueError(f"{name}: {key} is not a number ({value!r}).")
    return v


def _scan(path: Path) -> tuple[RadarInfo, Path, np.ndarray]:
    """``(info, dt1 path, x from the file or None)``; reads the trace headers, not the samples."""
    dt1, hd_path = _pair(path)
    name, hd_name = dt1.name, hd_path.name
    hd = read_hd(hd_path)
    n_listed = int(_number(hd, "NUMBER OF TRACES", hd_name))
    pts = int(_number(hd, "NUMBER OF PTS/TRC", hd_name))
    window_ns = _number(hd, "TOTAL TIME WINDOW", hd_name)
    if pts < 1:
        raise ValueError(f"{hd_name}: the header file gives no points per trace.")
    if window_ns <= 0:
        raise ValueError(f"{hd_name}: the header file gives no time window.")
    units = hd.get("POSITION UNITS", "m").strip().lower() or "m"
    if units not in _METRES:
        raise ValueError(f"{hd_name}: the positions are in {hd.get('POSITION UNITS')}; Groundwork "
                         "reads pulseEKKO lines with positions in metres.")

    notes = []
    trace_size = TRACE_HEADER + pts * _BYTES_PER_POINT
    n, rest = divmod(dt1.stat().st_size, trace_size)
    if n < 2:
        raise ValueError(f"{name}: the file holds fewer than 2 whole traces.")
    if rest:
        notes.append(f"The file ends inside a trace: the last {rest} bytes are left out.")
    if n != n_listed:
        notes.append(f"The header file lists {n_listed} traces, the trace file holds {n} whole "
                     f"traces; {n} are read.")
    with dt1.open("rb") as fh:
        raw = np.fromfile(fh, dtype=np.uint8, count=n * trace_size).reshape(n, trace_size)
    heads = raw[:, :TRACE_HEADER].copy().view("<f4")
    bytes_pp = heads[0, _BYTES]
    if bytes_pp != _BYTES_PER_POINT:
        raise ValueError(f"{name}: the traces hold {bytes_pp:g} bytes per point; Groundwork reads "
                         "2-byte pulseEKKO samples.")
    if heads[0, _POINTS] != pts:
        raise ValueError(f"{name}: the traces hold {heads[0, _POINTS]:g} points each, the header "
                         f"file gives {pts}.")

    step = window_ns * NANOSECOND / pts
    point = _number(hd, "TIMEZERO AT POINT", hd_name, required=False)
    time_zero = (point - 1.0) * step if point is not None and point >= 1 else None
    trace_window = float(heads[0, _WINDOW])
    if np.isfinite(trace_window) and trace_window > 0 and abs(trace_window - window_ns) > 1e-3:
        notes.append(f"The trace headers give a time window of {trace_window:g} ns, the header "
                     f"file {window_ns:g} ns; the header file's is used.")
    if np.any(heads[:, _T0_ADJUST] != 0):
        notes.append("The trace headers carry time zero adjustments; they are not applied.")
    if raw[:, _GPS].any():
        notes.append("The trace headers hold GPS numbers, which are not read; place the traces "
                     "with a coordinate file.")
    mode = hd.get("SURVEY MODE", "").strip()
    if mode and mode.lower() != "reflection":
        notes.append(f"The survey mode is {mode}: the traces may not be a profile along the "
                     "line.")

    start = _number(hd, "STARTING POSITION", hd_name, required=False) or 0.0
    given = _number(hd, "STEP SIZE USED", hd_name, required=False)
    trace_step = given if given is not None and given > 0 else None
    pos = heads[:, _POSITION].astype(np.float64)
    if np.isfinite(pos).all() and (np.diff(pos) > 0).all():
        x = pos
    elif trace_step is not None:
        x = start + np.arange(n, dtype=np.float64) * trace_step
        notes.append("The trace headers' positions do not increase along the line; the traces "
                     "are placed by the starting position and the step size.")
    else:
        x = None
    freq = _number(hd, "NOMINAL FREQUENCY", hd_name, required=False)
    info = RadarInfo(
        n_traces=int(n), n_samples=pts, step=step, window=window_ns * NANOSECOND, first=0.0,
        time_zero=time_zero, velocity=None, dielectric=None,
        antenna=f"{freq:g}MHz" if freq else "", frequency_mhz=freq, trace_step=trace_step,
        start=float(x[0]) if x is not None else float(start),
        length=float(x[-1] - x[0]) if x is not None else None, notes=notes, bits=16)
    return info, dt1, x


def inspect(path) -> RadarInfo:
    """What the header file and the trace headers say (no samples are read)."""
    return _scan(Path(path))[0]


def sample_traces(path, limit: int = 2000) -> TraceSection:
    """Every k-th trace of the line (at most ``limit``, the stride ``first_arrival`` takes),
    for an estimate of time zero without keeping the whole line; ``x`` is each trace's
    index. (The trace headers are still scanned whole, as ``inspect`` does.)"""
    info, dt1, _x = _scan(Path(path))
    k = max(1, math.ceil(info.n_traces / max(1, int(limit))))
    record = np.dtype([("h", "V128"), ("s", "<i2", (info.n_samples,))])
    mm = np.memmap(dt1, dtype=record, mode="r", shape=(info.n_traces,))
    try:
        samples = np.array(mm["s"][::k], dtype=np.int16)
    finally:
        del mm                                  # the file is closed again
    return TraceSection(samples, np.arange(0, info.n_traces, k), info.first, info.step, "time")


class PulseEkkoReader(Reader):
    name = "pulseekko"
    label = "Sensors & Software pulseEKKO (.dt1 + .hd)"

    def sniff(self, path: Path) -> bool:
        """By the name: a .dt1, or a .hd with a .dt1 of the same name beside it (a directory
        look; no file is opened)."""
        try:
            path = Path(path)
            suffix = path.suffix.lower()
            if suffix == ".dt1":
                return True
            return suffix == ".hd" and partner(path, ".DT1") is not None
        except Exception:
            return False

    def default_name(self, path: Path) -> str:
        """The line's name followed by the antenna's nominal frequency from the header file
        (only that file is read): "LINE00 (250MHz)"."""
        _dt1, hd_path = _pair(Path(path))
        freq = _number(read_hd(hd_path), "NOMINAL FREQUENCY", hd_path.name, required=False)
        return named_after(path, f"{freq:g}MHz" if freq else "")

    def read(self, path: Path, **options) -> ReaderResult:
        """Either file of the line. Options: ``position`` ("file", the default | "spacing" |
        "table"), ``spacing`` and, for "table", ``positions_file`` / ``positions_table`` /
        ``positions_columns`` with ``xy_to_distance``. Hang options are the provider's."""
        path = Path(path)
        check_position(options, path.name)
        info, dt1, file_x = _scan(path)
        provenance = provenance_of(self.name, dt1.name, info)
        x = trace_x(path, options, file_x, info.n_traces, provenance)
        pts = info.n_samples
        record = np.dtype([("h", "V128"), ("s", "<i2", (pts,))])
        traces = np.fromfile(dt1, dtype=record, count=info.n_traces)["s"]
        amplitudes = np.ascontiguousarray(traces, dtype=np.int16)
        section = TraceSection(amplitudes, x, info.first, info.step, "time",
                               numbers=np.arange(1, info.n_traces + 1))
        return ReaderResult(None, "depth", provenance, traces=section)
