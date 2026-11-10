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

The measured value is ``rhoa``, else ``r * k``, else ``u / i * k``. Column units
(``err/%``, ``u/mV``, ``i/mA``) are applied; an unknown unit on a used column is an error.
Electrode x is taken as given (2D pyGIMLi files keep the elevation in y); a 3D layout is
refused; remote electrodes (far off the line) count as absent poles. The response (BERT
``response.vector``, a pyGIMLi saved response) has one calculated value per reading.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..core.pseudo import remote_electrodes
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


def _tokens(line: str) -> list[tuple[str, str]]:
    """Column (name, unit) pairs: ``err/%`` is ("err", "%"), ``rhoa`` is ("rhoa", "")."""
    out = []
    for tok in line.lstrip("#").split():
        name, _sep, unit = tok.partition("/")
        out.append((name.lower(), unit.lower()))
    return out


#: unit factors to SI-like base units for the columns this reader uses; any other unit on
#: a used column is refused (never guessed)
UNITS = {"rhoa": {"": 1.0, "ohmm": 1.0, "ohm.m": 1.0, "ohm*m": 1.0},
         "r": {"": 1.0, "ohm": 1.0},
         "k": {"": 1.0, "m": 1.0},
         "err": {"": 1.0, "%": 0.01},
         "u": {"": 1.0, "v": 1.0, "mv": 1e-3, "uv": 1e-6},
         "i": {"": 1.0, "a": 1.0, "ma": 1e-3, "ua": 1e-6}}


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
        if "x" not in [name for name, _u in _tokens(lines[1])]:
            return False
        n = _count(lines[0])
        return n is not None and n >= 2

    def read(self, path: Path, **options) -> ReaderResult:
        path = Path(path)
        lines = _lines(_decode(path))
        try:
            n_el = _count(lines[0])
            el_tok = [name for name, _u in _tokens(lines[1])]
            el = np.array([[float(v) for v in ln.split()[:len(el_tok)]]
                           for ln in lines[2:2 + n_el]])
            i = 2 + n_el
            n_d = _count(lines[i])
            tok_units = _tokens(lines[i + 1])
            tok = [name for name, _u in tok_units]
            rows = [ln.split()[:len(tok)] for ln in lines[i + 2:i + 2 + n_d]]
            data = np.array([[float(v) for v in r] for r in rows])
        except (IndexError, ValueError, TypeError):
            # the file's layout is not BERT's (counts, electrode block, data block): say so
            # in the user's terms, never with Python's own message
            raise ValueError(f"{path.name}: not a BERT/pyGIMLi data file (expected the "
                             "electrode count, the electrodes, the reading count and the "
                             "readings)") from None
        if n_el is None or n_d is None or len(el) != n_el or data.shape[0] != n_d:
            raise ValueError(f"{path.name}: the electrode or reading count does not match "
                             f"the rows that follow")
        if data.ndim != 2 or data.shape[1] != len(tok) or el.shape[1] != len(el_tok):
            raise ValueError(f"{path.name}: the column names ('# {lines[i + 1].lstrip('#')}') "
                             f"do not match the number of values per row")
        if len(set(tok)) != len(tok):
            raise ValueError(f"{path.name}: a column name appears twice in "
                             f"'# {lines[i + 1].lstrip('#').strip()}'")
        for need in ("a", "b", "m", "n"):
            if need not in tok:
                raise ValueError(f"{path.name}: no '{need}' column in '# {' '.join(tok)}'")
        col = {}
        for k, (name, unit) in enumerate(tok_units):
            factor = 1.0
            if name in UNITS:
                if unit not in UNITS[name]:
                    raise ValueError(f"{path.name}: unknown unit '{unit}' for column "
                                     f"'{name}' (known: {', '.join(u or '(none)' for u in UNITS[name])})")
                factor = UNITS[name][unit]
            col[name] = data[:, k] * factor
        x = el[:, el_tok.index("x")] if "x" in el_tok else el[:, 0]
        if "y" in el_tok and "z" in el_tok and np.ptp(el[:, el_tok.index("y")]) > 1e-9 \
                and np.ptp(el[:, el_tok.index("z")]) > 1e-9:
            raise ValueError(f"{path.name}: electrodes vary in both y and z (a 3D layout); "
                             f"a section needs a line: x along it, elevation in y or z")
        x = np.where(remote_electrodes(x), np.nan, x)       # remote poles count as absent
        idx = {t: col[t].astype(int) for t in "abmn"}
        bad = [t for t in "abmn" if (idx[t] < 0).any() or (idx[t] > n_el).any()]
        if bad:
            raise ValueError(f"{path.name}: electrode number out of range 1..{n_el} "
                             f"in column {', '.join(bad)}")
        pos = {t: np.where(idx[t] > 0, x[np.maximum(idx[t] - 1, 0)], np.nan) for t in "abmn"}
        if not (np.isfinite(pos["a"]) | np.isfinite(pos["b"])).all() or \
                not (np.isfinite(pos["m"]) | np.isfinite(pos["n"])).all():
            raise ValueError(f"{path.name}: a reading has no current or no potential "
                             f"electrode on the line")
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
                raise ValueError(f"response file {resp_path.name} has several columns: "
                                 f"expected one calculated value per line")
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
