"""Export interpretation features' 3D pieces to a GeoPackage or a DXF file (OGR).

The geometry comes from the section-space truth (``to_3d`` over the profile's chainage),
so any version can be exported, frozen ones included.
"""
from __future__ import annotations

import os

from osgeo import ogr, osr

from ..store.interp_store import _geom3d

GPKG_LAYERS = {"line": ("lines_3d", ogr.wkbLineString25D),
               "polygon": ("polygons_3d", ogr.wkbPolygon25D),
               "point": ("points_3d", ogr.wkbPoint25D)}
FIELDS = ("feature_id", "letter", "type", "confidence", "note", "profile_id", "version")


def _rows(store, version_id: str, feature_ids):
    feats = {f.id: f for f in store.features(version_id)}
    chainages = {p.id: p.chainage for p in store.profiles()}
    for p in store.pieces(version_id):
        if feature_ids is not None and p.feature_id not in feature_ids:
            continue
        ch = chainages.get(p.profile_id)
        if ch is None:
            continue
        yield p, feats.get(p.feature_id), _geom3d(p, ch)


def _values(p, feat, version_name: str) -> dict:
    return {"feature_id": p.feature_id,
            "letter": feat.letter if feat else "", "type": feat.type if feat else "",
            "confidence": feat.confidence if feat else "", "note": feat.note if feat else "",
            "profile_id": p.profile_id, "version": version_name}


_TRANSLIT = {"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss",
             "·": "-"}


def dxf_layer_name(feat) -> str:
    """``entity_label`` in DXF-safe text: DXF files are ANSI (no "·") and layer names may
    not contain <>/\\":;?*|=`."""
    if feat is None:
        return "unnamed"
    text = " - ".join(x for x in (feat.letter, feat.type) if x) or "unnamed"
    text = "".join("_" if c in '<>/\\":;?*|=`' else c for c in text)
    for a, b in _TRANSLIT.items():
        text = text.replace(a, b)
    return text.encode("ascii", "replace").decode("ascii").replace("?", "_")


def _ring_as_line(geom):
    """A polygon's outer ring as a closed 3D polyline: the DXF writer keeps its z."""
    ring = geom.GetGeometryRef(0)
    line = ogr.Geometry(ogr.wkbLineString25D)
    for x, y, z in ring.GetPoints():
        line.AddPoint(x, y, z)
    return line


def export_pieces(store, version_id: str, feature_ids: set[str] | None, path: str) -> int:
    """Write the pieces of ``feature_ids`` (all when None) of ``version_id`` to ``path``
    (.gpkg or .dxf, overwritten); returns the number of pieces written."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".gpkg", ".dxf"):
        raise ValueError(f"export to .gpkg or .dxf, not {ext or 'no extension'}")
    if os.path.exists(path) and os.path.samefile(path, store.path):
        raise ValueError("that is the project's workbench GeoPackage; choose another file")
    version = next((v for v in store.versions() if v.id == version_id), None)
    version_name = version.name if version is not None else ""
    rows = list(_rows(store, version_id, feature_ids))
    driver = ogr.GetDriverByName("GPKG" if ext == ".gpkg" else "DXF")
    if os.path.exists(path):
        driver.DeleteDataSource(path)
    ds = driver.CreateDataSource(path)
    if ds is None:
        raise OSError(f"cannot create {path}")
    srs = osr.SpatialReference()
    srs.SetFromUserInput(store.crs_authid)
    srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    try:
        if ext == ".dxf":
            lyr = ds.CreateLayer("entities", srs, ogr.wkbUnknown)
            for p, feat, geom in rows:
                f = ogr.Feature(lyr.GetLayerDefn())
                f.SetField("Layer", dxf_layer_name(feat))
                f.SetGeometry(_ring_as_line(geom) if p.kind == "polygon" else geom)
                lyr.CreateFeature(f)
        else:
            layers = {}
            for p, feat, geom in rows:
                name, gtype = GPKG_LAYERS[p.kind]
                if name not in layers:
                    lyr = ds.CreateLayer(name, srs, gtype)
                    for n in FIELDS:
                        lyr.CreateField(ogr.FieldDefn(n, ogr.OFTString))
                    layers[name] = lyr
                lyr = layers[name]
                f = ogr.Feature(lyr.GetLayerDefn())
                for n, value in _values(p, feat, version_name).items():
                    f[n] = value
                if p.kind == "polygon" and geom.GetGeometryType() != ogr.wkbPolygon25D:
                    geom = ogr.ForceTo(geom, ogr.wkbPolygon25D)
                f.SetGeometry(geom)
                lyr.CreateFeature(f)
    finally:
        ds = None
    return len(rows)
