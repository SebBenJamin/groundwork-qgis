"""R2 / ResIPy inversion misfit: ``f001_err.dat``.

Format (R2 manual, v3.2 and later): a header line, then one row per reading with the four
electrode numbers, the normalised misfit, the observed apparent resistivity, the calculated
apparent resistivity of the model, the original and the final data weight (standard
deviation in data units) and a flag. Electrodes are numbers only: their positions come from
``electrodes.dat`` (x, y[, z] per electrode, as ResIPy writes it next to its R2 files), or the
``electrodes`` reader option. Electrode order within a reading changes neither the misfit
nor the pseudo-depth (reciprocity), so the four columns are taken as given.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..core.readings import Readings, check, readings_mesh
from .base import Reader, ReaderResult

ELECTRODE_FILES = ("electrodes.dat", "electrodes.csv")


def _electrode_x(path: Path, option: str | None) -> np.ndarray:
    candidates = [Path(option)] if option else [path.parent / n for n in ELECTRODE_FILES]
    for c in candidates:
        if not c.is_absolute():
            c = path.parent / c
        if c.is_file():
            try:
                a = np.loadtxt(c, delimiter="," if c.suffix == ".csv" else None,
                               skiprows=1 if c.suffix == ".csv" else 0, ndmin=2)
            except ValueError as exc:
                raise ValueError(f"{c.name}: cannot read electrode positions ({exc})")
            return a[:, 0].astype(float)
    raise ValueError(f"{path.name} numbers its electrodes but no electrode positions were "
                     f"found: put ResIPy's electrodes.dat next to it")


class R2ErrReader(Reader):
    name = "r2_err"
    label = "R2 / ResIPy misfit (f001_err.dat)"

    def sniff(self, path: Path) -> bool:
        try:
            with open(path, "rb") as fh:
                head = fh.read(512).decode("latin-1").lower()
        except OSError:
            return False
        first = head.splitlines()[0] if head else ""
        return "normalised" in first or ("calculated" in first and "observed" in first)

    def read(self, path: Path, **options) -> ReaderResult:
        path = Path(path)
        try:
            table = np.loadtxt(path, skiprows=1, ndmin=2)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{path.name}: not a readable R2 error file ({exc})")
        if table.shape[1] < 7:
            raise ValueError(f"{path.name}: expected at least 7 columns (4 electrodes, "
                             f"misfit, observed, calculated), found {table.shape[1]}")
        x = _electrode_x(path, options.get("electrodes"))
        idx = table[:, :4].astype(int)
        if (idx < 0).any() or (idx > len(x)).any():
            raise ValueError(f"{path.name}: electrode number out of range 1..{len(x)}")
        pos = [np.where(idx[:, k] > 0, x[np.maximum(idx[:, k] - 1, 0)], np.nan)
               for k in range(4)]
        normalised, observed, calculated = table[:, 4], table[:, 5], table[:, 6]
        # the weights are in R2's data units (transfer resistance), so the relative error
        # is taken from R2's own normalised misfit: chi2 = mean(normalised^2)
        rel = np.where(observed != 0, (calculated - observed) / np.where(observed != 0,
                                                                        observed, 1.0), np.nan)
        error = np.where(normalised != 0, np.abs(rel / np.where(normalised != 0,
                                                                normalised, 1.0)), np.nan)
        readings = Readings(*pos, observed, calculated, error=error)
        check(readings)
        mesh = readings_mesh(readings, "misfit")
        return ReaderResult(mesh, "depth", {
            "reader": self.name, "source_name": path.name, "kind": "ert_misfit",
            "n_readings": int(len(table)), "rms_percent": readings.rms_percent(),
            "chi2": readings.chi2(),
        })
