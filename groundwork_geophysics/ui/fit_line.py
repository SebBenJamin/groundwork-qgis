"""The one-line fit report of a placement, shown by Add Data and Profile Properties: how far the
known points move when the model is pinned to them, in the warning style when that is more than
half the gap between them."""
from __future__ import annotations

#: the dialogs' warning look (the colour the warnings already used)
WARNING_STYLE = "color: #9a5b00;"
#: the second sentence of a fit line that warns
FIT_WARNING = "Check the station spacing or the station numbers."


def fit_line(fit, guessed: bool = False, note: str = "") -> tuple[str, bool]:
    """(text, warn) for ``fit`` (a ``FitReport`` or None) and the resolution's ``note``:
    the report when it has two known points or more, with ``FIT_WARNING`` when it warns."""
    text = fit.text(guessed=guessed) if fit is not None and fit.n >= 2 else ""
    warn = bool(text) and bool(fit.warn)
    if warn:
        text = f"{text}. {FIT_WARNING}"
    if note:
        text = f"{text} {note}" if warn else "; ".join(t for t in (text, note) if t)
    return text, warn


def show_fit(label, text: str, warn: bool) -> None:
    """Put a fit line on ``label``, in the warning style when it warns."""
    label.setText(text)
    label.setStyleSheet(WARNING_STYLE if warn else "")
