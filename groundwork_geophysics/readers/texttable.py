"""Tolerant text tables: any columns, text columns kept, unusable rows counted (no QGIS/Qt).

Unlike ``textcols`` (strictly numeric), a table here keeps every cell as text and pads short
rows with empty cells; numbers are read per column on demand. Lines starting with ``#`` or
``//`` and blank lines are dropped.

With ``delimiter="detect"`` the delimiter is the one ``textcols._delimiter`` picks for most
lines, and decimal commas follow the ``textcols`` rule (read as a point unless the delimiter
is a comma). With an explicit delimiter a comma is a decimal point only when
``decimal_comma`` is set.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from .textcols import _delimiter, _split, decode_bytes

DELIMITERS = {"comma": ",", "semicolon": ";", "tab": "\t", "space": " "}
_VOTE_LINES = 200


@dataclass(frozen=True)
class TableOptions:
    delimiter: str = "detect"           # "detect" or a key of DELIMITERS
    skip: int = 0                       # file lines dropped before anything else
    header: bool = True                 # the first remaining line holds the column names
    decimal_comma: bool = False

    def __post_init__(self):
        if self.delimiter != "detect" and self.delimiter not in DELIMITERS:
            raise ValueError(f"unknown delimiter {self.delimiter!r}")
        if self.skip < 0:
            raise ValueError("skip must not be negative")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TableOptions":
        return cls(delimiter=str(d.get("delimiter", "detect")), skip=int(d.get("skip", 0)),
                   header=bool(d.get("header", True)),
                   decimal_comma=bool(d.get("decimal_comma", False)))


def _number(cell: str, decimal_comma: bool) -> float:
    """The cell as a finite float, NaN when it is empty or not a number."""
    if decimal_comma:
        cell = cell.replace(",", ".")
    try:
        v = float(cell)
    except ValueError:
        return float("nan")
    return v if np.isfinite(v) else float("nan")


@dataclass
class TextTable:
    names: list[str]
    cells: list[list[str]]              # one list per row, every row n_columns long
    line_numbers: list[int]             # file line number (1-based) of each row
    decimal_comma: bool = False

    @property
    def n_columns(self) -> int:
        return len(self.names)

    @property
    def n_rows(self) -> int:
        return len(self.cells)

    def numeric(self, col: int) -> np.ndarray:
        """Column ``col`` as floats, NaN where the cell is not a number or missing."""
        return np.array([_number(row[col], self.decimal_comma) for row in self.cells],
                        dtype=float)

    def is_numeric(self, col: int) -> bool:
        """More than half of the rows hold a number in ``col``."""
        return bool(self.n_rows) and int(np.isfinite(self.numeric(col)).sum()) * 2 > self.n_rows


def _content_lines(text: str, skip: int) -> list[tuple[int, str]]:
    out = []
    for no, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if no > skip and s and not s.startswith(("#", "//")):
            out.append((no, s))
    return out


def _detect(lines: list[tuple[int, str]]) -> str:
    votes = Counter(_delimiter(s) for _, s in lines[:_VOTE_LINES])
    return votes.most_common(1)[0][0] if votes else " "


def _resolve(options: TableOptions, lines) -> tuple[str, bool]:
    """(delimiter character, whether commas inside cells are decimal points)."""
    if options.delimiter == "detect":
        delim = _detect(lines)
        return delim, delim != ","
    delim = DELIMITERS[options.delimiter]
    return delim, options.decimal_comma and delim != ","


def guess_options(path) -> TableOptions:
    """Skip the leading lines before the first line with the most common column count; that
    line is a header when most of its cells are not numbers. The delimiter stays "detect"."""
    lines = _content_lines(decode_bytes(Path(path).read_bytes()), 0)
    if not lines:
        return TableOptions()
    delim, decimal = _resolve(TableOptions(), lines)
    # raw field counts: a trailing delimiter (``1;2;3;`` with an empty comment) still counts
    counts = [len(s.split()) if delim == " " else len(s.split(delim)) for _, s in lines]
    tally = Counter(counts)
    common = max(tally, key=lambda n: (tally[n], n))
    no, first = lines[counts.index(common)]
    cells = [c for c in _split(first, delim) if c]
    numbers = sum(np.isfinite(_number(c, decimal)) for c in cells)
    return TableOptions(skip=no - 1, header=numbers * 2 <= len(cells))


def read_table(path, options: TableOptions = TableOptions(),
               max_rows: int | None = None) -> TextTable:
    """Read ``path`` as text cells (see module docstring); ``max_rows`` limits the data rows
    read, for a preview. ValueError when nothing is left after the skipped lines."""
    path = Path(path)
    lines = _content_lines(decode_bytes(path.read_bytes()), options.skip)
    if not lines:
        raise ValueError(f"{path.name}: no table rows found")
    delim, decimal = _resolve(options, lines)
    names: list[str] = []
    if options.header:
        names, lines = _split(lines[0][1], delim), lines[1:]
    if max_rows is not None:
        lines = lines[:max_rows]
    rows = [_split(s, delim) for _, s in lines]
    width = max([len(names)] + [len(r) for r in rows])
    names = [n or f"column {i}" for i, n in enumerate(names + [""] * (width - len(names)), 1)]
    cells = [r + [""] * (width - len(r)) for r in rows]
    return TextTable(names, cells, [no for no, _ in lines], decimal)


def select_rows(table: TextTable, cols: list[int]) -> tuple[np.ndarray, int, int | None]:
    """The rows with a number in every column of ``cols`` as a float array (rows, len(cols)),
    the count of rows skipped, and the file line number of the first skipped row (or None).
    ValueError when no row is usable."""
    arr = np.column_stack([table.numeric(c) for c in cols])
    ok = np.isfinite(arr).all(axis=1)
    if not ok.any():
        chosen = ", ".join(table.names[c] for c in cols)
        raise ValueError(f"no usable rows: no row has a number in every chosen column ({chosen})")
    bad = np.flatnonzero(~ok)
    first = table.line_numbers[int(bad[0])] if bad.size else None
    return arr[ok], int(bad.size), first
