"""Which profile a data file belongs to, guessed from the file's name: Add Data with several
files proposes it, and the user can change it. Pure stdlib.

A profile named "<word> <number>" ("Line 8", "Line 2B", "ERT02", "Transect 3") matches a
file name holding the number after the word or after its first letter: "JWD_L8_DD",
"line_8", "ERT2_model", "T3_result". The number must stand whole ("L2B" is not Line 2, a year
is not Line 8). A name without a number matches when the file name holds it whole. Only a
single matching profile is a guess."""
from __future__ import annotations

import re

_NUMBERED = re.compile(r"^(.*?)_?(\d+)([a-z]?)$")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _pattern(name: str) -> re.Pattern | None:
    n = _norm(name)
    if not n:
        return None
    m = _NUMBERED.match(n)
    if m is None or not m.group(1):
        return re.compile(rf"(?<![a-z0-9]){re.escape(n)}(?![a-z0-9])")
    word, number, letter = m.group(1).strip("_"), m.group(2).lstrip("0") or "0", m.group(3)
    prefixes = "|".join(re.escape(p) for p in dict.fromkeys((word, word[0])))
    return re.compile(rf"(?<![a-z0-9])(?:{prefixes})_?0*{number}{letter}(?![0-9a-z])")


def guess_profile(stem: str, profiles) -> str | None:
    """The id of the one profile among ``profiles`` ((id, name) pairs) that the file name
    ``stem`` names, or None when none or several do."""
    text = _norm(stem)
    hits = []
    for pid, name in profiles:
        pattern = _pattern(name or "")
        if pattern is not None and pattern.search(text):
            hits.append(pid)
    return hits[0] if len(hits) == 1 else None
