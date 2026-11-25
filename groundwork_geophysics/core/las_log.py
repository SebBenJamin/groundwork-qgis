"""Well logs from LAS files (Log ASCII Standard 1.2 and 2.0, as most logging software
writes them): one well per file, its depth index converted to metres, every other curve with
its unit; null values become gaps. LAS 3.0 is refused with a message. No Qt, no QGIS."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

#: depth index mnemonics, and metres per unit
DEPTH_MNEMONICS = ("DEPT", "DEPTH", "DEP", "MD", "TVD")
_TO_METRES = {"": 1.0, "M": 1.0, "METRE": 1.0, "METRES": 1.0, "METER": 1.0, "METERS": 1.0,
              "FT": 0.3048, "F": 0.3048, "FEET": 0.3048, "FOOT": 0.3048, ".1IN": 0.00254,
              "CM": 0.01, "MM": 0.001}


@dataclass
class LasCurve:
    mnemonic: str
    unit: str = ""
    description: str = ""
    values: np.ndarray = field(default_factory=lambda: np.zeros(0), repr=False)


@dataclass
class LasLog:
    well: str = ""
    uwi: str = ""
    version: str = ""
    depth: np.ndarray = field(default_factory=lambda: np.zeros(0), repr=False)  # metres
    depth_unit: str = ""            # as in the file
    curves: list = field(default_factory=list)                      # [LasCurve], not depth
    path: str = ""


_LINE = re.compile(r"^\s*([^.\s][^.]*?)\s*\.(\S*)\s*(.*)$")


def _header(line: str) -> tuple[str, str, str, str] | None:
    """(mnemonic, unit, data, description) of a header line, or None."""
    m = _LINE.match(line)
    if m is None:
        return None
    mnem, unit, rest = m.group(1).strip(), m.group(2), m.group(3)
    data, _colon, desc = rest.rpartition(":") if ":" in rest else (rest, "", "")
    return mnem.upper(), unit, data.strip(), desc.strip()


def _sections(text: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    current = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.lstrip().startswith("~"):
            current = line.lstrip()[1:2].upper()
            out.setdefault(current, [])
            continue
        if current is not None:
            out[current].append(line)
    return out


def read_las_log(path) -> LasLog:
    """The log in ``path``; raises ValueError (in the user's words) for files that cannot be
    used."""
    path = Path(path)
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    sec = _sections(text)
    if "V" not in sec or "A" not in sec or "C" not in sec:
        raise ValueError(f"{path.name} is not a LAS file (no ~Version, ~Curve or ~ASCII "
                         "section)")
    version = {h[0]: h for h in map(_header, sec["V"]) if h}
    vers = version.get("VERS", ("", "", "", ""))[2]
    if vers.startswith("3"):
        raise ValueError(f"{path.name}: LAS 3.0 files are not supported yet; save it as "
                         "LAS 2.0 in your logging software")
    wrapped = version.get("WRAP", ("", "", "NO", ""))[2].upper().startswith("Y")
    well = {h[0]: h for h in map(_header, sec.get("W", [])) if h}

    def well_text(key: str) -> str:
        h = well.get(key)
        if h is None:
            return ""
        return h[2] or (h[3] if vers.startswith("1") else "")      # 1.2: the name after ":"
    null = None
    if "NULL" in well:
        try:
            null = float(well["NULL"][2])
        except ValueError:
            null = None
    curves = [h for h in map(_header, sec["C"]) if h]
    if not curves:
        raise ValueError(f"{path.name} lists no curves")
    first = curves[0][0]
    if first not in DEPTH_MNEMONICS:
        raise ValueError(f"{path.name}: the first curve ({first}) is not a depth; only "
                         "logs indexed by depth can be shown")
    unit = curves[0][1].upper()
    if unit not in _TO_METRES:
        raise ValueError(f"{path.name}: unknown depth unit '{curves[0][1]}'")
    numbers = " ".join(sec["A"]).replace(",", " ").split()
    try:
        values = np.array([float(v) for v in numbers], dtype=float)
    except ValueError:
        raise ValueError(f"{path.name}: the data section holds text, not numbers") from None
    n = len(curves)
    if values.size % n:
        if not wrapped:
            raise ValueError(f"{path.name}: the data rows do not have {n} values each")
        values = values[: values.size - values.size % n]
    table = values.reshape(-1, n)
    if null is not None:
        table[np.isclose(table, null)] = np.nan
    depth = table[:, 0] * _TO_METRES[unit]
    return LasLog(well=well_text("WELL"), uwi=well_text("UWI") or well_text("API"),
                  version=vers.split()[0] if vers else "", depth=depth,
                  depth_unit=curves[0][1],
                  curves=[LasCurve(m, u, d, table[:, i + 1])
                          for i, (m, u, _data, d) in enumerate(curves[1:])],
                  path=str(path))


def _norm(text: str) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(text).upper())


def guess_borehole(log: LasLog, stem: str, ids) -> str | None:
    """The borehole id ``log`` belongs to: its well name or UWI equal to an id (ignoring
    case, spaces and punctuation), else the id the file name starts with (the longest); only
    a unique hit counts."""
    by_norm: dict[str, list[str]] = {}
    for i in ids:
        by_norm.setdefault(_norm(i), []).append(str(i))
    for name in (log.well, log.uwi):
        hits = by_norm.get(_norm(name)) if _norm(name) else None
        if hits and len(hits) == 1:
            return hits[0]
    s = _norm(stem)
    prefixes = [k for k in by_norm if k and s.startswith(k)]
    if not prefixes:
        return None
    longest = max(len(k) for k in prefixes)
    best = [i for k in prefixes if len(k) == longest for i in by_norm[k]]
    return best[0] if len(best) == 1 else None
