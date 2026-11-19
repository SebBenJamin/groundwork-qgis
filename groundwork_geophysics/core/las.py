"""A small LAS 1.4 writer (pure NumPy) for the 3D view's point-cloud curtains: point format 7
(x, y, z and 16-bit RGB), extra double attributes in an Extra Bytes record, the CRS as OGC
WKT. QGIS reads (and indexes) the file through PDAL; nothing else is needed to write it."""
from __future__ import annotations

import os
import struct
from datetime import date
from pathlib import Path

import numpy as np

_HEADER_SIZE = 375
_VLR_HEADER = 54
_EXTRA_BYTES_DESCRIPTOR = 192
_FORMAT = 7
_DOUBLE = 10                            # Extra Bytes data type
_WKT_BIT = 16                           # global encoding: the CRS is WKT


def _vlr(user: str, record: int, payload: bytes, description: str = "") -> bytes:
    return (struct.pack("<H16sHH32s", 0, user.encode(), record, len(payload),
                        description.encode()[:32]) + payload)


def _extra_bytes(names) -> bytes:
    out = b""
    for name in names:
        descriptor = struct.pack("<2sBB32s4s", b"\0\0", _DOUBLE, 0, name.encode()[:32], b"")
        descriptor += b"\0" * (_EXTRA_BYTES_DESCRIPTOR - len(descriptor) - 32)
        descriptor += name.encode()[:32].ljust(32, b"\0")      # description
        out += descriptor
    return out


def write_las(path, xyz, rgb, extra: dict, wkt: str, scale: float = 0.001) -> None:
    """Write ``xyz`` (n, 3) with ``rgb`` (n, 3, 0-255) and the ``extra`` arrays (name -> (n,)
    float, stored as doubles) to ``path`` as LAS 1.4 in the CRS ``wkt``. Written to a
    ``.part`` file first and renamed, so a reader never sees half a file."""
    path = Path(path)
    xyz = np.asarray(xyz, float).reshape(-1, 3)
    n = len(xyz)
    rgb = np.asarray(rgb).reshape(-1, 3)
    names = list(extra)
    lo = xyz.min(axis=0) if n else np.zeros(3)
    hi = xyz.max(axis=0) if n else np.zeros(3)
    offset = np.floor(lo)
    dtype = np.dtype([("x", "<i4"), ("y", "<i4"), ("z", "<i4"), ("intensity", "<u2"),
                      ("returns", "u1"), ("flags", "u1"), ("classification", "u1"),
                      ("user", "u1"), ("angle", "<i2"), ("source", "<u2"), ("time", "<f8"),
                      ("red", "<u2"), ("green", "<u2"), ("blue", "<u2")]
                     + [(f"e{i}", "<f8") for i in range(len(names))])
    points = np.zeros(n, dtype)
    for k, axis in enumerate("xyz"):
        points[axis] = np.round((xyz[:, k] - offset[k]) / scale).astype(np.int64)
    points["returns"] = 0x11                     # return 1 of 1
    for k, band in enumerate(("red", "green", "blue")):
        points[band] = rgb[:, k].astype(np.uint16) * 257
    for i, name in enumerate(names):
        points[f"e{i}"] = np.asarray(extra[name], float)

    vlrs = _vlr("LASF_Projection", 2112, wkt.encode() + b"\0", "OGC WKT")
    if names:
        vlrs += _vlr("LASF_Spec", 4, _extra_bytes(names), "Extra Bytes")
    n_vlrs = 2 if names else 1
    today = date.today()
    header = struct.pack(
        "<4sHH16sBB32s32sHHHIIBHI5I3d3d6dQQIQ15Q",
        b"LASF", 0, _WKT_BIT, b"\0" * 16, 1, 4, b"Groundwork".ljust(32, b"\0"),
        b"Groundwork QGIS plugin".ljust(32, b"\0"), today.timetuple().tm_yday, today.year,
        _HEADER_SIZE, _HEADER_SIZE + len(vlrs), n_vlrs, _FORMAT, dtype.itemsize,
        0, 0, 0, 0, 0, 0,                        # legacy counts: 0 for format 6 and up
        scale, scale, scale, *offset,
        hi[0], lo[0], hi[1], lo[1], hi[2], lo[2],
        0, 0, 0, n, n, *([0] * 14))
    assert len(header) == _HEADER_SIZE
    part = path.with_name(path.name + ".part")
    with open(part, "wb") as f:
        f.write(header)
        f.write(vlrs)
        f.write(points.tobytes())
    os.replace(part, path)
