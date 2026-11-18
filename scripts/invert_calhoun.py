"""Invert the Calhoun demo lines once, offline, exactly as Refrapy's Refrainv does, and save
the results in Refrainv's own file layout (``<line>_xzv.txt``, ``<line>_topography.txt``).

Runs in a separate conda env with Refrapy's pyGIMLi, never inside QGIS:

    conda create -n refrapy -c gimli -c conda-forge python=3.8 pygimli=1.2.6 obspy
    (Windows: put the env folder and its Library\\bin on PATH before running its python)
    python scripts/invert_calhoun.py [L10 L11 L12 L6]

Input: the authors' expert first-arrival picks and elevation files, fetched to
.cache/calhoun/ by scripts/fetch_demo_calhoun.py (CC BY 4.0, Flinchum et al., HydroShare
resource 340773feb3b341d884f6742b55966609). Settings: those of the Refrainv run made for
line 1 (dx 1.5 m, quality 32, lambda 100, z weight 0.1, start model 400 -> 4500 m/s,
limits 100 - 7000 m/s, 3 secondary nodes, 15 iterations), with a lighter mesh and every
2nd geophone (see MESH below).
Outputs go to scripts/data/calhoun/ (committed: the demo build reads them, so it needs no
pyGIMLi); the Refrapick pick file goes to .cache/calhoun/<line>/<line>.sgt.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import calhoun_data  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
CACHE = REPO / ".cache" / "calhoun"
OUT = REPO / "scripts" / "data" / "calhoun"
#: Refrainv's line-1 settings, made lighter for these 720 m lines with 1 m geophone spacing
#: (18,000 picks): every 2nd geophone, 60 m deep (the rays reach about 40 m), cells up to
#: 20 m². The full settings need a 3.5 GB dense Jacobian, more than a laptop holds.
MESH = dict(paraDepth=60.0, paraDX=1.5, paraMaxCellSize=20.0, quality=32.0)
GEOPHONE_STEP = 2       # nominal metres
MAX_JACOBIAN_GB = 1.0   # refuse to invert above this (picks x cells x 8 bytes)
INVERT = dict(lam=100.0, zWeight=0.1, useGradient=True, vTop=400.0, vBottom=4500.0,
              maxIter=15, limits=[100.0, 7000.0], secNodes=3)
XZV_HEADER = "x z velocity converage standardized coverage sc_v"


def invert_line(name: str) -> dict:
    import pygimli as pg
    from pygimli.physics import TravelTimeManager

    line = calhoun_data.thinned(calhoun_data.read_line(*calhoun_data.line_files(CACHE, name)),
                                GEOPHONE_STEP)
    sgt = CACHE / name / f"{name}.sgt"
    n_picks = calhoun_data.write_sgt(sgt, line)
    data = pg.DataContainer(str(sgt), "s g")          # as Refrainv loads a pick file
    mgr = TravelTimeManager()
    start = time.time()
    mesh = mgr.createMesh(data=data, **MESH)
    jacobian_gb = n_picks * mesh.cellCount() * 8 / 1e9
    if jacobian_gb > MAX_JACOBIAN_GB:
        raise SystemExit(f"{name}: {n_picks} picks x {mesh.cellCount()} cells need a "
                         f"{jacobian_gb:.1f} GB Jacobian (limit {MAX_JACOBIAN_GB} GB)")
    mgr.invert(data=data, mesh=mesh, verbose=True, **INVERT)
    minutes = (time.time() - start) / 60.0

    # Refrainv's saveResults: cell centres, velocity, coverage, standardized coverage, and
    # velocity x standardized coverage (0 where no ray passed)
    centres = np.array(mgr.paraDomain.cellCenters())
    v = np.asarray(mgr.model)
    cov = np.asarray(mgr.coverage())
    scov = np.asarray(mgr.standardizedCoverage())
    sc_v = scov * v
    sc_v[np.isneginf(cov)] = 0.0
    OUT.mkdir(parents=True, exist_ok=True)
    np.savetxt(OUT / f"{name}_xzv.txt", np.c_[centres[:, 0], centres[:, 1], v, cov, scov, sc_v],
               fmt="%.2f", header=XZV_HEADER, comments="")
    xs, zs, _index = calhoun_data.sensor_points(line)
    np.savetxt(OUT / f"{name}_topography.txt", np.c_[xs, zs],
               fmt="%.2f", header="x z", comments="")
    info = {"line": name, "n_picks": int(n_picks), "n_cells": int(len(v)),
            "chi2": float(mgr.inv.chi2()), "relrms_percent": float(mgr.inv.relrms()),
            "absrms_ms": float(mgr.inv.absrms()) * 1000.0, "minutes": round(minutes, 1),
            "pygimli": pg.__version__, "mesh": MESH, "invert": INVERT,
            "geophone_step_m": GEOPHONE_STEP}
    (OUT / f"{name}_pygimli.json").write_text(json.dumps(info, indent=1) + "\n")
    return info


def main(names: list[str]) -> int:
    for name in names:
        info = invert_line(name)
        print(f"{name}: chi2 {info['chi2']:.2f}, rel. RMS {info['relrms_percent']:.1f} %, "
              f"{info['n_cells']} cells, {info['minutes']} min", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or list(calhoun_data.LINES)))
