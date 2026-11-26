"""The two swisstopo reflection lines of the Vaud demo and the elevation around them (numpy
only, no QGIS).

Source: Federal Office of Topography swisstopo, "2D and 3D reflection seismic in Switzerland"
(opendata.swiss; free use, the source must be named). Each line comes as a zip with its stack
(``*_stk-p.sgy``, LV95 positions in the source fields), a picture and a report.

Elevation: swissALTI3D (swisstopo, same terms), 1 km tiles in LV95 named
``swissalti3d_<year>_<E km>-<N km>`` in swisstopo's STAC catalogue; the demo carries it
resampled to 10 m and cut to a corridor along both lines.
"""
from __future__ import annotations

import re

import numpy as np

CRS = "EPSG:2056"
BASE = "https://data.geo.admin.ch/ch.swisstopo.geologie-reflexionsseismik/"
#: line name -> its zip under BASE
LINES = {"VD-P760057": "875/vd-p760057.zip", "VD-P760068": "886/vd-p760068.zip"}
STACK_SUFFIX = "_stk-p.sgy"
#: Source of the datum and velocities: the original section sheet in swisstopo's download,
#: VD-P760057-stk.TIF (CGG 1976, "PROFIL 76 VD 57"). Its title block: "TEMPS RAPPORTES AU
#: DP 500 M" (times referred to a datum plane at 500 m) and "VITESSE D'HOMOGENEITE 4000 m/s"
#: (replacement velocity). Its table "V. MOY. EN M/S": average velocities against two-way time,
#: one column per stretch of the line (midpoints PM 221-285, 180, 129, 66, 1). The scan is
#: fuzzy and its printer draws 0 like 8: digits marked "?" were chosen by plausibility (the
#: average velocity grows with time, neighbouring columns are close).
DATUM = 500.0                   # m, "DP 500 M"
#: m/s, "VITESSE D'HOMOGENEITE": not applied; processing used it to bring the data to the datum,
#: and the sheet's times and velocities already count from there
REPLACEMENT_VELOCITY = 4000.0
#: rows: two-way time ms, then PM 221-285, PM 180, PM 129, PM 66, PM 1 (m/s)
SHEET_AVERAGE_VELOCITIES = (
    (200, 3500, 3599, 3199, 3199, 3199),    # 3500? (or 3508)
    (400, 3500, 3599, 3199, 3199, 3496),    # 3500?
    (600, 3800, 3774, 3826, 4024, 4093),    # 3800? (or 3888), 4024? (reads 4824), 4093?
    (800, 4265, 4256, 4449, 4449, 4506),    # 4506? (or 4500 / 4508)
    (1000, 4479, 4463, 4569, 4599, 4659),   # 4599? (or 4589)
    (1200, 4723, 4599, 4764, 4721, 4749),
    (1400, 4865, 4825, 4830, 4800, 4852),   # 4800? (or 4808 / 4888)
    (1600, 4968, 4867, 4879, 4873, 5027),   # 5027? (reads 5827)
    (1800, 5048, 4899, 4926, 4963, 5129),   # 5048? (reads 5848)
    (2000, 5104, 5037, 4971, 5072, 5176),   # 5104? (reads 5184), 5072? (reads 9872)
    (2200, 5156, 5150, 5028, 5161, 5222),   # 5150? (or 5158)
    (2400, 5199, 5220, 5132, 5220, 5262),   # 5220? (or 5228) twice, 5132? (or 5182)
    (2600, 5236, 5257, 5209, 5257, 5296),   # 5209? (or 5299)
    (2800, 5271, 5289, 5244, 5289, 5324),
    (3000, 5299, 5316, 5274, 5316, 5349),
    (3200, 5324, 5340, 5301, 5340, 5371),   # 5340? (or 5348) twice, 5301? (reads 5381)
    (3400, 5347, 5361, 5324, 5361, 5391),   # 5391? (or 5381)
    (3600, 5366, 5380, 5345, 5380, 5408),   # 5380? (or 5388) twice, 5408? (reads 5488)
    (3800, 5384, 5387, 5364, 5387, 5423),   # 5387? (or 5397) twice
)
#: one function for the whole line: at each time the median of the five columns
VELOCITY_TABLE = [[row[0] / 1000.0, float(np.median(row[1:]))] for row in SHEET_AVERAGE_VELOCITIES]
#: how both files are read: positions in the source fields, time, time zero at the sheet's
#: datum, depths below it from the sheet's average velocities.
#: VD-P760068 has no sheet in its zip; it is from the same 1976 survey and uses the same values.
OPTIONS = {"position": "map", "xy_field": "source", "crs": CRS, "domain": "time",
           "zero": "datum", "datum": DATUM,
           "velocity_table": VELOCITY_TABLE, "velocity_kind": "average"}
