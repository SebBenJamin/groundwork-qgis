"""Converters for the Gülpe real-data demo: PANGAEA cores, DGPS electrodes, BERT electrode
files and DGM1 tiles into demo files (no QGIS; GDAL/OGR and pyproj from the QGIS Python).

The authors' values are never changed: core rows marked "offset" (core loss) are the only ones
dropped, and every other interval keeps its original depths.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

EPSG = 25833
_EVENT = re.compile(r"(RK\d+) \(([^)]*)\) \* LATITUDE: ([-\d.]+) \* LONGITUDE: ([-\d.]+)"
                    r".*?ELEVATION: ([-\d.]+) m")
# 0-based columns of the cores data matrix
C_EVENT, C_TOP, C_BOTTOM, C_TEXTURE, C_CLASS, C_COMMENT, C_HORIZON = 0, 2, 3, 4, 5, 11, 12


@dataclass(frozen=True)
class CoreSite:
    id: str
    transect: str
    x: float
    y: float
    elevation: float


def lithology(texture: str, grain_class: str, comment: str, horizon: str) -> str | None:
    """Label of one core interval; ``None`` drops it (core loss)."""
    texture, grain_class = texture.strip(), grain_class.strip()
    comment, horizon = comment.strip(), horizon.strip()
    if texture:
        return f"{grain_class} · {texture}" if grain_class else texture
    if "offset" in comment.lower():
        return None
    if horizon.startswith("H") or "peat" in comment.lower():
        return "peat"
    return horizon or comment or None


def parse_cores(text: str) -> tuple[list[CoreSite], dict[str, list[tuple[float, float, str]]]]:
    from pyproj import Transformer

    head, _, body = text.partition("\n*/\n")
    tr = Transformer.from_crs(4326, EPSG, always_xy=True)
    sites, seen = [], set()
    for rk, transect, lat, lon, elev in _EVENT.findall(head):
        if rk in seen:
            continue
        seen.add(rk)
        x, y = tr.transform(float(lon), float(lat))
        sites.append(CoreSite(rk, transect, round(x, 2), round(y, 2), float(elev)))
    logs: dict[str, list[tuple[float, float, str]]] = {s.id: [] for s in sites}
    for line in body.splitlines()[1:]:                    # first line: column names
        cols = line.split("\t") + [""] * 16
        if not cols[C_EVENT] or not cols[C_TOP].strip() or not cols[C_BOTTOM].strip():
            continue
        lith = lithology(cols[C_TEXTURE], cols[C_CLASS], cols[C_COMMENT], cols[C_HORIZON])
        top, bottom = float(cols[C_TOP]), float(cols[C_BOTTOM])
        if lith is None or bottom <= top:
            continue
        logs.setdefault(cols[C_EVENT], []).append((top, bottom, lith))
    for rows in logs.values():
        rows.sort()
    return sites, logs


#: the cores' lab samples: (field, unit, what it is); columns 16-30 of the cores table in this
#: order, then the derived sums sand / silt / clay
LAB_TABLE = "core_lab"
LAB_FIELDS = (
    ("tn", "%", "total nitrogen"), ("tc", "%", "total carbon"),
    ("tic", "%", "total inorganic carbon (carbonate)"), ("toc", "%", "total organic carbon"),
    ("ts", "%", "total sulfur"),
    ("cs_2000_630um", "%", "coarse sand 2000-630 µm"),
    ("ms_630_200um", "%", "medium sand 630-200 µm"),
    ("fs_200_125um", "%", "fine sand 200-125 µm"), ("fs_125_64um", "%", "fine sand 125-64 µm"),
    ("cu_63_20um", "%", "coarse silt 63-20 µm"), ("mu_20_6_3um", "%", "medium silt 20-6.3 µm"),
    ("fu_6_3_2um", "%", "fine silt 6.3-2 µm"), ("cc_2_0_63um", "%", "coarse clay 2-0.63 µm"),
    ("mc_0_63_0_2um", "%", "medium clay 0.63-0.2 µm"), ("fc_lt0_2um", "%", "fine clay < 0.2 µm"),
    ("sand", "%", "sand 2000-64 µm (sum of the sand fractions)"),
    ("silt", "%", "silt 63-2 µm (sum of the silt fractions)"),
    ("clay", "%", "clay < 2 µm (sum of the clay fractions)"))
C_SAMPLE, C_SAMPLE_TOP, C_SAMPLE_BOTTOM, C_LAB = 13, 14, 15, 16
_MEASURED = 15                          # the first 15 fields are columns; the rest are sums


def parse_samples(text: str) -> list[tuple[str, float, float, str, dict[str, float]]]:
    """(core id, top, bottom, sample id, {field: value}) of each lab sample of the cores
    table, values as the authors give them; sand/silt/clay are the sums of their fractions."""
    _head, _, body = text.partition("\n*/\n")
    out = []
    for line in body.splitlines()[1:]:
        cols = line.split("\t") + [""] * 32
        if not cols[C_EVENT] or not cols[C_SAMPLE].strip():
            continue
        values = {}
        for k, (name, _unit, _what) in enumerate(LAB_FIELDS[:_MEASURED]):
            cell = cols[C_LAB + k].strip()
            if cell and not cell.startswith("<"):       # "<0.0020": below detection, a gap
                values[name] = float(cell)
        names = [n for n, _u, _w in LAB_FIELDS[:_MEASURED]]
        for total, parts in (("sand", names[5:9]), ("silt", names[9:12]),
                             ("clay", names[12:15])):
            if all(n in values for n in parts):
                values[total] = sum(values[n] for n in parts)
        out.append((cols[C_EVENT], float(cols[C_SAMPLE_TOP]), float(cols[C_SAMPLE_BOTTOM]),
                    cols[C_SAMPLE].strip(), values))
    return out


def write_lab_table(path: Path, samples) -> None:
    """Add ``LAB_TABLE`` to the cores GeoPackage: one row per sample at its middle depth (to
    the centimetre), with its top, bottom and sample id."""
    from osgeo import gdal, ogr

    with gdal.ExceptionMgr(), ogr.ExceptionMgr(), \
            gdal.config_option("OGR_CURRENT_DATE", "2026-11-25T00:00:00.000Z"):
        ds = ogr.Open(str(path), update=1)
        table = ds.CreateLayer(LAB_TABLE, None, ogr.wkbNone, options=[
            "DESCRIPTION=Lab values of the core samples (Köhler et al. 2025, PANGAEA 983887); "
            "depth = middle of the sample"])
        for name, kind in (("core_id", ogr.OFTString), ("depth", ogr.OFTReal),
                           ("top", ogr.OFTReal), ("bottom", ogr.OFTReal),
                           ("sample_id", ogr.OFTString)):
            table.CreateField(ogr.FieldDefn(name, kind))
        for name, _unit, _what in LAB_FIELDS:
            table.CreateField(ogr.FieldDefn(name, ogr.OFTReal))
        for cid, top, bottom, sid, values in sorted(samples, key=lambda s: (int(s[0][2:]), s[1])):
            f = ogr.Feature(table.GetLayerDefn())
            f.SetField("core_id", cid)
            f.SetField("depth", float(np.floor((top + bottom) / 2 * 100 + 0.5) / 100))
            f.SetField("top", top)
            f.SetField("bottom", bottom)
            f.SetField("sample_id", sid)
            for name, value in values.items():
                f.SetField(name, value)
            table.CreateFeature(f)
        ds = None


def read_dgps(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """(numbers from the ID suffix, xyz) of a DGPS file with header ``E N H ID``."""
    numbers, xyz = [], []
    for line in Path(path).read_text(encoding="utf-8").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 4:
            xyz.append([float(v) for v in parts[:3]])
            numbers.append(int(re.search(r"(\d+)$", parts[3]).group(1)))
    return np.array(numbers, dtype=int), np.array(xyz, dtype=float)


def read_topo_electrodes(path: Path) -> np.ndarray:
    """Electrode (x, z) rows of a BERT ``*_topo.data`` file."""
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    n = int(lines[0].split()[0])
    rows = [ln.split()[:2] for ln in lines[1:] if ln.strip() and not ln.startswith("#")][:n]
    return np.array(rows, dtype=float)


def match_electrodes(electrodes_xz: np.ndarray, numbers: np.ndarray, xyz: np.ndarray,
                     spacing: float) -> np.ndarray:
    """DGPS number of each electrode: the electrode at x is point ``round(x / spacing) + 1``
    (x counts from point 1), checked against the point's height (to 2 cm, the DGPS precision: the authors adjusted one T1 height by 11 mm)."""
    by_number = {int(n): i for i, n in enumerate(numbers)}
    out = []
    for x, z in electrodes_xz:
        n = int(round((x - electrodes_xz[0, 0]) / spacing)) + 1
        i = by_number.get(n)
        if i is None:
            raise ValueError(f"electrode at x={x}: no DGPS point {n}")
        if abs(xyz[i, 2] - z) > 0.02:
            raise ValueError(f"electrode at x={x}: z {z} differs from DGPS point {n} "
                             f"height {xyz[i, 2]}")
        out.append(n)
    return np.array(out, dtype=int)


