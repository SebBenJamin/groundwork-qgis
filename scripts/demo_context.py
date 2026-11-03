"""Synthetic third-party context for the demo (called by scripts/build_demo.py).

- ``Body`` / ``make_bodies`` / ``blend``: the clay bodies and the earthing artefact, defined in
  EPSG:25832 map coordinates (centre x, y, depth; horizontal semi-axes; half-thickness), so
  crossing profiles see the same body. Body A sits on the P1 x P3 tie, Body B on P2 where its
  0.1 lens was, the earthing artefact under the pylon nearest P1 (if within 20 m) or else at
  the P1 x powerline crossing.
- ``write_context`` writes, under demo/context/:
    pylons.geojson    the powerline's vertices inside the demo area (in OSM those are the towers)
    boreholes.gpkg    layer ``boreholes`` (id, name, elevation) + table ``borehole_logs``
                      (borehole_id, top, bottom, lithology), logs from the model's own layering
    geology.geojson   four synthetic surface units (field ``unit``)
    dem.tif           2 m terrain, cell-centre registered, plus a road embankment on P2 that
                      the GPS station heights do not include

Terrain, bedrock and profiles come from build_demo as arguments (build_demo imports this
module). Needs GDAL/OGR with GEOS (QGIS's Python). Text outputs are byte-identical on
re-runs; dem.tif pixels are identical.
"""
from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from geophysics_workbench.core.context import (line_crossings, profile_ties,  # noqa: E402
                                               project_points)

EPSG = 25832
CRS_URN = f"urn:ogc:def:crs:EPSG::{EPSG}"
MARGIN = 100.0              # DEM and pylon area: the profiles' bbox plus this (m)
PIXEL = 2.0                 # DEM pixel size (m)
BODY_B_S = 71.0             # P2 chainage of the 0.1 demo's lens, now Body B
PYLON_RADIUS = 20.0         # the earthing artefact goes under a pylon this close to P1
LOG_DEPTH = 25.0
#: borehole id -> (profile, chainage or None = the P1 x P3 tie, signed offset, + = left)
BOREHOLES = {"B1": ("P1", None, 0.0), "B2": ("P2", 200.0, 12.0), "B3": ("P1", 180.0, -8.0),
             "B4": ("P3", 265.0, 30.0)}
#: road embankment on P2: centre chainage, height, crest half-width, foot half-width, and its
#: direction relative to P2 (degrees, 90 = square across); it passes 8+ m beyond P1's end
ROAD = {"s": 252.5, "height": 2.0, "crest": 4.0, "foot": 6.0, "angle": 80.0}
GPKG_DATE = "2026-10-30T00:00:00.000Z"      # fixed gpkg_contents timestamps


# ---------------------------------------------------------------- bodies
@dataclass(frozen=True)
class Body:
    name: str
    x: float
    y: float
    depth: float            # centre depth below the surface (m)
    a: float                # horizontal semi-axis along x (m)
    b: float                # horizontal semi-axis along y (m)
    half_thickness: float
    rho: float              # ohm.m
    clay: bool = True       # False: not geology (earthing artefact), never in a borehole log

    def weight(self, x, y, depth, edge):
        """1 inside the ellipsoid, 0 outside, a tanh transition ``edge`` m wide."""
        r = np.sqrt(((np.asarray(x, float) - self.x) / self.a) ** 2
                    + ((np.asarray(y, float) - self.y) / self.b) ** 2
                    + ((np.asarray(depth, float) - self.depth) / self.half_thickness) ** 2)
        return 0.5 * (1 - np.tanh((r - 1.0) * min(self.a, self.b, self.half_thickness) / edge))

    def interval(self, x: float, y: float):
        """(top, bottom) depth of the body below (x, y), or None where it is not."""
        h = 1.0 - ((x - self.x) / self.a) ** 2 - ((y - self.y) / self.b) ** 2
        if h <= 0:
            return None
        dz = self.half_thickness * math.sqrt(h)
        return max(self.depth - dz, 0.0), self.depth + dz


def blend(lg, x, y, depth, bodies, edge):
    """log10 resistivity ``lg`` with each body blended in (later bodies on top)."""
    for body in bodies:
        w = body.weight(x, y, depth, edge)
        lg = (1 - w) * lg + w * math.log10(body.rho)
    return lg