CORRIDOR = 500.0        # m each side of the lines: the DEM the demo carries
PIXEL = 10.0            # m, the demo's DEM
TILE = 1000.0           # m, a swissALTI3D tile
STAC_ITEMS = "https://data.geo.admin.ch/api/stac/v0.9/collections/ch.swisstopo.swissalti3d/items"
_ITEM = re.compile(r"^swissalti3d_(\d{4})_(\d{4})-(\d{4})$")
TILE_GSD = "2"          # the 2 m tiles (also 0.5 m in the catalogue)


def zip_name(line: str) -> str:
    return LINES[line].rsplit("/", 1)[1]


def shipped_name(line: str) -> str:
    """The stack as the demo carries it: ``data/<line>_stack.sgy``."""
    return f"{line}_stack.sgy"


def stack_member(names) -> str | None:
    """The zip member that is the line's stack (``*_stk-p.sgy``, any case), else None."""
    hits = [n for n in names if n.lower().endswith(STACK_SUFFIX)]
    return hits[0] if len(hits) == 1 else None


def distance_to_lines(x, y, lines) -> np.ndarray:
    """The distance (m) of the points ``x``, ``y`` (any matching shapes) to the nearest
    segment of any of the polylines ``lines`` ((n, 2) each)."""
    x, y = np.broadcast_arrays(np.asarray(x, float), np.asarray(y, float))
    best = np.full(x.shape, np.inf)
    for line in lines:
        pts = np.asarray(line, float)[:, :2]
        for (ax, ay), (bx, by) in zip(pts[:-1], pts[1:]):
            dx, dy = bx - ax, by - ay
            t = np.clip(((x - ax) * dx + (y - ay) * dy) / max(dx * dx + dy * dy, 1e-12), 0, 1)
            best = np.minimum(best, np.hypot(x - (ax + t * dx), y - (ay + t * dy)))
    return best


def corridor_box(lines, corridor: float = CORRIDOR, pixel: float = PIXEL
                 ) -> tuple[float, float, float, float]:
    """(x0, y0, x1, y1) of the lines + ``corridor``, on whole ``pixel`` steps."""
    xy = np.vstack([np.asarray(line, float)[:, :2] for line in lines])
    (x0, y0), (x1, y1) = xy.min(axis=0) - corridor, xy.max(axis=0) + corridor
    return (float(np.floor(x0 / pixel) * pixel), float(np.floor(y0 / pixel) * pixel),
            float(np.ceil(x1 / pixel) * pixel), float(np.ceil(y1 / pixel) * pixel))


def tiles_near(lines, corridor: float = CORRIDOR) -> list[tuple[int, int]]:
    """The swissALTI3D tiles ``(E km, N km)`` (lower-left corner) that reach within
    ``corridor`` of a line, as a conservative set: a tile counts when its centre lies within
    ``corridor`` + half its diagonal."""
    x0, y0, x1, y1 = corridor_box(lines, corridor, TILE)
    e = np.arange(int(x0 // TILE), int(x1 // TILE))
    n = np.arange(int(y0 // TILE), int(y1 // TILE))
    ee, nn = np.meshgrid(e, n)
    near = distance_to_lines((ee + 0.5) * TILE, (nn + 0.5) * TILE, lines) \
        <= corridor + TILE * np.sqrt(0.5)
    return sorted((int(a), int(b)) for a, b in zip(ee[near], nn[near]))


def newest_tiles(items) -> dict[tuple[int, int], str]:
    """``(E km, N km) -> href`` of the 2 m GeoTIFF of each tile's newest year, from STAC
    items (dicts with ``id`` and ``assets``)."""
    best: dict[tuple[int, int], tuple[int, str]] = {}
    for item in items:
        m = _ITEM.match(item.get("id", ""))
        if not m:
            continue
        year, key = int(m.group(1)), (int(m.group(2)), int(m.group(3)))
        hrefs = [a["href"] for name, a in (item.get("assets") or {}).items()
                 if name.endswith(f"_{TILE_GSD}_2056_5728.tif")]
        if hrefs and (key not in best or year > best[key][0]):
            best[key] = (year, hrefs[0])
    return {k: href for k, (_year, href) in best.items()}


def outside_corridor(geotransform, shape, lines, corridor: float = CORRIDOR) -> np.ndarray:
    """Boolean (rows, cols) of a north-up raster: True where a pixel centre lies farther
    than ``corridor`` from every line."""
    x0, dx, _r1, y0, _r2, dy = geotransform
    rows, cols = shape
    x = x0 + (np.arange(cols) + 0.5) * dx
    y = y0 + (np.arange(rows) + 0.5) * dy
    xx, yy = np.meshgrid(x, y)
    return distance_to_lines(xx, yy, lines) > corridor
