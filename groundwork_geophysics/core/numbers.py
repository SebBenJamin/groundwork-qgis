"""Numbers as the user reads and types them: in QGIS's locale (the same decimal separator as
QGIS's own spin boxes), without thousands separators (counts in text: ``fmt_count``), never
"-0". Qt is imported lazily, so
core stays importable without QGIS."""
from __future__ import annotations

import math

MINUS = "−"


def _locale(locale=None):
    from qgis.PyQt.QtCore import QLocale
    loc = QLocale(locale) if locale is not None else QLocale()
    loc.setNumberOptions(loc.numberOptions() | QLocale.NumberOption.OmitGroupSeparator)
    return loc


def fmt(value: float, decimals: int = 1, locale=None, sign: bool = False) -> str:
    """``value`` with ``decimals`` decimals in QGIS's locale; ``sign`` puts "+" before
    positive values (and "−" before negative ones); a value that rounds to zero is "0"."""
    v = float(value)
    if round(v, decimals) == 0:
        v = 0.0
    text = _locale(locale).toString(abs(v), "f", decimals)
    if v < 0:
        return (MINUS if sign else "-") + text
    return ("+" + text) if sign and v > 0 else text


def fmt_trim(value: float, decimals: int = 2, locale=None) -> str:
    """Like ``fmt`` but without trailing zeros: 2.0 -> "2", 1.25 -> "1,25" (German)."""
    loc = _locale(locale)
    text = fmt(value, decimals, locale)
    if decimals > 0:
        text = text.rstrip("0").rstrip(loc.decimalPoint())
    return text


#: groups the digits of a count: a narrow no-break space reads the same in every locale
#: (a "." or "," could be taken for a decimal point)
COUNT_GROUP = " "


def fmt_count(n) -> str:
    """A count (cells, points, rows) grouped in threes: 2057769 -> "2 057 769". For text
    only: counts are never typed back, so the group separator cannot be misread there."""
    return f"{int(round(float(n))):,}".replace(",", COUNT_GROUP)


def fmt_sig(value: float, digits: int = 3, locale=None) -> str:
    """``value`` with ``digits`` significant digits in QGIS's locale (small values)."""
    return _locale(locale).toString(float(value), "g", digits)


def parse(text: str) -> float:
    """A number typed with "," or "." as the decimal separator (raises ValueError)."""
    t = str(text).strip().replace(" ", "").replace(MINUS, "-")
    if "," in t and "." in t:                       # "1.234,5" or "1,234.5"
        t = t.replace(".", "").replace(",", ".") if t.rfind(",") > t.rfind(".") \
            else t.replace(",", "")
    else:
        t = t.replace(",", ".")
    return float(t)


def parse_levels(text: str) -> tuple[float, ...]:
    """Contour levels typed as "10;30;100" (each read like ``parse``); blanks are skipped.
    Raises ValueError naming the part that is not a number."""
    out = []
    for part in str(text).split(";"):
        if not part.strip():
            continue
        message = f"“{part.strip()}” is not a number. Separate values with “;”."
        if len(part.split()) > 1:               # "10 30 100": not one number 1030100
            raise ValueError(message)
        try:
            value = parse(part)
        except ValueError:
            raise ValueError(message) from None
        if not math.isfinite(value):
            raise ValueError(message)
        out.append(value)
    return tuple(out)


def levels_text(levels) -> str:
    """The levels as typed: "10;30;2,5" in QGIS's locale."""
    return ";".join(fmt_trim(v, 6) for v in levels)
