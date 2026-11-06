"""Synthetic log curves for the Gülpe demo: NOT measured data.

The Köhler et al. (2025) cores have lithology logs but no geophysical logs. To show the
borehole viewer's curve tracks, the demo gets a clearly labelled synthetic table: one sample
every 0.1 m down each core, with a seeded random level per logged interval plus a little
noise. Nothing is derived from the lithology words. The table name, its description, its
field names and the units in the demo settings all say "synthetic".

Run (rewrites demo_guelpe/context/synthetic_logs.gpkg from context/cores.gpkg):
    python-qgis.bat scripts/make_synthetic_curves.py
"""
from __future__ import annotations

import sys
import zlib
from pathlib import Path

import numpy as np

LAYER = "synthetic_curves_NOT_MEASURED"
DESCRIPTION = ("Synthetic log curves for demonstration only - NOT measured. Seeded random "
               "levels per logged interval (scripts/make_synthetic_curves.py).")
STEP = 0.1
ROOT = Path(__file__).resolve().parent.parent


def _samples(core_id: str, intervals) -> list[tuple[float, float, float]]:
    """(depth, gamma, conductivity) every ``STEP`` m from the top to the deepest bottom;
    a shared interval boundary is sampled once (by the upper interval)."""
    rng = np.random.default_rng(zlib.crc32(core_id.encode("utf-8")))
    out: dict[float, tuple[float, float]] = {}
    for top, bottom, _text in sorted(intervals):
        gamma, cond = rng.uniform(20.0, 120.0), rng.uniform(5.0, 60.0)
        for d in np.arange(top, bottom + 1e-9, STEP):
            d = round(float(d), 3)
            if d not in out:
                out[d] = (round(gamma + rng.normal(0, 4.0), 2), round(cond + rng.normal(0, 2.0), 2))
    return [(d, g, c) for d, (g, c) in sorted(out.items())]


def write(path: Path, logs: dict) -> None:
    """``logs``: core id -> [(top, bottom, text)]. Writes ``LAYER`` (no geometry)."""
    from osgeo import gdal, ogr

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with gdal.ExceptionMgr(), ogr.ExceptionMgr(), \
            gdal.config_option("OGR_CURRENT_DATE", "2026-11-06T00:00:00.000Z"):
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
        table = ds.CreateLayer(LAYER, None, ogr.wkbNone,
                               options=[f"DESCRIPTION={DESCRIPTION}"])
        for name, kind in (("core_id", ogr.OFTString), ("depth", ogr.OFTReal),
                           ("gamma_synthetic", ogr.OFTReal), ("cond_synthetic", ogr.OFTReal)):
            table.CreateField(ogr.FieldDefn(name, kind))
        for cid in sorted(logs):
            for depth, gamma, cond in _samples(cid, logs[cid]):
                f = ogr.Feature(table.GetLayerDefn())
                f.SetField("core_id", cid)
                f.SetField("depth", depth)
                f.SetField("gamma_synthetic", gamma)
                f.SetField("cond_synthetic", cond)
                table.CreateFeature(f)
        ds = None


def read_logs(cores_gpkg: Path) -> dict:
    from osgeo import ogr
    with ogr.ExceptionMgr():
        ds = ogr.Open(str(cores_gpkg))
        out: dict = {}
        for f in ds.GetLayerByName("core_logs"):
            out.setdefault(f["core_id"], []).append((f["top"], f["bottom"], f["lithology"]))
    return out


def main() -> int:
    ctx = ROOT / "demo_guelpe" / "context"
    write(ctx / "synthetic_logs.gpkg", read_logs(ctx / "cores.gpkg"))
    print(f"wrote {ctx / 'synthetic_logs.gpkg'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
