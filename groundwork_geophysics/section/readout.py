"""Text of the section panel's cursor readout. QGIS-free."""
from __future__ import annotations

from ..core.numbers import fmt, fmt_sig

SEP = " · "
UNIT_LABELS = {"ohm.m": "Ω·m", "ohm-m": "Ω·m", "ohmm": "Ω·m", "ohm m": "Ω·m"}


def unit_label(unit: str) -> str:
    return UNIT_LABELS.get((unit or "").strip().lower(), unit or "")


def format_value(value: float) -> str:
    """No decimals from 100 up, one from 1 up, three significant digits below 1 (so a
    small value never shows as 0.0); zero is "0.0"."""
    size = abs(value)
    if size >= 100:
        return f"{fmt(value, 0)}"
    if size >= 1 or size == 0:
        return f"{fmt(value, 1)}"
    return fmt_sig(value, 3)


BEYOND = "beyond stations"


def format_readout(s: float, z: float | None = None, depth: float | None = None,
                   xy=None, hits=(), beyond: bool = False, extra=()) -> str:
    """``s = 123.4 m · z = 61.2 m · depth = 3.8 m · X 432105.2 Y 5851234.9 · P1 model: 27.3 Ω·m``.
    Parts whose input is ``None`` are left out; ``hits`` are ``identify`` dicts (a trace
    section's: ``Line 1: 0.42 · trace 123 · 245.0 ms · 183.8 m below time zero``; no time
    for a depth section, whose depth is "below depth zero"). ``beyond``
    (s outside the station coverage) appends `` · beyond stations``. ``extra`` (context lines)
    follow on a second line, joined by `` · ``."""
    parts = [f"s = {fmt(s, 1)} m"]
    if z is not None:
        parts.append(f"z = {fmt(z, 1)} m")
    if depth is not None:
        parts.append(f"depth = {fmt(depth, 1)} m")
    if xy is not None:
        parts.append(f"X {fmt(xy[0], 1)} Y {fmt(xy[1], 1)}")
    for hit in hits:
        unit = unit_label(hit.get("unit", ""))
        text = f"{hit['name']}: {format_value(hit['value'])}" + (f" {unit}" if unit else "")
        trace = hit.get("trace")
        if trace:                                  # a trace section: trace, time, depth
            text += f"{SEP}trace {trace['number']}"
            timed = trace.get("time") is not None
            if timed:
                text += f"{SEP}{fmt(trace['time'] * 1000.0, 1)} ms"
            text += f"{SEP}{fmt(trace['depth'], 1)} m below {'time' if timed else 'depth'} zero"
        reading = hit.get("reading")
        if reading:
            abmn = " ".join(f"{k.upper()} {fmt(reading[k], 1)}" for k in "abmn"
                            if reading[k] == reading[k])          # skip absent poles (NaN)
            vals = f"meas {format_value(reading['measured'])}"
            if reading["calculated"] == reading["calculated"]:
                vals += f" · calc {format_value(reading['calculated'])}"
            text += f" ({abmn} · {vals} {unit_label('ohm.m')})"
        parts.append(text)
    if beyond:
        parts.append(BEYOND)
    text = SEP.join(parts)
    return text + "\n" + SEP.join(extra) if extra else text
