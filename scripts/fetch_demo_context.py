"""One-off, online: fetch a real high-voltage powerline from OpenStreetMap (Overpass)
and write it as EPSG:25832 GeoJSON to demo/context/powerline.geojson.

Run: python-qgis.bat scripts/fetch_demo_context.py
Data (c) OpenStreetMap contributors, ODbL (see demo/context/ATTRIBUTION.md).
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from pyproj import Transformer

# Candidate bboxes (south, west, north, east) in lon/lat: rural farmland in the north German
# plain / Lower Saxony, inside UTM zone 32N (6-12 E). The first one with a line is used.
BBOXES = [
    (52.790, 8.060, 52.817, 8.104),   # Vechta / Cloppenburg farmland
    (52.560, 9.050, 52.587, 9.094),   # Nienburg area
    (52.250, 7.550, 52.277, 7.594),   # Emsland / Muensterland
    (51.900, 9.300, 51.927, 9.344),   # Weser uplands foreland
]
VOLTAGE_RE = "^(110000|220000|380000)"
ENDPOINT = "https://overpass-api.de/api/interpreter"
USER_AGENT = "groundwork-qgis-demo-builder/0.1 (QGIS plugin demo data; one-off fetch)"
OUT = Path(__file__).resolve().parent.parent / "demo" / "context" / "powerline.geojson"


def query(bbox) -> list[dict]:
    s, w, n, e = bbox
    q = (f'[out:json][timeout:60];way["power"="line"]["voltage"~"{VOLTAGE_RE}"]'
         f'({s},{w},{n},{e});out geom;')
    req = urllib.request.Request(ENDPOINT, data=urllib.parse.urlencode({"data": q}).encode(),
                                 headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))["elements"]


def main() -> int:
    tr = Transformer.from_crs("EPSG:4326", "EPSG:25832", always_xy=True)
    for bbox in BBOXES:
        try:
            ways = [w for w in query(bbox) if len(w.get("geometry", [])) >= 2]
        except Exception as exc:
            print(f"Overpass request failed for {bbox}: {exc}", file=sys.stderr)
            return 2
        if ways:
            break
        print(f"no line in {bbox}, trying next")
    else:
        print("no powerline found in any candidate bbox", file=sys.stderr)
        return 3

    def length(w):
        pts = [tr.transform(p["lon"], p["lat"]) for p in w["geometry"]]
        return sum(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a, b in zip(pts, pts[1:]))

    ways.sort(key=length, reverse=True)
    best = ways[0]
    feats, allpts = [], []
    w = best
    coords = [[round(x, 2), round(y, 2)] for x, y in
              (tr.transform(p["lon"], p["lat"]) for p in w["geometry"])]
    allpts += coords
    tags = w.get("tags", {})
    props = {"osm_id": w["id"], "voltage": tags.get("voltage")}
    for k in ("name", "operator"):
        if k in tags:
            props[k] = tags[k]
    feats.append({"type": "Feature", "properties": props,
                  "geometry": {"type": "LineString", "coordinates": coords}})
    gj = {"type": "FeatureCollection",
          "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::25832"}},
          "features": feats}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(gj, indent=1) + "\n", encoding="utf-8", newline="\n")
    xs, ys = [p[0] for p in allpts], [p[1] for p in allpts]
    print("bbox (lat/lon S,W,N,E):", bbox)
    print("osm way:", best["id"], best.get("tags", {}).get("voltage"), f"length {length(best):.0f} m")
    print(f"centroid EPSG:25832: {sum(xs)/len(xs):.1f}, {sum(ys)/len(ys):.1f}")
    print(f"extent: x {min(xs):.1f}..{max(xs):.1f}  y {min(ys):.1f}..{max(ys):.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())