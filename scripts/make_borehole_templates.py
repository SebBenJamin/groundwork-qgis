"""The borehole data templates for users (docs/user/templates/): one Excel file with the three
sheets the plugin needs (collars, layers, curves) and the same as CSV files, filled with a
tiny MADE-UP example of three boreholes along a 100 m line.

Run with QGIS's Python (needs GDAL):
    python-qgis.bat scripts/make_borehole_templates.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "user" / "templates"
CRS = "EPSG:25833"

# made-up example: three boreholes near a line from (400000, 5800000) to (400100, 5800000)
COLLARS = [
    ("BH1", 400010.0, 5800001.5, 31.20, 6.0),
    ("BH2", 400050.0, 5799998.0, 30.85, 8.0),
    ("BH3", 400090.0, 5800002.0, 30.40, 5.0),
]
LAYERS = [
    ("BH1", 0.0, 0.4, "topsoil", "humic, dark brown"),
    ("BH1", 0.4, 2.5, "sand", "fine to medium sand"),
    ("BH1", 2.5, 6.0, "clay", "silty clay, grey"),
    ("BH2", 0.0, 0.3, "topsoil", ""),
    ("BH2", 0.3, 4.0, "sand", "medium sand, some gravel"),
    ("BH2", 4.0, 8.0, "gravel", "sandy gravel"),
    ("BH3", 0.0, 1.2, "peat", ""),
    ("BH3", 1.2, 5.0, "sand", "fine sand"),
]


def _curves() -> list[tuple]:
    rows = []
    levels = {"topsoil": (60.0, 80.0), "sand": (35.0, 300.0), "clay": (110.0, 20.0),
              "gravel": (25.0, 600.0), "peat": (40.0, 50.0)}       # made-up example values
    for bid, _x, _y, _z, total in COLLARS:
        d = 0.0
        while d <= total + 1e-9:
            lith = next(t for b, top, bot, t, _n in LAYERS if b == bid and top <= d <= bot)
            gamma, res = levels[lith]
            rows.append((bid, round(d, 2), gamma, res))
            d += 0.5
    return rows


SHEETS = {
    "collars": (["id", "x", "y", "elevation", "total_depth"], COLLARS),
    "layers": (["id", "top", "bottom", "lithology", "description"], LAYERS),
    "curves": (["id", "depth", "gamma_api", "resistivity_ohmm"], None),
}


def write(out: Path = OUT) -> list[Path]:
    from osgeo import gdal, ogr
    out.mkdir(parents=True, exist_ok=True)
    written = []
    xlsx = out / "boreholes_template.xlsx"
    xlsx.unlink(missing_ok=True)
    with gdal.ExceptionMgr(), ogr.ExceptionMgr():
        ds = ogr.GetDriverByName("XLSX").CreateDataSource(str(xlsx))
        for name, (fields, rows) in SHEETS.items():
            rows = rows if rows is not None else _curves()
            layer = ds.CreateLayer(name, None, ogr.wkbNone)
            for i, field in enumerate(fields):
                kind = ogr.OFTString if isinstance(rows[0][i], str) else ogr.OFTReal
                layer.CreateField(ogr.FieldDefn(field, kind))
            for row in rows:
                f = ogr.Feature(layer.GetLayerDefn())
                for field, value in zip(fields, row):
                    f.SetField(field, value)
                layer.CreateFeature(f)
        ds = None
    written.append(xlsx)
    for name, (fields, rows) in SHEETS.items():
        path = out / f"boreholes_{name}.csv"
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(fields)
            w.writerows(rows if rows is not None else _curves())
        written.append(path)
    return written


def main() -> int:
    for path in write():
        print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
