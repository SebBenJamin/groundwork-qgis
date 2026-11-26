"""Small SEG-Y files for the tests, written with segyio (never by hand).

Only the ASCII text header is patched in afterwards: segyio always writes the text header in
EBCDIC, and some real files (Innomar exports) carry it in ASCII."""
from __future__ import annotations

from pathlib import Path

import numpy as np

_FIELDS = {"cdp": ("CDP_X", "CDP_Y"), "source": ("SourceX", "SourceY"),
           "group": ("GroupX", "GroupY")}


def _text_lines(text: str) -> bytes:
    """``text`` as 40 lines of 80 characters (ASCII bytes), padded with spaces."""
    lines = (text or "").split("\n")[:40]
    lines += [""] * (40 - len(lines))
    return "".join(line[:80].ljust(80) for line in lines).encode("ascii")


def write_segy(path, amplitudes, dt_us=1000, fmt=1, endian="big", delay_ms=0, cdp=None, xy=None,
               xy_field="source", scalar=1, offsets=None, text=None, ascii_text=False,
               units=None, inline=None, crossline=None) -> Path:
    """Write ``amplitudes`` (traces x samples) as a SEG-Y file and return its path.

    ``xy`` (n, 2) are the header numbers of ``xy_field`` as stored (before ``scalar``);
    ``units`` is the coordinate-units code, ``inline`` / ``crossline`` the 3D numbers per trace."""
    import segyio
    path = Path(path)
    a = np.asarray(amplitudes)
    n, ns = a.shape
    spec = segyio.spec()
    spec.format = int(fmt)
    spec.samples = list(range(ns))
    spec.tracecount = n
    spec.endian = endian
    dtype = {1: np.float32, 5: np.float32, 2: np.int32, 3: np.int16, 8: np.int8}[int(fmt)]
    with segyio.create(str(path), spec) as f:
        # create() works the interval out from the samples; the exact number is set here
        f.bin.update({segyio.BinField.Interval: int(dt_us),
                      segyio.BinField.IntervalOriginal: int(dt_us)})
        if text is not None and not ascii_text:
            f.text[0] = _text_lines(text)
        for i in range(n):
            h = {segyio.TraceField.TRACE_SEQUENCE_LINE: i + 1,
                 segyio.TraceField.TRACE_SAMPLE_COUNT: ns,
                 segyio.TraceField.TRACE_SAMPLE_INTERVAL: int(dt_us),
                 segyio.TraceField.DelayRecordingTime: int(delay_ms),
                 segyio.TraceField.SourceGroupScalar: int(scalar)}
            if cdp is not None:
                h[segyio.TraceField.CDP] = int(cdp[i])
            if offsets is not None:
                h[segyio.TraceField.offset] = int(offsets[i])
            if xy is not None:
                fx, fy = _FIELDS[xy_field]
                h[getattr(segyio.TraceField, fx)] = int(xy[i][0])
                h[getattr(segyio.TraceField, fy)] = int(xy[i][1])
            if units is not None:
                h[segyio.TraceField.CoordinateUnits] = int(units)
            if inline is not None:
                h[segyio.TraceField.INLINE_3D] = int(inline[i])
            if crossline is not None:
                h[segyio.TraceField.CROSSLINE_3D] = int(crossline[i])
            f.header[i] = h
            f.trace[i] = np.ascontiguousarray(a[i], dtype=dtype)
    if text is not None and ascii_text:
        with path.open("r+b") as fh:
            fh.write(_text_lines(text))
    return path
