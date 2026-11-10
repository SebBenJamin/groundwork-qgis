"""Reader errors as the user reads them: the file named, plain words (no internal option or
parameter names), and the next step at the end."""
from __future__ import annotations

from pathlib import Path

NEXT_STEP = "Check that the file is a section model or data file, and its format."
#: internal phrasings -> plain words (applied to the message text)
_PLAIN = (
    ("All triangles were filtered out; increase max_edge or check the points",
     "no section could be built from its points (they are too far apart, or the file is not "
     "a model)"),
    ("z_kind must be one of", "unknown height meaning; expected one of"),
)
_STEPS = ("Check", "Choose", "Open", "Remove", "Pick", "Select")


def plain_error(exc: BaseException, path=None, next_step: str = NEXT_STEP) -> str:
    """One line for the user about ``exc`` while reading ``path``."""
    name = Path(path).name if path else ""
    if isinstance(exc, FileNotFoundError):
        where = getattr(exc, "filename", None) or (str(path) if path else "")
        missing = Path(where).name if where else name
        text = f"{missing}: file not found"
        if where:
            text += f" ({where})"
        if missing != name and name:
            text = f"{name}: {text}"
        return f"{text}. Check the path, or remove the layer and add the file again."
    text = str(exc).strip() or type(exc).__name__
    for internal, plain in _PLAIN:
        text = text.replace(internal, plain)
    text = text.replace("z_kind", "height meaning")
    if name and name not in text:
        text = f"{name}: {text}"
    text = text.rstrip(".") + "."
    last = text.rstrip(".").split(". ")[-1]
    if not last.startswith(_STEPS):
        text += f" {next_step}"
    return text
