"""Converters for the Erfurt real-data demo (no QGIS; GDAL/OGR from the QGIS Python).

Sources (both CC BY 4.0):
- ERT: Silbermann, Pohle, Jung, Werban (2025), PANGAEA, doi:10.1594/PANGAEA.974818 — seven
  transects, BERT 2.2.9 inversions with topography, electrode positions in UTM zone 32N;
- cores: Hein et al. (2026), PLoS ONE 21(1): e0337410, Supporting Information S1 File,
  Suppl. Table 3 "Simplified stratigraphic logs of all sediment cores" (UTM zone 32N).

The authors' values are never changed: depths are only converted from cm to m, units and
properties keep the authors' words."""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

EPSG = 32632                                    # "WGS 1984 UTM Zone 32N" (explanation PDFs)
TRANSECTS = ("ERT02", "ERT03", "ERT04", "ERT06", "ERT07", "ERT11", "ERT12")
SPACING = 0.5                                   # m, all transects
#: measurement types of the raw files, as the explanation PDFs name them
ARRAYS = {"WA": "Wenner alpha", "DD": "dipole-dipole"}
_CORE = re.compile(r"^Core (EN-RK \d+) \(\s*([\d.]*)\s*E,\s*([\d.]*)\s*N\)")
_DEPTH = re.compile(r"^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$")


@dataclass(frozen=True)
class CoreSite:
    id: str
    x: float
    y: float


def docx_paragraphs(path: Path) -> list[str]:
    """The text paragraphs (table cells included) of a .docx, in document order."""
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    out = []
    for para in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        text = "".join(re.findall(r"<w:t(?: [^>]*)?>([^<]*)</w:t>", para))
        text = (text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
                .replace("&quot;", '"').replace("&apos;", "'"))
        if text.strip():
            out.append(text)
    return out


def parse_core_logs(paragraphs: list[str]):
    """Sites and ``{core id: [(top m, bottom m, unit, properties)]}`` from Suppl. Table 3:
    a "Core EN-RK n (E, N)" heading, then rows of depth range (cm), unit, properties. A core
    listed without coordinates keeps its log but gets no site (it cannot be placed)."""
    sites, logs = [], {}
    current, i = None, 0
    while i < len(paragraphs):
        line = paragraphs[i].strip()
        head = _CORE.match(line)
        if head:
            current = head.group(1)
            if head.group(2) and head.group(3):         # two cores are listed as "(E, N)"
                sites.append(CoreSite(current, float(head.group(2)), float(head.group(3))))
            logs[current] = []
            i += 1
            continue
        depth = _DEPTH.match(line)
        if current is not None and depth and i + 2 < len(paragraphs):
            top, bottom = float(depth.group(1)) / 100.0, float(depth.group(2)) / 100.0
            logs[current].append((top, bottom, paragraphs[i + 1].strip(),
                                  paragraphs[i + 2].strip()))
            i += 3
            continue
        i += 1
    return sites, logs


def survey_info(raw_path: Path) -> dict[str, str]:
    """Array(s) and date of a RESECS raw file (columns "#", "Type", …, "Time")."""
    lines = Path(raw_path).read_text(encoding="utf-8", errors="replace").splitlines()
    header = lines[0].split("\t")
    i_type, i_time = header.index("Type"), header.index("Time")
    types, first = [], None
    for line in lines[1:]:
        cols = line.split("\t")
        if len(cols) <= max(i_type, i_time):
            continue
        if cols[i_type] not in types:
            types.append(cols[i_type])
        if first is None and cols[i_time].strip():
            first = datetime.strptime(cols[i_time].split()[0], "%d.%m.%Y").date()
    out = {"array": ", ".join(ARRAYS.get(t, t) for t in types)}
    if first is not None:
        out["date"] = first.isoformat()
    return out


def transect_files(cache: Path, name: str) -> dict[str, Path]:
    """The files of one transect in the unpacked PANGAEA download (``ERT06-v2/…``)."""
    folder = next(p for p in sorted(Path(cache).glob(f"{name}*")) if p.is_dir())

    def one(sub: str, pattern: str) -> Path:
        found = [p for p in sorted((folder / sub).glob(pattern)) if "Kopie" not in p.name]
        if not found:
            raise FileNotFoundError(f"{folder / sub}: no {pattern}")
        return found[0]

    return {"dgps": one("DGPS data", "*.txt"), "topo": one("Processing data", "*_topo.data"),
            "model": one("Processing data", "dcinv.result.vtk"), "raw": one("Raw data", "*.txt"),
            "explanation": one(".", "Explanation_*.pdf")}


def write_cores_gpkg(path: Path, sites, logs) -> None:
    from osgeo import gdal, ogr, osr

    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with gdal.ExceptionMgr(), ogr.ExceptionMgr(), osr.ExceptionMgr(), \
            gdal.config_option("OGR_CURRENT_DATE", "2026-11-09T00:00:00.000Z"):
        ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(EPSG)
        layer = ds.CreateLayer("cores", srs, ogr.wkbPoint)
        for name in ("id", "name"):
            layer.CreateField(ogr.FieldDefn(name, ogr.OFTString))
        layer.CreateField(ogr.FieldDefn("depth", ogr.OFTReal))
        for s in sites:
            f = ogr.Feature(layer.GetLayerDefn())
            f.SetField("id", s.id)
            f.SetField("name", f"Core {s.id} (Hein et al. 2026)")
            f.SetField("depth", max((b for _t, b, _u, _p in logs.get(s.id, [])), default=0.0))
            point = ogr.Geometry(ogr.wkbPoint)
            point.AddPoint_2D(s.x, s.y)
            f.SetGeometry(point)
            layer.CreateFeature(f)
        table = ds.CreateLayer("core_logs", None, ogr.wkbNone)
        for name, kind in (("core_id", ogr.OFTString), ("top", ogr.OFTReal),
                           ("bottom", ogr.OFTReal), ("unit", ogr.OFTString),
                           ("properties", ogr.OFTString)):
            table.CreateField(ogr.FieldDefn(name, kind))
        for s in sites:
            for top, bottom, unit, props in logs.get(s.id, []):
                f = ogr.Feature(table.GetLayerDefn())
                f.SetField("core_id", s.id)
                f.SetField("top", top)
                f.SetField("bottom", bottom)
                f.SetField("unit", unit)
                f.SetField("properties", props)
                table.CreateFeature(f)
        ds = None