def _line(p) -> np.ndarray:
    return np.column_stack(p.xy(np.array([0.0, p.length])))


def artefact_site(p1, powerline_xy, pylons):
    """(x, y, description): under the pylon nearest P1 if within 20 m, else the crossing."""
    if pylons:
        hits = project_points(_line(p1), np.array([(x, y) for _n, x, y in pylons]), PYLON_RADIUS)
        if hits:
            i, s, off = min(hits, key=lambda h: abs(h[2]))
            name, x, y = pylons[i]
            return x, y, f"under {name} ({abs(off):.1f} m off P1, s = {s:.1f} m)"
    [crossing] = line_crossings(_line(p1), powerline_xy, "", "line")
    x, y = p1.xy(crossing.s)
    return float(x), float(y), (f"no pylon within {PYLON_RADIUS:.0f} m of P1: at the P1 x "
                                f"powerline crossing, s = {crossing.s:.1f} m")


def make_bodies(profiles: dict, powerline_xy, pylons):
    """[Body A, Body B, earthing artefact] and a description of where the artefact went."""
    p1, p2, p3 = profiles["P1"], profiles["P2"], profiles["P3"]
    [(s1, _s3, _dist)] = profile_ties(_line(p1), _line(p3), 0.0)
    ax, ay = (float(v) for v in p1.xy(s1))
    bx, by = (float(v) for v in p2.xy(BODY_B_S))
    ex, ey, where = artefact_site(p1, powerline_xy, pylons)
    return [Body("A", ax, ay, 5.0, 25.0, 25.0, 3.0, 8.0),
            Body("B", bx, by, 5.0, 20.0, 20.0, 3.0, 6.5),
            Body("earthing", ex, ey, 1.5, 4.0, 4.0, 1.5, 5.0, clay=False)], where


# ---------------------------------------------------------------- area and pylons
def load_line(path: Path) -> np.ndarray:
    gj = json.loads(Path(path).read_text(encoding="utf-8"))
    return np.array([c[:2] for f in gj["features"] for c in f["geometry"]["coordinates"]], float)


def demo_extent(profiles) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1): the profiles' bbox plus 100 m, snapped outwards to the 2 m grid."""
    xy = np.vstack([_line(p) for p in profiles])
    (x0, y0), (x1, y1) = xy.min(axis=0) - MARGIN, xy.max(axis=0) + MARGIN
    snap = PIXEL
    return (math.floor(x0 / snap) * snap, math.floor(y0 / snap) * snap,
            math.ceil(x1 / snap) * snap, math.ceil(y1 / snap) * snap)


def pylons(powerline_xy, extent):
    """[(name, x, y)]: powerline vertices inside ``extent``, "Mast 1..n" along the line."""
    x0, y0, x1, y1 = extent
    inside = [(float(x), float(y)) for x, y in powerline_xy if x0 <= x <= x1 and y0 <= y <= y1]
    return [(f"Mast {i}", x, y) for i, (x, y) in enumerate(inside, start=1)]


# ---------------------------------------------------------------- boreholes
def borehole_sites(profiles: dict):
    """[(id, x, y)] from BOREHOLES."""
    out = []
    for bid, (name, s, offset) in BOREHOLES.items():
        p = profiles[name]
        if s is None:
            [(s, _s3, _d)] = profile_ties(_line(profiles["P1"]), _line(profiles["P3"]), 0.0)
        x, y = p.xy(s)
        out.append((bid, float(x) - offset * math.sin(p.azimuth),
                    float(y) + offset * math.cos(p.azimuth)))
    return out


def borehole_log(x, y, bodies, bedrock, topsoil):
    """[(top, bottom, lithology)] from the model's layering at (x, y), 0.1 m precision."""
    rock = round(float(bedrock(x, y)), 1)
    rows = [(0.0, 0.3, "Mutterboden"), (0.3, topsoil, "Sand"), (topsoil, rock, "Geschiebelehm"),
            (rock, LOG_DEPTH, "Fels (verwittert)")]
    for body in bodies:
        iv = body.interval(x, y) if body.clay else None
        if iv is None or round(iv[0], 1) >= round(iv[1], 1):
            continue
        top, bottom = round(iv[0], 1), round(iv[1], 1)
        keep = []
        for a, b, lith in rows:
            if a < top:
                keep.append((a, min(b, top), lith))
            if b > bottom:
                keep.append((max(a, bottom), b, lith))
        rows = sorted(keep + [(top, bottom, "Ton")])
    merged = []
    for a, b, lith in rows:
        if merged and merged[-1][2] == lith:
            merged[-1] = (merged[-1][0], b, lith)
        else:
            merged.append((a, b, lith))
    return merged


