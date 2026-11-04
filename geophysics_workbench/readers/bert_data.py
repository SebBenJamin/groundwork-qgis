"""pyGIMLi/BERT unified data format (``.data``, ``.ohm``, ``.dat``): measured readings, and
with a model response file the calculated values, i.e. the misfit of an inversion.

Layout::

    <number of electrodes>
    # x z            (or # x y z; tokens name the columns)
    <one row per electrode>
    <number of readings>
    # a b m n rhoa err ...
    <one row per reading>            electrodes are 1-based, 0 = absent (pole)
    [<number of topography points> ...]

The measured value is ``rhoa``, else ``r * k``, else ``u / i * k``. The response (BERT
``response.vector``, a pyGIMLi saved response) has one calculated value per reading.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..core.readings import Readings, check, readings_mesh
from .base import Reader, ReaderResult


def _decode(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _lines(text: str) -> list[str]:
    """Non-empty lines; the token lines (starting with #) are kept, other comments dropped."""
    out = []
    for line in text.splitlines():
        s = line.strip()
        if not s:
            continue
        out.append(s)
    return out


def _count(line: str) -> int | None:
    head = line.split("#")[0].split()
    if len(head) >= 1:
        try:
            return int(float(head[0]))
        except ValueError:
            return None
    return None


def _tokens(line: str) -> list[str]:
    return line.lstrip("#").replace("/", " ").lower().split()


def _distance_along(xyz: np.ndarray) -> np.ndarray:
    """x of a straight line as given; a bent line's cumulative distance."""
    if xyz.shape[1] >= 2:
        xy = xyz[:, :2] if xyz.shape[1] == 3 else np.column_stack([xyz[:, 0],
                                                                    np.zeros(len(xyz))])
        if xyz.shape[1] == 3 and np.ptp(xyz[:, 1]) > 1e-9:
            step = np.hypot(*np.diff(xy, axis=0).T)
            return np.concatenate([[0.0], np.cumsum(step)]) + xyz[0, 0]
    return xyz[:, 0].astype(float)


class BertDataReader(Reader):
    name = "bert_data"
    label = "pyGIMLi/BERT data (.data, .ohm) + response"

    def sniff(self, path: Path) -> bool:
        try:
            with open(path, "rb") as fh:
                head = fh.read(4096).decode("latin-1")
        except OSError:
            return False
        lines = _lines(head)
        if len(lines) < 3 or _count(lines[0]) is None or not lines[1].startswith("#"):
            return False
        if not {"x"} <= set(_tokens(lines[1])):
            return False
        n = _count(lines[0])
        return n is not None and n >= 2

    def read(self, path: Path, **options) -> ReaderResult:
        path = Path(path)
        lines = _lines(_decode(path))
        try:
            n_el = _count(lines[0])
            el_tok = _tokens(lines[1])
            el = np.array([[float(v) for v in ln.split()[:len(el_tok)]]
                           for ln in lines[2:2 + n_el]])
            i = 2 + n_el
            n_d = _count(lines[i])
            tok = _tokens(lines[i + 1])
            rows = [ln.split()[:len(tok)] for ln in lines[i + 2:i + 2 + n_d]]
            data = np.array([[float(v) for v in r] for r in rows])
        except (IndexError, ValueError, TypeError) as exc:
            raise ValueError(f"{path.name}: not a readable BERT/pyGIMLi data file ({exc})")
        if n_el is None or n_d is None or len(el) != n_el or data.shape[0] != n_d:
            raise ValueError(f"{path.name}: the electrode or reading count does not match "
                             f"the rows that follow")
        for need in ("a", "b", "m", "n"):
            if need not in tok:
                raise ValueError(f"{path.name}: no '{need}' column in '# {' '.join(tok)}'")
        col = {t: data[:, k] for k, t in enumerate(tok)}
        coords = el[:, [el_tok.index(t) for t in ("x", "y", "z") if t in el_tok]]
        x = _distance_along(coords) if "x" in el_tok else el[:, 0]
        idx = {t: col[t].astype(int) for t in "abmn"}
        bad = [t for t in "abmn" if (idx[t] < 0).any() or (idx[t] > n_el).any()]
        if bad:
            raise ValueError(f"{path.name}: electrode number out of range 1..{n_el} "
                             f"in column {', '.join(bad)}")
        pos = {t: np.where(idx[t] > 0, x[np.maximum(idx[t] - 1, 0)], np.nan) for t in "abmn"}
        if "rhoa" in col:
            measured = col["rhoa"]
        elif "r" in col and "k" in col:
            measured = col["r"] * col["k"]
        elif {"u", "i", "k"} <= set(col):
            measured = col["u"] / np.where(col["i"] != 0, col["i"], np.nan) * col["k"]
        else:
            raise ValueError(f"{path.name}: no apparent resistivity (rhoa, or r and k, or "
                             f"u, i and k) in '# {' '.join(tok)}'")
        error = col.get("err")
        calculated = np.full(n_d, np.nan)
        response = options.get("response")
        if response:
            resp_path = Path(response)
            if not resp_path.is_absolute():
                resp_path = path.parent / resp_path
            try:
                calc = np.loadtxt(resp_path, ndmin=1, dtype=float)
            except (OSError, ValueError) as exc:
                raise ValueError(f"response file {resp_path.name}: {exc}")
            if calc.ndim > 1:
                calc = calc[:, -1]
            if len(calc) != n_d:
                raise ValueError(f"response file {resp_path.name} has {len(calc)} values for "
                                 f"{n_d} readings: not the response of this data file")
            calculated = calc
        readings = Readings(pos["a"], pos["b"], pos["m"], pos["n"], measured, calculated,
                            error=None if error is None else np.asarray(error, float),
                            has_calculated=bool(response))
        check(readings)
        shown = "misfit" if readings.has_calculated else "measured"
        mesh = readings_mesh(readings, shown)
        return ReaderResult(mesh, "depth", {
            "reader": self.name, "source_name": path.name,
            "kind": "ert_misfit" if readings.has_calculated else "ert_measured",
            "n_readings": int(n_d), "n_electrodes": int(n_el),
            "response": str(response) if response else "",
            "rms_percent": readings.rms_percent(), "chi2": readings.chi2(),
        })
