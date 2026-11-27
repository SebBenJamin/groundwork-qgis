"""Small radar files for the tests, written in the layouts the readers read (the layouts are
described once, in the docstrings of ``readers.gssi_dzt`` and ``readers.pulseekko``)."""
from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

_LIGHT_M_PER_NS = 0.299792458


def write_dzt(path, amplitudes, range_ns, scans_per_metre=50.0, bits=16, dielectric=None,
              antenna="270MHz", channels=1, position_ns=0.0) -> Path:
    """Write ``amplitudes`` (scans x samples, signed values) as a GSSI .dzt file with one
    1,024-byte header per channel; every channel holds the same scans."""
    path = Path(path)
    a = np.asarray(amplitudes)
    n, ns = a.shape
    head = bytearray(1024)
    struct.pack_into("<HHHHh", head, 0, 0x00FF, 1024, ns, bits, 0)
    struct.pack_into("<5f", head, 10, 64.0, scans_per_metre, 0.5, position_ns, range_ns)
    struct.pack_into("<H", head, 52, channels)
    eps = 0.0 if dielectric is None else float(dielectric)
    depth = range_ns * _LIGHT_M_PER_NS / np.sqrt(eps) / 2 if eps >= 1 else 0.0
    struct.pack_into("<3f", head, 54, eps, 0.0, depth)
    head[98:98 + 14] = antenna.encode("ascii")[:14].ljust(14, b"\0")
    if bits == 8:
        data = (a.astype(np.int16) + 128).astype("<u1")
    elif bits == 16:
        data = (a.astype(np.int32) + 32768).astype("<u2")
    elif bits == 32:
        data = a.astype("<i4")
    else:
        data = np.zeros((n, ns * bits // 8), np.uint8)
    data = np.repeat(data, channels, axis=0) if channels > 1 else data
    with path.open("wb") as fh:
        fh.write(bytes(head) * channels)
        fh.write(np.ascontiguousarray(data).tobytes())
    return path


def write_pulseekko(path_dt1, amplitudes, window_ns, step_m=0.1, timezero_point=None, start=0.0,
                    frequency=250.0, positions=None, trace_window_ns=None) -> Path:
    """Write ``amplitudes`` (traces x points, int16 values) as a pulseEKKO line: the ``.dt1``
    (``path_dt1``) and the ``.hd`` of the same name (upper case suffix when the .dt1's is).
    ``positions`` overrides the trace headers' positions (default start + i × step);
    ``trace_window_ns`` the window written in the trace headers (default ``window_ns``)."""
    path = Path(path_dt1)
    a = np.asarray(amplitudes)
    n, pts = a.shape
    pos = start + np.arange(n) * step_m if positions is None else np.asarray(positions, float)
    with path.open("wb") as fh:
        for i in range(n):
            words = np.zeros(25, "<f4")
            words[[0, 1, 2, 5, 6, 7]] = (i + 1, pos[i], pts, 2,
                                         window_ns if trace_window_ns is None else trace_window_ns,
                                         16)
            fh.write(words.tobytes())
            fh.write(b" " * 28)
            fh.write(a[i].astype("<i2").tobytes())
    lines = ["1234", "Data written for a test", "2026-11-26",
             f"NUMBER OF TRACES   = {n}", f"NUMBER OF PTS/TRC  = {pts}"]
    if timezero_point is not None:
        lines.append(f"TIMEZERO AT POINT  = {timezero_point}")
    lines += [f"TOTAL TIME WINDOW  = {window_ns:.3f}", f"STARTING POSITION  = {start:.4f}",
              f"FINAL POSITION     = {start + (n - 1) * step_m:.4f}",
              f"STEP SIZE USED     = {step_m:.4f}", "POSITION UNITS     = m",
              f"NOMINAL FREQUENCY  = {frequency:.2f}", "ANTENNA SEPARATION = 0.3800",
              "SURVEY MODE        = Reflection"]
    hd = path.with_suffix(".HD" if path.suffix.isupper() else ".hd")
    hd.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
    return path