def write_boreholes(path: Path, sites, logs, terrain) -> None:
    from osgeo import gdal, ogr, osr

    path.unlink(missing_ok=True)
    with gdal.ExceptionMgr(), ogr.ExceptionMgr(), osr.ExceptionMgr(), \
            gdal.config_option("OGR_CURRENT_DATE", GPKG_DATE):
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(EPSG)
        layer = ds.CreateLayer("boreholes", srs, ogr.wkbPoint)
        for name, kind in (("id", ogr.OFTString), ("name", ogr.OFTString),
                           ("elevation", ogr.OFTReal)):
            layer.CreateField(ogr.FieldDefn(name, kind))
        for bid, x, y in sites:
            f = ogr.Feature(layer.GetLayerDefn())
            f.SetField("id", bid)
            f.SetField("name", f"Bohrung {bid} (synthetisch)")
            f.SetField("elevation", round(float(terrain(x, y)), 2))
            point = ogr.Geometry(ogr.wkbPoint)
            point.AddPoint_2D(round(x, 2), round(y, 2))
            f.SetGeometry(point)
            layer.CreateFeature(f)
        table = ds.CreateLayer("borehole_logs", None, ogr.wkbNone)
        for name, kind in (("borehole_id", ogr.OFTString), ("top", ogr.OFTReal),
                           ("bottom", ogr.OFTReal), ("lithology", ogr.OFTString)):
            table.CreateField(ogr.FieldDefn(name, kind))
        for bid, rows in logs.items():
            for top, bottom, lith in rows:
                f = ogr.Feature(table.GetLayerDefn())
                f.SetField("borehole_id", bid)
                f.SetField("top", top)
                f.SetField("bottom", bottom)
                f.SetField("lithology", lith)
                table.CreateFeature(f)
        ds = None


# ---------------------------------------------------------------- geology
def _ring(points) -> str:
    pts = list(points) + [points[0]]
    return "(" + ", ".join(f"{x:.3f} {y:.3f}" for x, y in pts) + ")"


def _ellipse(cx, cy, a, b, angle_deg, n=72):
    t = np.linspace(0.0, 2 * np.pi, n, endpoint=False)
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    return [(cx + a * math.cos(u) * c - b * math.sin(u) * s,
             cy + a * math.cos(u) * s + b * math.sin(u) * c) for u in t]


def geology(extent, origin):
    """[(unit, ogr polygon geometry)]: a Talsand valley running SW-NE with a fen-peat patch,
    a Flugsand patch on the till plain, and the till (Grundmoräne) everywhere else."""
    from osgeo import ogr

    ox, oy = origin
    x0, y0, x1, y1 = extent
    c, s = math.cos(math.radians(45.0)), math.sin(math.radians(45.0))
    t = np.arange(-800.0, 800.1, 10.0)                 # along the valley axis
    cx, cy = ox + t * c, oy + 40.0 + t * s             # axis through origin + (0, 40)
    left = 35.0 + 8.0 * np.sin(2 * np.pi * t / 150.0)
    right = 35.0 + 6.0 * np.sin(2 * np.pi * t / 110.0 + 1.3)
    edge_l = list(zip(cx - left * s, cy + left * c))
    edge_r = list(zip(cx + right * s, cy - right * c))
    valley = ogr.CreateGeometryFromWkt(f"POLYGON({_ring(edge_l + edge_r[::-1])})")
    area = ogr.CreateGeometryFromWkt(
        f"POLYGON({_ring([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])})")
    valley = valley.Intersection(area)
    peat = ogr.CreateGeometryFromWkt(
        f"POLYGON({_ring(_ellipse(ox + 20.0, oy + 60.0, 35.0, 14.0, 45.0))})").Intersection(valley)
    dune = ogr.CreateGeometryFromWkt(
        f"POLYGON({_ring(_ellipse(ox + 40.0, oy + 190.0, 40.0, 25.0, -20.0))})"
    ).Intersection(area).Difference(valley)
    till = area.Difference(valley).Difference(dune)
    return [("Geschiebelehm (Grundmoräne)", till), ("Talsand", valley.Difference(peat)),
            ("Niedermoortorf", peat), ("Flugsand", dune)]


