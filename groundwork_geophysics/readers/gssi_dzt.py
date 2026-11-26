"""GSSI radar files (.dzt), read by Groundwork itself (no QGIS/Qt, no library).

What is covered, and nothing else:

* the 1,024-byte header of one channel, little-endian, with the data right after it;
* 8-, 16- and 32-bit samples;
* traces placed by the file's scans per metre, a spacing, or a coordinate file.

Refused with a plain message: files with several channels, other sample sizes, a header that
gives no samples or no time range, and files with fewer than two whole scans.

The header (byte offset, type, field; all little-endian)::

     0  uint16   rh_tag       header tag (not checked: the real files hold 0x0700 where the
                              description gives 0x00FF)
     2  uint16   rh_data      offset to the data: below 1,024 a count of 1,024-byte blocks,
                              else the data starts after 1,024 bytes per channel
     4  uint16   rh_nsamp     samples per scan
     6  uint16   rh_bits      bits per sample (8, 16, 32)
     8  int16    rh_zero      binary offset (0x80 / 0x8000); not used, see below
    10  float32  rhf_sps      scans per second
    14  float32  rhf_spm      scans per metre (0: recorded by time, without a distance wheel)
    18  float32  rhf_mpm      metres per mark
    22  float32  rhf_position position (ns)
    26  float32  rhf_range    range (ns): the recorded time window
    52  uint16   rh_nchan     number of channels
    54  float32  rhf_epsr     average dielectric constant
    58  float32  rhf_top      top position (m)
    62  float32  rhf_depth    range (m)
    98  char[14] rh_antname   antenna name, ends at the first zero byte

Where the meanings come from: GSSI's header description ("DZT file header" in the SIR system
manuals and GSSI's DZT file format note), which the open readers RGPR (readDZT.R), readgssi
(dzt.py) and GPRPy (gprIO_DZT.py) quote field by field in their source; all three agree on
every field used here, including the rule for rh_data. The samples: "Eight and sixteen bit
samples are unsigned integers. Thirty-two bit samples are signed integers" (GSSI's DZT file
format note as quoted in GPRPy); USGS Open-File Report 02-166 (GPR_SAMP) says the same for
8 and 16 bits. So 8-bit samples are stored minus 128 (int8), 16-bit minus 32,768 (int16), and
32-bit as they are (int32). rh_zero is not used for this: the real files checked hold 0 there.
Nothing else is done to the samples.

The first two samples of every scan are not radar data: USGS Open-File Report 02-166 says
"the first 2 samples ... are reserved". In the 150 real files checked (the open PANGAEA
dataset 10.1594/PANGAEA.922902) sample 1 counts the scans (0, 1, 2 …) and sample 2 holds marks
(0x6400 or 0x6800 on a marked scan, 0 elsewhere). They are kept as stored and lie before time
zero.

The sample step is range / samples: the open readers differ here (readgssi divides by the
samples, RGPR and GPRPy by samples − 1, 0.1 % apart for 1,024 samples); range / samples is the
rule the pulseEKKO reader follows too, where the real files' 150 ns over 750 points gives the
0.2 ns sampling interval the instrument offers. The first sample is at time 0 of the file;
rhf_position is not applied (it is reported in the notes when it is not 0). The velocity is
c / sqrt(rhf_epsr) when the dielectric is 1 or more; the real files' rhf_depth equals
range × velocity / 2 to within 4 cm, which confirms the reading of rhf_epsr.
"""
from __future__ import annotations

import re
import struct
from pathlib import Path

import numpy as np

from ..core.trace_section import TraceSection
from .base import Reader, ReaderResult
from .radar_info import (NANOSECOND, RadarInfo, check_position, provenance_of, trace_x,
                         velocity_from_dielectric)

SUFFIX = ".dzt"
HEADER_SIZE = 1024
#: the samples at the start of each scan that are not radar data (scan counter, marks)
RESERVED = 2
_FREQUENCY = re.compile(r"(?i)(\d+(?:\.\d+)?)\s*MHz")
_DTYPES = {8: np.uint8, 16: np.uint16, 32: np.int32}


