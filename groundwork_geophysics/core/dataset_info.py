"""What the user knows about a dataset (method, array, spacing, inversion, reference…), kept
in ``Dataset.provenance["info"]`` next to what the readers detected, and the one-line
provenance a plate prints. Only what is known is printed; nothing is invented."""
from __future__ import annotations

import math
from dataclasses import replace

from .dataset_types import TYPES, is_radar_kind, is_trace_kind, type_label

INFO_FIELDS = ("method", "array", "spacing", "date", "software", "reference", "note")
#: how a velocity function's rows are read, as the provenance names it
KIND_WORDS = {"average": "average", "interval": "interval", "rms": "RMS"}


def dataset_info(d) -> dict[str, str]:
    info = (d.provenance or {}).get("info") or {}
    return {k: str(info[k]).strip() for k in INFO_FIELDS
            if isinstance(info, dict) and k in info and str(info[k]).strip()}


def with_info(d, info: dict):
    """``d`` with its info replaced by the known, non-empty ``info`` fields."""
    clean = {k: str(v).strip() for k, v in info.items()
             if k in INFO_FIELDS and v is not None and str(v).strip()}
    provenance = dict(d.provenance or {})
    provenance["info"] = clean
    return replace(d, provenance=provenance)


def _size(v) -> str:
    """A cell size in metres, up to 2 decimals without trailing zeros (1.0 -> "1")."""
    return f"{float(v):.2f}".rstrip("0").rstrip(".")


def cells_text(d) -> str:
    """"1 × 0.5 m" when ``d``'s cells were averaged in blocks on reading, else ""."""
    cell = (d.provenance or {}).get("cell")
    if not (isinstance(cell, (list, tuple)) and len(cell) == 2):
        return ""
    return f"{_size(cell[0])} × {_size(cell[1])} m"


def averaged_from_text(d) -> str:
    """"averaged from 623241 cells of 0.25 × 0.1 m to 1 × 0.5 m", or "" (not averaged)."""
    p, to = d.provenance or {}, cells_text(d)
    was = p.get("cell_file")
    if not to or not (isinstance(was, (list, tuple)) and len(was) == 2):
        return ""
    from .numbers import fmt_count
    n = p.get("n_points_file")
    count = fmt_count(n) if isinstance(n, (int, float)) and not isinstance(n, bool) else "?"
    return f"averaged from {count} cells of {_size(was[0])} × {_size(was[1])} m to {to}"


def _speed(v: float) -> str:
    """A velocity in m/s as ``Velocity.text`` writes it (1 decimal at most)."""
    v = round(float(v), 1)
    return f"{v:.0f}" if v == int(v) else f"{v:.1f}"


def depth_text(d) -> str:
    """How a reflection section's depths come about and from where: "depth from v = 1500 m/s
    below the ground", "depth from a velocity function (1800–3400 m/s, RMS) below 500 m"
    (with ", corrected to the ground with 3200 m/s" for a section corrected to the ground),
    "depth section"; a radargram's in m/ns (``_radar_depth_text``); "" for other kinds and for
    a time section without a velocity."""
    if not is_trace_kind(d.kind):
        return ""
    options = d.reader_options or {}
    if is_radar_kind(d.kind):
        return _radar_depth_text(options)
    if (options.get("domain") or "time") == "depth":
        return "depth section"
    from .trace_section import Velocity
    velocity = Velocity.from_options(options)
    if velocity.value is None and not velocity.table:
        return ""
    said = velocity.text()
    if velocity.table:                          # which velocities: "(1800–3400 m/s, RMS)"
        said = f"{said[:-1]}, {KIND_WORDS.get(velocity.kind, velocity.kind)})"
    text = f"depth from {said}"
    zero, datum = options.get("zero") or "ground", options.get("datum")
    if zero == "ground":
        text += " below the ground"
    elif isinstance(datum, (int, float)) and not isinstance(datum, bool) and \
            math.isfinite(datum):
        text += f" below {_speed(datum)} m"
    rv = options.get("replacement_velocity")
    if zero == "datum_ground" and isinstance(rv, (int, float)) and rv > 0:
        text += f", corrected to the ground with {_speed(rv)} m/s"
    return text