def _multipolygon(geom) -> list:
    from osgeo import ogr

    parts = ([geom.GetGeometryRef(i) for i in range(geom.GetGeometryCount())]
             if geom.GetGeometryType() == ogr.wkbMultiPolygon else [geom])
    return [[[[round(x, 2), round(y, 2)] for x, y, *_ in part.GetGeometryRef(k).GetPoints()]
             for k in range(part.GetGeometryCount())] for part in parts]


# ---------------------------------------------------------------- DEM
def embankment(x, y, p2):
    """Height (m) of the road embankment crossing P2 at ROAD['s'], 0 off it."""
    rx, ry = p2.xy(ROAD["s"])
    direction = p2.azimuth + math.radians(ROAD["angle"])
    dist = np.abs((np.asarray(x, float) - rx) * math.sin(direction)
                  - (np.asarray(y, float) - ry) * math.cos(direction))
    ramp = (ROAD["foot"] - dist) / (ROAD["foot"] - ROAD["crest"])
    return ROAD["height"] * np.clip(ramp, 0.0, 1.0)


def dem_grid(extent, terrain, p2):
    """(float32 heights, GDAL geotransform); each pixel holds the height at its centre."""
    x0, y0, x1, y1 = extent
    nx, ny = int(round((x1 - x0) / PIXEL)), int(round((y1 - y0) / PIXEL))
    xc = x0 + (np.arange(nx) + 0.5) * PIXEL
    yc = y1 - (np.arange(ny) + 0.5) * PIXEL
    gx, gy = np.meshgrid(xc, yc)
    z = terrain(gx, gy) + embankment(gx, gy, p2)
    return z.astype(np.float32), (x0, PIXEL, 0.0, y1, 0.0, -PIXEL)


def write_dem(path: Path, z, transform) -> None:
    from osgeo import gdal, osr

    path.unlink(missing_ok=True)
    with gdal.ExceptionMgr(), osr.ExceptionMgr():
        ds = gdal.GetDriverByName("GTiff").Create(
            str(path), z.shape[1], z.shape[0], 1, gdal.GDT_Float32,
            ["COMPRESS=DEFLATE", "PREDICTOR=3"])
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(EPSG)
        ds.SetProjection(srs.ExportToWkt())
        ds.SetGeoTransform(transform)
        ds.GetRasterBand(1).WriteArray(z)
        ds = None


# ---------------------------------------------------------------- writers
def _write_geojson(path: Path, features: list) -> None:
    head = json.dumps({"type": "FeatureCollection",
                       "crs": {"type": "name", "properties": {"name": CRS_URN}}})[:-1]
    text = (head + ', "features": [\n'
            + ",\n".join(json.dumps(f, ensure_ascii=False) for f in features) + "\n]}\n")
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(text.encode("utf-8"))


def write_context(context_dir: Path, profiles: dict, bodies, masts, extent, terrain, bedrock,
                  topsoil: float, origin) -> None:
    context_dir = Path(context_dir)
    context_dir.mkdir(parents=True, exist_ok=True)
    _write_geojson(context_dir / "pylons.geojson", [
        {"type": "Feature", "properties": {"name": name},
         "geometry": {"type": "Point", "coordinates": [x, y]}} for name, x, y in masts])
    sites = borehole_sites(profiles)
    logs = {bid: borehole_log(x, y, bodies, bedrock, topsoil) for bid, x, y in sites}
    write_boreholes(context_dir / "boreholes.gpkg", sites, logs, terrain)
    _write_geojson(context_dir / "geology.geojson", [
        {"type": "Feature", "properties": {"unit": unit},
         "geometry": {"type": "MultiPolygon", "coordinates": _multipolygon(geom)}}
        for unit, geom in geology(extent, origin)])
    write_dem(context_dir / "dem.tif", *dem_grid(extent, terrain, profiles["P2"]))
