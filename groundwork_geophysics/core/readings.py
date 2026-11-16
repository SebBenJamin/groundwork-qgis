"""Readings of an inversion (no QGIS): per four-electrode reading the measured and (when the
file has them) calculated apparent resistivity, and their pseudosection mesh."""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from .pseudo import median_depth, midpoint
from .section_mesh import SectionMesh

SHOWN = ("misfit", "measured", "calculated")
#: the computed RMS may differ from the file's own stated RMS by at most this factor
RMS_TOLERANCE = 2.0


@dataclass
class Readings:
    a: np.ndarray               # electrode x along the line (data metres); NaN = absent pole
    b: np.ndarray
    m: np.ndarray
    n: np.ndarray
    measured: np.ndarray        # apparent resistivity, ohm.m
    calculated: np.ndarray      # forward response of the model; NaN when unknown
    error: np.ndarray | None = None     # relative data error (0.03 = 3 %), when given
    stated_rms: float | None = None     # the file's own RMS in %, when it states one
    has_calculated: bool = True

    def misfit_percent(self) -> np.ndarray:
        meas = np.asarray(self.measured, float)
        calc = np.asarray(self.calculated, float)
        ok = np.isfinite(meas) & np.isfinite(calc) & (meas != 0)
        return np.where(ok, (calc - meas) / np.where(ok, meas, 1.0) * 100.0, np.nan)

    def rms_percent(self) -> float | None:
        mis = self.misfit_percent()
        mis = mis[np.isfinite(mis)]
        return float(np.sqrt(np.mean(mis ** 2))) if mis.size else None

    def chi2(self) -> float | None:
        if self.error is None:
            return None
        mis = self.misfit_percent() / 100.0
        err = np.asarray(self.error, float)
        ok = np.isfinite(mis) & np.isfinite(err) & (err > 0)
        return float(np.mean((mis[ok] / err[ok]) ** 2)) if ok.any() else None

    def values(self, shown: str) -> np.ndarray:
        if shown == "misfit":
            return self.misfit_percent()
        if shown == "calculated":
            return np.asarray(self.calculated, float)
        return np.asarray(self.measured, float)

    def with_x(self, fn) -> "Readings":
        return replace(self, **{k: fn(np.asarray(getattr(self, k), float)) for k in "abmn"})

    def __len__(self) -> int:
        return len(self.measured)


def check(r: Readings) -> None:
    """Fail loudly on what usually means a misread file."""
    if not len(r):
        raise ValueError("the file has no readings")
    if not np.isfinite(np.asarray(r.measured, float)).any():
        raise ValueError("no measured value could be read")
    if not r.has_calculated:
        return
    calc = np.asarray(r.calculated, float)
    if not np.isfinite(calc).any():
        raise ValueError("no calculated (model response) value could be read")
    if np.all(calc[np.isfinite(calc)] == 0):
        raise ValueError("all calculated values are zero: wrong column or response file?")
    rms = r.rms_percent()
    if r.stated_rms and rms is not None and not (
            r.stated_rms / RMS_TOLERANCE <= rms <= r.stated_rms * RMS_TOLERANCE):
        raise ValueError(f"misfit RMS {rms:.1f} % is far from the file's own "
                         f"{r.stated_rms:.1f} %: electrodes or columns misread?")


def readings_mesh(r: Readings, shown: str) -> SectionMesh:
    """Triangulated pseudosection (x = midpoint, z = -median depth) carrying the readings and
    one value per reading (``point_values``); a cell gets the mean of its corners
    (geometric for resistivities), NaN when a corner has no value."""
    x = midpoint(r.a, r.b, r.m, r.n)
    d = median_depth(r.a, r.b, r.m, r.n)
    v = r.values(shown)
    ok = np.isfinite(x) & np.isfinite(d)
    if ok.sum() < 3:
        raise ValueError("fewer than three readings with a usable electrode geometry")
    log = shown != "misfit"
    work = np.log10(np.where(v > 0, v, np.nan)) if log else np.asarray(v, float)
    work = work[ok]
    try:
        mesh = SectionMesh.from_points(x[ok], -d[ok], np.nan_to_num(work, nan=0.0),
                                       quantity="pseudo", unit="")
    except ValueError as exc:
        raise ValueError(f"cannot build a pseudosection: {exc}") from exc
    cell_vals = work[mesh.cells[:, :3]].mean(axis=1)
    if log:
        cell_vals = np.power(10.0, cell_vals)
    kept = Readings(*(np.asarray(getattr(r, k), float)[ok] for k in
                      ("a", "b", "m", "n", "measured", "calculated")),
                    error=None if r.error is None else np.asarray(r.error, float)[ok],
                    stated_rms=r.stated_rms, has_calculated=r.has_calculated)
    misfit = shown == "misfit"
    return replace(mesh, values=cell_vals, quantity="misfit" if misfit else "resistivity",
                   unit="%" if misfit else "ohm.m", readings=kept, point_values=v[ok])
