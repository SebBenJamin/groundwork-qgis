"""One-off, online: fetch the open data for the Gülpe real-data demo.

Run: python-qgis.bat scripts/fetch_demo_guelpe.py

Writes the raw downloads to .cache/guelpe/ (git-ignored):
  ert/ERT_Transect{1,2,3_V2,4}.zip  2D-ERT, Pohle, Birnstengel, Werban (2025), PANGAEA,
                                    doi:10.1594/PANGAEA.983478, CC BY 4.0. PANGAEA restores
                                    these from tape: the first answers are an HTML "please
                                    wait" page, so each file is retried until it is a zip.
  cores.tab                         sediment cores, Köhler, Kaniecki, Schneider, Zielhofer (2025),
                                    PANGAEA, doi:10.1594/PANGAEA.983887, CC BY 4.0
  dgm/dgm_33<E>-<N>.zip             DGM1 1 km tiles, © GeoBasis-DE/LGB, dl-de/by-2-0
  state_boreholes.gpkg              the LBGR Bohrpunktkarte (WFS) around the transects, layers
                                    with_log and without_log, © LBGR, dl-de/by-2-0: a copy, as
                                    the live state-wide layer makes a QGIS 3D view download
                                    half of Brandenburg
and, derived, demo_guelpe/context/waterways.geojson (EPSG:25833) from OpenStreetMap
(© OpenStreetMap contributors, ODbL).
"""
from __future__ import annotations

import json
import math
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "guelpe"
WATERWAYS = ROOT / "demo_guelpe" / "context" / "waterways.geojson"
ERT_URL = "https://download.pangaea.de/dataset/983478/files/"
ERT_FILES = {1: "ERT_Transect1.zip", 2: "ERT_Transect2.zip", 3: "ERT_Transect3_V2.zip",
             4: "ERT_Transect4.zip"}
CORES_URL = "https://doi.pangaea.de/10.1594/PANGAEA.983887?format=textfile"
DGM_URL = "https://data.geobasis-bb.de/geobasis/daten/dgm/tif/"
TRANSECTS_BBOX = (311673.0, 5845638.0, 312216.0, 5846564.0)     # EPSG:25833
WATERWAYS_BBOX = (12.200, 52.722, 12.230, 52.742)                # lon/lat: west, south, east, north
ENDPOINT = "https://overpass-api.de/api/interpreter"
USER_AGENT = "groundwork-qgis-demo-builder/0.2 (QGIS plugin demo data; one-off fetch)"
RETRIES, WAIT = 15, 30.0
BPK_WFS = "https://inspire.brandenburg.de/services/bpk_wfs"
#: the state boreholes: WFS type name -> layer in state_boreholes.gpkg
BPK_LAYERS = {"app:bpk_m_sch": "with_log", "app:bpk_o_sch": "without_log"}
#: m around the transects (as the geology the demo's legend lists)
BOREHOLE_MARGIN = 1500.0


def dgm_tiles(bbox, margin: float = 100.0) -> list[str]:
    """Names of the 1 km DGM1 tiles (south-west corner in km) covering ``bbox`` ± ``margin``."""
    x0, y0, x1, y1 = bbox
    xs = range(math.floor((x0 - margin) / 1000), math.floor((x1 + margin) / 1000) + 1)
    ys = range(math.floor((y0 - margin) / 1000), math.floor((y1 + margin) / 1000) + 1)
    return sorted(f"dgm_33{x}-{y}" for x in xs for y in ys)


def is_zip(data: bytes) -> bool:
    return data[:2] == b"PK"


def waterways_query(bbox_lonlat) -> str:
    w, s, e, n = bbox_lonlat
    return (f'[out:json][timeout:60];way["waterway"~"^(river|canal|stream|ditch|drain)$"]'
            f'({s},{w},{n},{e});out geom;')


def _get(url: str, data: bytes | None = None) -> bytes:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _fetch_zip(url: str, target: Path) -> None:
    if target.exists() and is_zip(target.read_bytes()[:2]):
        return
    for _ in range(RETRIES):
        data = _get(url)
        if is_zip(data):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return
        time.sleep(WAIT)                       # PANGAEA is restoring the file from tape
    raise RuntimeError(f"{url}: no zip after {RETRIES} tries")


def fetch_waterways(out: Path = WATERWAYS) -> int:
    from pyproj import Transformer

    q = waterways_query(WATERWAYS_BBOX)
    elements = json.loads(_get(ENDPOINT, urllib.parse.urlencode({"data": q}).encode()))
    tr = Transformer.from_crs(4326, 25833, always_xy=True)
    features = []
    for el in sorted(elements["elements"], key=lambda e: e["id"]):
        coords = [[round(c, 2) for c in tr.transform(p["lon"], p["lat"])] for p in el["geometry"]]
        tags = el.get("tags", {})
        features.append({"type": "Feature",
                         "properties": {"osm_id": el["id"], "name": tags.get("name", ""),
                                        "waterway": tags.get("waterway", "")},
                         "geometry": {"type": "LineString", "coordinates": coords}})
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"type": "FeatureCollection", "name": "waterways",
                               "crs": {"type": "name",
                                       "properties": {"name": "urn:ogc:def:crs:EPSG::25833"}},
                               "features": features}, indent=1) + "\n", encoding="utf-8")
    return len(features)


def fetch_state_boreholes(out: Path = CACHE / "state_boreholes.gpkg",
                          margin: float = BOREHOLE_MARGIN) -> dict:
    """The LBGR state boreholes (with and without a layer log) within ``margin`` of the
    transects, as layers of one GeoPackage (EPSG:25833); only that area is asked of the WFS.
    Returns the feature count per layer."""
    from osgeo import gdal, ogr
    gdal.UseExceptions()
    x0, y0, x1, y1 = TRANSECTS_BBOX
    box = (x0 - margin, y0 - margin, x1 + margin, y1 + margin)
    out.unlink(missing_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    counts = {}
    for i, (typename, layer) in enumerate(BPK_LAYERS.items()):
        gdal.VectorTranslate(str(out), f"WFS:{BPK_WFS}", format="GPKG",
                             accessMode=None if i == 0 else "update",
                             layers=[typename], layerName=layer, spatFilter=box,
                             spatSRS="EPSG:25833", dstSRS="EPSG:25833")
        ds = ogr.Open(str(out))
        counts[layer] = ds.GetLayerByName(layer).GetFeatureCount()
        ds = None
    return counts


def main() -> int:
    for name in ERT_FILES.values():
        _fetch_zip(ERT_URL + name, CACHE / "ert" / name)
        print("ert", name)
    cores = CACHE / "cores.tab"
    if not cores.exists():
        cores.write_bytes(_get(CORES_URL))
    for tile in dgm_tiles(TRANSECTS_BBOX):
        _fetch_zip(f"{DGM_URL}{tile}.zip", CACHE / "dgm" / f"{tile}.zip")
        print("dgm", tile)
    print("waterways", fetch_waterways())
    print("state boreholes", fetch_state_boreholes())
    return 0


if __name__ == "__main__":
    sys.exit(main())
