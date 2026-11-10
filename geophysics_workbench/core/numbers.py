"""Numbers as the user reads and types them: in QGIS's locale (the same decimal separator as
QGIS's own spin boxes), without thousands separators, never "-0". Qt is imported lazily, so
core stays importable without QGIS."""
from __future__ import annotations

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
