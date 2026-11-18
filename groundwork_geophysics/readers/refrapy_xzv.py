"""Refrapy (Refrainv) velocity model reader: ``<line>_xzv.txt`` (no QGIS/Qt).

Refrainv's "Save results" writes the pyGIMLi model's cell centres with the header line
``x z velocity converage standardized coverage sc_v`` (Refrapy's own spelling; 7 words for
6 columns): x (metres along the line), z (elevation), P-wave velocity (m/s), ray coverage
(log, ``-inf`` where no ray passed), standardized coverage (1 = resolved, 0 = not) and
velocity x standardized coverage. The cells come as centres only, so they are
triangulated. The lowest coverage Refrainv counts as resolved becomes the default fade
threshold. ``<line>_topography.txt`` next to it (``x z``) lists the shot and geophone
points: their x are kept as ``station_x``.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from .base import Reader, ReaderResult, chosen_z_kind, mesh_from_points

HEADER = "x z velocity converage standardized coverage sc_v"
NO_TOPOGRAPHY = "no _topography.txt next to the file: station positions unknown"


def _topography_x(path: Path) -> list[float] | None:
    """Sorted x of ``<line>_topography.txt`` beside ``<line>_xzv.txt``; None when missing
    or unreadable."""
    stem = path.name[:-len("_xzv.txt")] if path.name.endswith("_xzv.txt") else path.stem
    topo = path.with_name(f"{stem}_topography.txt")
    try:
        a = np.loadtxt(topo, skiprows=1, ndmin=2)
    except (OSError, ValueError):
        return None
    if a.shape[0] < 2 or a.shape[1] < 2:
        return None
    return sorted(float(v) for v in a[:, 0])


class RefrapyXzvReader(Reader):
    name = "refrapy_xzv"
    label = "Refrapy velocity model (_xzv.txt)"

    def sniff(self, path: Path) -> bool:
        try:
            with open(path, "rb") as f:
                first = f.readline(200).decode("latin-1")
        except OSError:
            return False
        return " ".join(first.split()) == HEADER

    def read(self, path: Path, **options) -> ReaderResult:
        path = Path(path)
        try:
            a = np.loadtxt(path, skiprows=1, ndmin=2)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{path.name}: not a Refrapy model table ({exc})") from None
        if a.shape[1] < 6 or a.shape[0] < 3:
            raise ValueError(f"{path.name}: expected 6 columns (x z velocity coverage "
                             f"standardized coverage sc_v) in at least 3 rows, found "
                             f"{a.shape[1]} columns in {a.shape[0]} rows")
        x, z, v, cov, resolved = (a[:, k] for k in range(5))
        good = (resolved > 0.5) & np.isfinite(cov)
        cut = float(cov[good].min()) if good.any() else None
        z_kind = chosen_z_kind(options, "elevation")
        mesh, n_masked, kind = mesh_from_points(x, z, v, path.name, z_kind,
                                                quantity="p_velocity", unit="m/s",
                                                coverage=cov, coverage_cut=cut)
        provenance = {
            "reader": self.name,
            "source_name": path.name,
            "kind": "srt_model",
            "method": "srt",
            "n_cells": int(a.shape[0]),
            "n_unresolved": int((resolved <= 0.5).sum()),
            "n_masked": n_masked,
            "coverage_cut": cut,
            "reconstruction": kind,
        }
        station_x = _topography_x(path)
        if station_x is None:
            provenance["warning"] = NO_TOPOGRAPHY
        else:
            provenance["station_x"] = station_x
        return ReaderResult(mesh, z_kind, provenance)
