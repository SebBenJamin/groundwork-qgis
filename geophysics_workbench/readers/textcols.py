"""Tolerant reader for numeric text tables (no QGIS/Qt).

Delimiter rule, applied to the first data line:
  1. contains ';'  -> semicolon
  2. contains a tab -> tab
  3. contains ',' and either no whitespace at all, or every comma is followed by
     whitespace -> comma (``x,z,rho`` / ``1.5,2,30``); a comma is then never decimal
  4. otherwise whitespace; commas inside numeric tokens are decimal commas (``0,5 1,25``)
With semicolon, tab or whitespace delimiters a decimal comma is read as a point.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np

_SNIFF_BYTES = 4096


def decode_bytes(raw: bytes) -> str:
    """UTF-8 (BOM tolerated) with Latin-1 fallback."""
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("latin-1")


def _delimiter(line: str) -> str:
    if ";" in line:
        return ";"
    if "\t" in line:
        return "\t"
    if "," in line and (not re.search(r"\s", line) or not re.search(r",\S", line)):
        return ","
    return " "


def _split(line: str, delim: str) -> list[str]:
    if delim == " ":
        return line.split()
    return [t.strip() for t in line.split(delim)]


def _to_float(tok: str, delim: str) -> float:
    if delim != ",":
        tok = tok.replace(",", ".")
    return float(tok)


def _is_numeric(tokens: list[str], delim: str) -> bool:
    try:
        for t in tokens:
            _to_float(t, delim)
    except ValueError:
        return False
    return bool(tokens)


def parse_columns(text: str, name: str = "<text>") -> tuple[list[str] | None, np.ndarray]:
    """Parse ``text`` (see module docstring). ValueError messages name ``name`` and the line."""
    lines = [(no, raw.strip()) for no, raw in enumerate(text.splitlines(), 1)
             if raw.strip() and not raw.strip().startswith("//")]
    if not lines:
        raise ValueError(f"{name}: file is empty")

    first_is_hash = lines[0][1].startswith("#")
    hash_header = lines[0] if first_is_hash else None
    body = [(no, s) for no, s in lines if not s.startswith("#")]
    if not body:
        raise ValueError(f"{name}: no numeric data rows found")

    # a non-numeric first body line is a text header; the delimiter comes from the first data line
    first_delim = _delimiter(body[0][1])
    header = None
    if not _is_numeric(_split(body[0][1], first_delim), first_delim):
        header_line, body = body[0][1], body[1:]
        if not body:
            raise ValueError(f"{name}: no numeric data rows found")
    else:
        header_line = None
    delim = _delimiter(body[0][1])
    if header_line is not None:
        header = _split(header_line, delim)
    elif hash_header is not None:
        toks = _split(hash_header[1].lstrip("#").strip(), delim)
        if toks and not _is_numeric(toks, delim) and len(toks) == len(_split(body[0][1], delim)):
            header = toks

    rows, width = [], None
    for no, s in body:
        try:
            vals = [_to_float(t, delim) for t in _split(s, delim)]
        except ValueError:
            raise ValueError(f"{name}, line {no}: non-numeric value in {s[:60]!r}") from None
        if width is None:
            width = len(vals)
        elif len(vals) != width:
            raise ValueError(f"{name}, line {no}: expected {width} columns, found {len(vals)}")
        rows.append(vals)
    return header, np.array(rows, dtype=float)


def read_columns(path) -> tuple[list[str] | None, np.ndarray]:
    """Read a numeric table: returns (header tokens or None, float array (rows, cols)).

    Handles ``#``/``//`` comment lines (a leading ``#`` line with non-numeric tokens
    matching the column count counts as the header), a non-numeric first line as header,
    and the delimiters described in the module docstring. Raises ValueError (naming file
    and line) for files without numeric rows or with ragged / non-numeric rows."""
    path = Path(path)
    return parse_columns(decode_bytes(path.read_bytes()), path.name)


def sniff_columns(path) -> tuple[list[str] | None, np.ndarray] | None:
    """Cheap probe on the first ~4 KB: (header, parsed rows) or None. Never raises."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(_SNIFF_BYTES + 1)
        text = decode_bytes(raw[:_SNIFF_BYTES])
        if len(raw) > _SNIFF_BYTES and "\n" in text:
            text = text[: text.rindex("\n")]          # drop the possibly cut last line
        return parse_columns(text, Path(path).name)
    except Exception:
        return None
