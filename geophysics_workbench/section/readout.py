"""Text of the section panel's cursor readout. QGIS-free."""
from __future__ import annotations

SEP = " · "
UNIT_LABELS = {"ohm.m": "Ω·m", "ohm-m": "Ω·m", "ohmm": "Ω·m", "ohm m": "Ω·m"}


def unit_label(unit: str) -> str:
    return UNIT_LABELS.get((unit or "").strip().lower(), unit or "")


def format_value(value: float) -> str:
    """No decimals from 100 up, one from 1 up, three significant digits below 1 (so a
    small value never shows as 0.0); zero is "0.0"."""
    size = abs(value)
    if size >= 100:
        return f"{value:.0f}"
    if size >= 1 or size == 0:
        return f"{value:.1f}"
    return f"{value:.3g}"


BEYOND = "beyond stations"


def format_readout(s: float, z: float | None = None, depth: float | None = None,
                   xy=None, hits=(), beyond: bool = False, extra=()) -> str:
    """``s = 123.4 m · z = 61.2 m · depth = 3.8 m · X 432105.2 Y 5851234.9 · P1 model: 27.3 Ω·m``.
    Parts whose input is ``None`` are left out; ``hits`` are ``identify`` dicts. ``beyond``
    (s outside the station coverage) appends `` · beyond stations``. ``extra`` (context lines)
    follow on a second line, joined by `` · ``."""
    parts = [f"s = {s:.1f} m"]
    if z is not None:
        parts.append(f"z = {z:.1f} m")
    if depth is not None:
        parts.append(f"depth = {depth:.1f} m")
    if xy is not None:
        parts.append(f"X {xy[0]:.1f} Y {xy[1]:.1f}")
    for hit in hits:
        unit = unit_label(hit.get("unit", ""))
        text = f"{hit['name']}: {format_value(hit['value'])}" + (f" {unit}" if unit else "")
        reading = hit.get("reading")
        if reading:
            abmn = " ".join(f"{k.upper()} {reading[k]:.1f}" for k in "abmn"
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