def _radar_depth_text(options: dict) -> str:
    """A radargram's: "depth from v = 0.10 m/ns (ε 9.0)" (the velocity stored in m/s, said in
    m/ns with the dielectric constant it stands for), " below 372.5 m" when hung at a datum;
    "" without a usable velocity."""
    from .trace_section import C_M_PER_NS, Velocity
    v = Velocity.from_options(options).value
    if v is None or not (math.isfinite(v) and v > 0):
        return ""
    per_ns = v * 1e-9
    text = f"depth from v = {per_ns:.2f} m/ns"
    if per_ns <= C_M_PER_NS:
        text += f" (ε {(C_M_PER_NS / per_ns) ** 2:.1f})"
    datum = options.get("datum")
    if options.get("zero") == "datum" and isinstance(datum, (int, float)) and \
            not isinstance(datum, bool) and math.isfinite(datum):
        text += f" below {_speed(datum)} m"
    return text


def traces_text(d) -> str:
    """"1 970 traces × 1 125 samples, 4 ms" of a reflection section (from what the reader
    recorded; the sample step as the dataset reads it); "19 310 traces × 1 024 samples, 565 ns,
    270MHz" of a radargram (its recorded window and antenna); else ""."""
    p, options = d.provenance or {}, d.reader_options or {}
    n, ns = p.get("n_traces"), p.get("n_samples")
    if not is_trace_kind(d.kind) or not all(isinstance(v, (int, float)) for v in (n, ns)):
        return ""
    from .numbers import fmt_count, fmt_trim
    text = f"{fmt_count(n)} traces × {fmt_count(ns)} samples"
    if is_radar_kind(d.kind):                   # the recorded window and the antenna
        window, antenna = p.get("window"), str(p.get("antenna") or "").strip()
        if isinstance(window, (int, float)) and window > 0:
            text += f", {fmt_trim(window * 1e9, 1)} ns"
        return text + (f", {antenna}" if antenna else "")
    depth =(options.get("domain") or "time") == "depth"
    step = options.get("sample_step")
    if not isinstance(step, (int, float)):
        step = p.get("step")                    # the file's, s; a depth section: × 1000 in m
        step = step * 1000.0 if isinstance(step, (int, float)) and depth else step
    if isinstance(step, (int, float)) and step > 0:
        text += f", {fmt_trim(step, 3)} m" if depth else f", {fmt_trim(step * 1000.0, 3)} ms"
    return text


def provenance_line(profile_name: str, d) -> str:
    """e.g. "Transect 3 · ERT model: BERT inversion (Pohle et al. 2025) · dipole-dipole,
    1 m spacing · RMS 8.0 %"; a reflection section: "Line 4 · Seismic reflection · section ·
    depth from v = 1500 m/s". Parts with nothing known are left out."""
    info = dataset_info(d)
    t = TYPES.get(d.kind)
    head = f"{t.method} · {t.shows}" if t is not None and is_trace_kind(d.kind) else \
        type_label(d.kind)
    software = info.get("software", "")
    if software:
        head += f": {software}" + (f" ({info['reference']})" if info.get("reference") else "")
    elif info.get("reference"):
        head += f" ({info['reference']})"
    parts = [profile_name, head, depth_text(d)]
    layout = ", ".join(x for x in (info.get("array", ""),
                                   f"{info['spacing']} spacing" if info.get("spacing") else "")
                       if x)
    if layout:
        parts.append(layout)
    if cells_text(d):
        parts.append(f"averaged to {cells_text(d)} cells")
    rms = (d.provenance or {}).get("rms_percent")
    if isinstance(rms, (int, float)) and not isinstance(rms, bool):
        parts.append(f"RMS {rms:.1f} %")
    return " · ".join(p for p in parts if p)
