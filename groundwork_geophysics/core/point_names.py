"""Electrode numbers read from point names (``ERT03_15``, ``E15``, ``15a``): the last or the
first run of digits. Each row gets a status; rows without a number and the earlier rows of a
repeated number do not become stations, and the user's corrections (typed per row) win over
the guess. Nothing is remembered: the corrections live as long as the caller keeps them.
Pure stdlib/NumPy."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace

import numpy as np

from .placement import Positions

OK, CORRECTED, NO_NUMBER, CLEARED, TWICE = "ok", "corrected", "no number", "cleared", "twice"
STATUS_TEXT = {OK: "ok", CORRECTED: "corrected", NO_NUMBER: "not an electrode",
               CLEARED: "not an electrode", TWICE: "measured twice, later row used"}
#: statuses the user should look at; a row the user cleared is their choice
TO_CHECK = (NO_NUMBER, TWICE)
_DIGITS = re.compile(r"[0-9]+")


@dataclass(frozen=True)
class NameRow:
    name: str
    guess: int | None           # the number read from the name
    number: int | None          # the number the row ends with (the correction or the guess)
    status: str


def number_from_name(name: str, which: str = "last") -> int | None:
    """The last (or first) run of digits in ``name`` as a number; None without a digit."""
    runs = _DIGITS.findall(name or "")
    if not runs:
        return None
    return int(runs[0] if which == "first" else runs[-1])


def read_names(names: list[str], which: str = "last",
               corrections: dict[int, int | None] | None = None) -> list[NameRow]:
    """Each name's row in file order. ``corrections``: row index -> the number typed, or None
    for a row cleared. Of rows ending with the same number, the last one is used."""
    corrections = corrections or {}
    guesses = [number_from_name(n, which) for n in names]
    numbers = [corrections[i] if i in corrections else g for i, g in enumerate(guesses)]
    last_row = {n: i for i, n in enumerate(numbers) if n is not None}
    rows = []
    for i, (name, guess, number) in enumerate(zip(names, guesses, numbers)):
        if number is None:
            status = CLEARED if i in corrections else NO_NUMBER
        elif last_row[number] != i:
            status = TWICE
        else:
            status = CORRECTED if i in corrections else OK
        rows.append(NameRow(name, guess, number, status))
    return rows


def list_order(rows: list[NameRow]) -> list[int]:
    """Row indices for the list: rows to check first, then the others, each in file order."""
    check = [i for i, r in enumerate(rows) if r.status in TO_CHECK]
    return check + [i for i, r in enumerate(rows) if r.status not in TO_CHECK]


def names_title(rows: list[NameRow]) -> str:
    """The row list's group title, e.g. "Electrodes from Names (75 rows, 2 to check)"."""
    n = len(rows)
    text = f"{n} row{'s' if n != 1 else ''}"
    check = sum(r.status in TO_CHECK for r in rows)
    return f"Electrodes from Names ({text}, {check} to check)" if check else \
        f"Electrodes from Names ({text})"


def apply_names(positions: Positions, which: str = "last",
                corrections: dict[int, int | None] | None = None
                ) -> tuple[Positions, list[NameRow]]:
    """(the positions of the rows that become stations, numbered from their names; every
    row as read). ValueError when the positions carry no names."""
    if positions.names is None:
        raise ValueError("The positions have no point names.")
    rows = read_names(list(positions.names), which, corrections)
    keep = np.array([r.status in (OK, CORRECTED) for r in rows], dtype=bool)
    inline = None if positions.inline is None else np.asarray(positions.inline, dtype=float)[keep]
    used = replace(positions, xyz=np.asarray(positions.xyz, dtype=float)[keep],
                   numbers=np.array([r.number for r in rows if r.status in (OK, CORRECTED)],
                                    dtype=int),
                   inline=inline,
                   names=[r.name for r in rows if r.status in (OK, CORRECTED)])
    return used, rows


def station_label(name: str, number: int) -> str:
    """How a station is named to the user: its point name, else its number."""
    name = (name or "").strip()
    return name or str(int(number))
