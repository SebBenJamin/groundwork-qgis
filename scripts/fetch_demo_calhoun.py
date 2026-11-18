"""One-off, online: fetch the open data for the Calhoun refraction demo.

Run: python-qgis.bat scripts/fetch_demo_calhoun.py

Writes the raw downloads to .cache/calhoun/ (git-ignored):
  allBR.txt                     points every 10 m along the lines (UTM 17N) with depth to
                                bedrock, and for each demo line L6, L10, L11, L12 its first-
                                arrival picks, its elevation file and the authors' inversion
                                script, from HydroShare resource 340773feb3b341d884f6742b55966609
                                "Supporting Data Repository: Landscape Curvature and Deep
                                Critical Zone Structure" (Flinchum et al.), CC BY 4.0
  dem_3dep.tif                  USGS 3DEP 1 m elevation of the lines + 150 m, EPSG:32617
                                (public domain), from the 3DEP elevation image service
"""
from __future__ import annotations

import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np

import calhoun_data

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "calhoun"
RESOURCE = "340773feb3b341d884f6742b55966609"
BASE = (f"https://www.hydroshare.org/resource/{RESOURCE}/data/contents/Seismic%20Data/")
PIECES = BASE + "ExtrapolationCodes/allBR.txt"
LINE_URL = BASE + "Picks%20and%20Inversions/{line}/{name}"
SCRIPTS = {"L12": "StreamLineInversion_Pwave_bootstrap.py"}
SCRIPT = "StreamLineInversion_Pwave_bootstrap_mulitThread.py"
DEM_URL = ("https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/"
           "exportImage")
CRS_EPSG = 32617
MARGIN = 150.0
USER_AGENT = "groundwork-qgis-demo-builder/0.3 (QGIS plugin demo data; one-off fetch)"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


def _fetch(url: str, target: Path) -> None:
    if target.exists() and target.stat().st_size > 0:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(_get(url))


def demo_bbox(cache: Path = CACHE) -> tuple[float, float, float, float]:
    """Bounding box of the demo lines' pieces + MARGIN, whole metres (UTM 17N)."""
    pieces = calhoun_data.read_pieces(cache / "allBR.txt")
    xy = np.vstack([pieces[piece][:, :2] for piece, _p, _e in calhoun_data.LINES.values()])
    (x0, y0), (x1, y1) = np.floor(xy.min(axis=0) - MARGIN), np.ceil(xy.max(axis=0) + MARGIN)
    return float(x0), float(y0), float(x1), float(y1)


def fetch_dem(cache: Path = CACHE) -> Path:
    target = cache / "dem_3dep.tif"
    if target.exists() and target.stat().st_size > 0:
        return target
    x0, y0, x1, y1 = demo_bbox(cache)
    query = urllib.parse.urlencode({
        "bbox": f"{x0},{y0},{x1},{y1}", "bboxSR": CRS_EPSG, "imageSR": CRS_EPSG,
        "size": f"{int(x1 - x0)},{int(y1 - y0)}", "format": "tiff", "pixelType": "F32",
        "interpolation": "RSP_BilinearInterpolation", "f": "image"})
    data = _get(f"{DEM_URL}?{query}")
    if data[:2] not in (b"II", b"MM"):
        raise RuntimeError(f"3DEP did not return a GeoTIFF: {data[:200]!r}")
    target.write_bytes(data)
    return target


def main() -> int:
    _fetch(PIECES, CACHE / "allBR.txt")
    for line, (_piece, picks, elev) in calhoun_data.LINES.items():
        for name in (picks, elev, SCRIPTS.get(line, SCRIPT)):
            _fetch(LINE_URL.format(line=line, name=name), CACHE / line / name)
    dem = fetch_dem()
    print(f"{CACHE}: allBR.txt, {len(calhoun_data.LINES)} lines, {dem.name} "
          f"(bbox {demo_bbox()})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
