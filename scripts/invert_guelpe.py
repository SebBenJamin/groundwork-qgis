"""Invert Gülpe transect 3 once, offline, to get real misfit files for the M4b readers and
the demo: pyGIMLi (BERT format response) and R2 via ResIPy (f001_err.dat).

Runs in the separate conda env ``wb-inversion`` (pyGIMLi 1.5, ResIPy), never inside QGIS:

    conda create -n wb-inversion -c gimli -c conda-forge "pygimli>=1.5" python=3.11
    conda run -n wb-inversion pip install resipy
    conda run -n wb-inversion python scripts/invert_guelpe.py [pygimli|r2|both]

Input: the authors' measured data, ``processing/240603_Guelpe_ERT_Transect3_topo.data`` in
PANGAEA's ``ERT_Transect3_V2.zip`` (CC BY 4.0, Pohle et al. 2025), fetched to .cache/guelpe by
scripts/fetch_demo_guelpe.py. The authors' BERT settings (Guelpe_ERT_Transect3.cfg) are
followed where pyGIMLi has them: lambda 100, robust data, paraDX 0.25, quality 34.
Outputs go to .cache/guelpe/inversion/ (copied into the demo/tests by the caller).
"""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
ZIP = REPO / ".cache" / "guelpe" / "ert" / "ERT_Transect3_V2.zip"
MEMBER = "processing/240603_Guelpe_ERT_Transect3_topo.data"
OUT = REPO / ".cache" / "guelpe" / "inversion"


def data_file() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "T3_topo.data"
    if not path.exists():
        with zipfile.ZipFile(ZIP) as zf:
            path.write_bytes(zf.read(MEMBER))
    return path


def run_pygimli() -> None:
    import pygimli as pg
    from pygimli.physics import ert

    data = ert.load(str(data_file()))
    if not data.haveData("err") or np.all(np.asarray(data["err"]) <= 0):
        data["err"] = ert.estimateError(data, relativeError=0.03, absoluteUError=50e-6)
    mgr = ert.ERTManager(data, verbose=True)
    mgr.invert(lam=100, robustData=True, paraDX=0.25, quality=34, verbose=True)
    resp = np.asarray(mgr.inv.response)
    np.savetxt(OUT / "T3_response.vector", resp, fmt="%.6e")
    info = {"chi2": float(mgr.inv.chi2()), "rms_percent": float(mgr.inv.relrms()),
            "n": int(len(resp)), "pygimli": pg.__version__, "lam": 100, "robustData": True}
    (OUT / "T3_pygimli.json").write_text(json.dumps(info, indent=1))
    mgr.saveResult(str(OUT / "pygimli_result"))
    print("pygimli done:", info)


def run_r2() -> None:
    import resipy.Survey
    from resipy import Project

    # ResIPy's compiled reciprocal search fails with recent numpy ("buffer source array is
    # read-only"); its pure-pandas fallback gives the same pairs
    sys.modules["resipy.Survey"].recipCalc_installed = False    # the module, not the class
    work = OUT / "r2_work"
    if work.exists():
        shutil.rmtree(work)
    k = Project(dirname=str(work), typ="R2")
    k.createSurvey(str(data_file()), ftype="BERT")
    k.createMesh("trian")
    k.invert()
    inv = work / "invdir"
    for name in ("f001_err.dat", "R2.in", "protocol.dat", "f001_res.vtk", "R2.out"):
        if (inv / name).exists():
            shutil.copy(inv / name, OUT / f"r2_{name}")
    elec = k.elec[["x", "y", "z"]].to_numpy()
    np.savetxt(OUT / "r2_electrodes.csv", elec, delimiter=",", header="x,y,z", comments="")
    print("r2 done:", sorted(p.name for p in OUT.glob("r2_*")))


def subset_file(n_electrodes: int = 80) -> Path:
    """The first ``n_electrodes`` of transect 3 and the readings that use only them: a small
    real dataset that R2 inverts in minutes (for a test fixture of its f001_err.dat)."""
    lines = data_file().read_text().splitlines()
    n_el = int(lines[0].split()[0])
    el_rows = lines[2:2 + n_el]
    n_d = int(lines[2 + n_el].split()[0])
    head = lines[3 + n_el]
    rows = [r for r in lines[4 + n_el:4 + n_el + n_d]
            if all(0 < int(float(v)) <= n_electrodes for v in r.split()[:4])]
    out = OUT / "T3_first80.data"
    out.write_text("\n".join([str(n_electrodes), lines[1], *el_rows[:n_electrodes],
                              str(len(rows)), head, *rows, "0"]) + "\n")
    return out


def run_r2_small() -> None:
    from resipy import Project

    sys.modules["resipy.Survey"].recipCalc_installed = False    # see run_r2
    work = OUT / "r2s_work"
    if work.exists():
        shutil.rmtree(work)
    k = Project(dirname=str(work), typ="R2")
    k.createSurvey(str(subset_file()), ftype="BERT")
    k.createMesh("quad")
    k.invert()
    inv = work / "invdir"
    for name in ("f001_err.dat", "electrodes.dat", "R2.out", "protocol.dat"):
        if (inv / name).exists():
            shutil.copy(inv / name, OUT / f"r2s_{name}")
    print("r2 small done:", sorted(p.name for p in OUT.glob("r2s_*")))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "both"
    if which in ("pygimli", "both"):
        run_pygimli()
    if which in ("r2", "both"):
        run_r2()
    if which == "r2small":
        run_r2_small()