def write_stations_csv(path: Path, numbers, xyz) -> None:
    lines = ["number,x,y,z"] + [f"{int(n)},{x:.3f},{y:.3f},{z:.3f}"
                                for n, (x, y, z) in zip(numbers, xyz)]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def write_cores_gpkg(path: Path, sites, logs) -> None:
    from osgeo import gdal, ogr, osr

    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with gdal.ExceptionMgr(), ogr.ExceptionMgr(), osr.ExceptionMgr(), \
            gdal.config_option("OGR_CURRENT_DATE", "2026-11-04T00:00:00.000Z"):
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(EPSG)
        layer = ds.CreateLayer("cores", srs, ogr.wkbPoint)
        for name, kind in (("id", ogr.OFTString), ("name", ogr.OFTString),
                           ("transect", ogr.OFTString), ("elevation", ogr.OFTReal)):
            layer.CreateField(ogr.FieldDefn(name, kind))
        for s in sites:
            f = ogr.Feature(layer.GetLayerDefn())
            f.SetField("id", s.id)
            f.SetField("name", f"Core {s.id} (Köhler et al. 2025)")
            f.SetField("transect", s.transect)
            f.SetField("elevation", s.elevation)
            point = ogr.Geometry(ogr.wkbPoint)
            point.AddPoint_2D(s.x, s.y)
            f.SetGeometry(point)
            layer.CreateFeature(f)
        table = ds.CreateLayer("core_logs", None, ogr.wkbNone)
        for name, kind in (("core_id", ogr.OFTString), ("top", ogr.OFTReal),
                           ("bottom", ogr.OFTReal), ("lithology", ogr.OFTString)):
            table.CreateField(ogr.FieldDefn(name, kind))
        for cid in sorted(logs, key=lambda k: int(k[2:])):
            for top, bottom, lith in logs[cid]:
                f = ogr.Feature(table.GetLayerDefn())
                f.SetField("core_id", cid)
                f.SetField("top", top)
                f.SetField("bottom", bottom)
                f.SetField("lithology", lith)
                table.CreateFeature(f)
        ds = None


def mosaic_dgm(tile_zips: list[Path], bbox, out: Path, margin: float = 100.0) -> None:
    """GeoTIFF of the tiles cropped to ``bbox`` ± ``margin`` at their native pixel size."""
    from osgeo import gdal

    sources = []
    for z in tile_zips:
        with __import__("zipfile").ZipFile(z) as zf:
            tif = next(n for n in zf.namelist() if n.lower().endswith(".tif"))
        sources.append(f"/vsizip/{Path(z).as_posix()}/{tif}")
    x0, y0, x1, y1 = bbox
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    with gdal.ExceptionMgr():
        vrt = gdal.BuildVRT("", sources)
        gdal.Translate(str(out), vrt, projWin=[x0 - margin, y1 + margin, x1 + margin, y0 - margin],
                       creationOptions=["COMPRESS=LZW"])
        vrt = None
    Path(str(out) + ".aux.xml").unlink(missing_ok=True)
