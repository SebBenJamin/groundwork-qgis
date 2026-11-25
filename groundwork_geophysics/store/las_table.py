"""Well logs (``core.las_log``) written as one curve table in a GeoPackage: a row per depth
with the borehole id, the depth in metres below the ground and one column per curve, as
Context Layers' curve tables read them. Each import makes a new table (``las_curves``,
``las_curves_2``, …); nothing existing is changed."""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from osgeo import ogr

TABLE = "las_curves"
_RESERVED = {"id", "depth", "fid"}


def _plain(text: str) -> str:
    name = re.sub(r"[^0-9a-z]+", "_", str(text).lower()).strip("_") or "curve"
    return f"c_{name}" if name[0].isdigit() else name


def curve_columns(logs) -> tuple[list[tuple[str, str]], dict]:
    """[(field, unit)] in first-seen order, and (mnemonic, unit) -> field: a curve keeps one
    column across wells; the same mnemonic in another unit gets its own."""
    columns: list[tuple[str, str]] = []
    by_curve: dict[tuple[str, str], str] = {}
    used: set[str] = set(_RESERVED)
    first_unit: dict[str, str] = {}
    for log in logs:
        for c in log.curves:
            key = (c.mnemonic.upper(), c.unit.upper())
            if key in by_curve:
                continue
            base = _plain(c.mnemonic)
            if base in _RESERVED:
                base += "_log"
            if base in first_unit and first_unit[base] != key[1]:
                base = f"{base}_{_plain(c.unit)}"
            first_unit.setdefault(base, key[1])
            name, n = base, 2
            while name in used:
                name, n = f"{base}_{n}", n + 1
            used.add(name)
            by_curve[key] = name
            columns.append((name, c.unit))
    return columns, by_curve


def _free_name(ds) -> str:
    names = {ds.GetLayerByIndex(i).GetName() for i in range(ds.GetLayerCount())} if ds else set()
    name, n = TABLE, 2
    while name in names:
        name, n = f"{TABLE}_{n}", n + 1
    return name


def write_las_table(gpkg: Path, entries) -> tuple[str, list[tuple[str, str]]]:
    """Write ``entries`` ([(borehole id, LasLog, depth of the ground in the log's depth, m)])
    as a new table in ``gpkg`` (created when missing); its name and [(field, unit)]."""
    gpkg = Path(gpkg)
    ds = ogr.Open(str(gpkg), 1) if gpkg.exists() else \
        ogr.GetDriverByName("GPKG").CreateDataSource(str(gpkg))
    if ds is None:
        raise OSError(f"cannot write {gpkg}")
    try:
        table = _free_name(ds)
        columns, by_curve = curve_columns([log for _bid, log, _off in entries])
        lyr = ds.CreateLayer(table, None, ogr.wkbNone)
        lyr.CreateField(ogr.FieldDefn("id", ogr.OFTString))
        lyr.CreateField(ogr.FieldDefn("depth", ogr.OFTReal))
        for name, _unit in columns:
            lyr.CreateField(ogr.FieldDefn(name, ogr.OFTReal))
        defn = lyr.GetLayerDefn()
        lyr.StartTransaction()
        for bid, log, offset in entries:
            fields = [(by_curve[(c.mnemonic.upper(), c.unit.upper())], c.values)
                      for c in log.curves]
            for i, d in enumerate(np.asarray(log.depth, dtype=float)):
                if not np.isfinite(d):
                    continue
                f = ogr.Feature(defn)
                f["id"] = str(bid)
                f["depth"] = float(d) - float(offset or 0.0)
                for name, values in fields:
                    v = float(values[i])
                    if np.isfinite(v):
                        f[name] = v
                lyr.CreateFeature(f)
        lyr.CommitTransaction()
        return table, columns
    finally:
        ds = None