def _parse(path: Path) -> tuple[RadarInfo, int]:
    """``(info, data offset)`` from the header and the file size."""
    name = path.name
    size = path.stat().st_size
    with path.open("rb") as fh:
        head = fh.read(HEADER_SIZE)
    if len(head) < HEADER_SIZE:
        raise ValueError(f"{name}: the file is shorter than a GSSI header (1,024 bytes).")
    rh_data, nsamp, bits = struct.unpack_from("<3H", head, 2)
    sps, spm, _mpm, position, rng = struct.unpack_from("<5f", head, 10)
    (nchan,) = struct.unpack_from("<H", head, 52)
    (epsr,) = struct.unpack_from("<f", head, 54)
    antenna = head[98:112].split(b"\0", 1)[0].decode("latin-1").strip()

    if nchan > 1:
        raise ValueError(f"{name}: this file holds {nchan} channels; Groundwork reads "
                         "single-channel files.")
    if nchan == 0:
        raise ValueError(f"{name}: the header gives 0 channels; this is not a GSSI file "
                         "Groundwork can read.")
    if bits not in _DTYPES:
        raise ValueError(f"{name}: {bits}-bit GSSI files are not supported yet.")
    if nsamp < 1:
        raise ValueError(f"{name}: the header gives no samples per scan.")
    if not (np.isfinite(rng) and rng > 0):
        raise ValueError(f"{name}: the header gives no time range.")
    if rh_data == 0:
        raise ValueError(f"{name}: the header gives no data offset.")
    offset = rh_data * HEADER_SIZE if rh_data < HEADER_SIZE else HEADER_SIZE * nchan

    notes = []
    scan = nsamp * bits // 8
    n, rest = divmod(max(0, size - offset), scan)
    if n < 2:
        raise ValueError(f"{name}: the file holds fewer than 2 whole scans.")
    if rest:
        notes.append(f"The file ends inside a scan: the last {rest} bytes are left out.")
    if nsamp > RESERVED:
        notes.append("Samples 1 and 2 of every scan are not radar data (GSSI keeps them for a "
                     "scan counter and marks); they lie before time zero.")
    trace_step = 1.0 / spm if np.isfinite(spm) and spm > 0 else None
    if trace_step is None:
        notes.append(f"The file was recorded by time ({sps:g} scans per second), without a "
                     "distance wheel; enter the trace spacing.")
    if np.isfinite(position) and position != 0:
        notes.append(f"The header gives a position of {position:g} ns; the times are not "
                     "shifted by it.")
    dielectric = float(epsr) if velocity_from_dielectric(epsr) is not None else None
    m = _FREQUENCY.search(antenna)
    info = RadarInfo(
        n_traces=int(n), n_samples=int(nsamp), step=float(rng) * NANOSECOND / nsamp,
        window=float(rng) * NANOSECOND, first=0.0, time_zero=None,
        velocity=velocity_from_dielectric(dielectric), dielectric=dielectric, antenna=antenna,
        frequency_mhz=float(m.group(1)) if m else None, trace_step=trace_step, start=0.0,
        length=(n - 1) * trace_step if trace_step is not None else None, notes=notes,
        bits=int(bits))
    return info, offset


def inspect(path) -> RadarInfo:
    """What the file's header says (no samples are read)."""
    return _parse(Path(path))[0]


def _samples(path: Path, info: RadarInfo, offset: int) -> np.ndarray:
    """The scans (traces x samples), decoded only: 8-bit minus 128 (int8), 16-bit minus 32,768
    (int16), 32-bit as stored (int32)."""
    count = info.n_traces * info.n_samples
    raw = np.fromfile(path, dtype=np.dtype(_DTYPES[info.bits]).newbyteorder("<"), count=count,
                      offset=offset).reshape(info.n_traces, info.n_samples)
    if info.bits == 8:
        return (raw ^ np.uint8(0x80)).view(np.int8)          # minus 128 in two's complement
    if info.bits == 16:
        return (raw ^ np.uint16(0x8000)).view(np.int16)      # minus 32,768
    return raw.astype(np.int32, copy=False)


class GssiDztReader(Reader):
    name = "gssi_dzt"
    label = "GSSI radar (.dzt)"

    def sniff(self, path: Path) -> bool:
        """By the name alone (.dzt); the file is not opened."""
        try:
            return Path(path).suffix.lower() == SUFFIX
        except Exception:
            return False

    def read(self, path: Path, **options) -> ReaderResult:
        """Options: ``position`` ("file", the default | "spacing" | "table"), ``spacing`` and,
        for "table", ``positions_file`` / ``positions_table`` / ``positions_columns`` with
        ``xy_to_distance``. Hang options (velocity, time zero, datum) are the provider's."""
        path = Path(path)
        check_position(options, path.name)
        info, offset = _parse(path)
        provenance = provenance_of(self.name, path.name, info)
        file_x = None
        if info.trace_step is not None:
            file_x = info.start + np.arange(info.n_traces, dtype=np.float64) * info.trace_step
        x = trace_x(path, options, file_x, info.n_traces, provenance)
        section = TraceSection(_samples(path, info, offset), x, info.first, info.step, "time",
                               numbers=np.arange(1, info.n_traces + 1))
        return ReaderResult(None, "depth", provenance, traces=section)
