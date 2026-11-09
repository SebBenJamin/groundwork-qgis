"""Field notes: what the field crew experienced along a profile (no QGIS/Qt).

A note sits at a chainage (``s_to`` is None) or along a stretch ``s_from``..``s_to``, with a
text, an optional free category and a "shown" switch. Chainage is the truth; the map
geometry is derived. Positions can be entered as station (electrode) names."""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np


@dataclass
class FieldNote:
    id: str
    profile_id: str
    s_from: float
    s_to: float | None          # None: a note at one chainage
    text: str
    category: str = ""
    shown: bool = True
    stations: str = ""          # optional label of the position, e.g. "23–28"
    author: str = ""
    created: str = ""
    modified: str = ""


def note_range(note: FieldNote) -> tuple[float, float]:
    """(low, high) chainage; a point note gives the same value twice."""
    if note.s_to is None:
        return float(note.s_from), float(note.s_from)
    return float(min(note.s_from, note.s_to)), float(max(note.s_from, note.s_to))


def clamp_to_profile(note: FieldNote, length: float) -> tuple[FieldNote, bool]:
    """The note kept within 0..``length``; the flag says whether anything was cut."""
    lo, hi = note_range(note)
    c_lo, c_hi = min(max(lo, 0.0), length), min(max(hi, 0.0), length)
    clamped = (c_lo, c_hi) != (lo, hi)
    if note.s_to is None:
        return replace(note, s_from=c_lo), clamped
    return replace(note, s_from=c_lo, s_to=c_hi), clamped


def stations_to_chainage(names: list[str], chainages: np.ndarray, first: str,
                         last: str | None) -> tuple[float, float | None]:
    """Chainages of the stations named ``first`` (and ``last``), compared as stripped text.
    ``ValueError`` for a name that is not a station of the profile."""
    index = {str(n).strip(): i for i, n in enumerate(names)}

    def at(name: str) -> float:
        key = str(name).strip()
        if key not in index:
            raise ValueError(f"no station named {key!r} on this profile")
        return float(np.asarray(chainages, float)[index[key]])

    return at(first), (None if last is None or not str(last).strip() else at(last))
