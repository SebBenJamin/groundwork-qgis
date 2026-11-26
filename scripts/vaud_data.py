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
#: how both files are read: positions in the source fields, time, a velocity assumed for the
#: depth display, time zero at the catalogue's SRD of 500 m
OPTIONS = {"position": "map", "xy_field": "source", "crs": CRS, "domain": "time",
           "velocity": 3000.0, "zero": "datum", "datum": 500.0}
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
