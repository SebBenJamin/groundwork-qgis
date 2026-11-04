"""GeoPackage project store. QGIS-free: uses only ``osgeo.ogr`` / ``osgeo.osr``.

One GeoPackage holds a whole workbench project: spatial layers ``profiles`` and ``stations``
(which QGIS can display via :meth:`ProjectStore.layer_uri`) and attribute tables
``station_sets``, ``datasets`` and ``wb_meta``.  Every operation opens the file, does its work
and closes it again, so no file lock outlives a call.  GDAL exceptions are enabled only inside
``gdal.ExceptionMgr`` blocks, never process-wide.
"""
from __future__ import annotations

import json
import math
from contextlib import ExitStack, contextmanager
from pathlib import Path

import numpy as np
from osgeo import gdal, ogr, osr

from ..core.model import Dataset, Profile, StationSet
from .interp_store import InterpStoreMixin

SCHEMA_VERSION = 1

_STR, _INT, _REAL = ogr.OFTString, ogr.OFTInteger, ogr.OFTReal
_INT64 = ogr.OFTInteger64

_STATION_SET_FIELDS = [("id", _STR), ("profile_id", _STR), ("name", _STR), ("method", _STR),
                       ("metre0", _REAL), ("warnings", _STR)]
_DATASET_FIELDS = [("id", _STR), ("profile_id", _STR), ("station_set_id", _STR), ("kind", _STR),
                   ("source_path", _STR), ("source_mtime", _REAL), ("source_sha1", _STR),
                   ("reader", _STR), ("reader_options", _STR), ("provenance", _STR),
                   ("version", _INT), ("parent_id", _STR), ("quantity", _STR), ("unit", _STR),
                   ("name", _STR), ("seq", _INT64)]
_STATION_FIELDS = [("set_id", _STR), ("profile_id", _STR), ("set_name", _STR), ("method", _STR),
                   ("number", _INT64), ("chainage", _REAL), ("offset", _REAL), ("seq", _INT64)]


@contextmanager
def _exceptions():
    """Enable GDAL/OGR/OSR exceptions for the duration of the block only."""
    with ExitStack() as stack:
        for mod in (gdal, ogr, osr):
            stack.enter_context(mod.ExceptionMgr(useExceptions=True))
        yield


def _srs(authid: str) -> osr.SpatialReference:
    try:
        with _exceptions():
            srs = osr.SpatialReference()
            srs.SetFromUserInput(authid)
            srs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
            geographic = srs.IsGeographic()
    except RuntimeError as exc:
        raise ValueError(f"Unknown CRS {authid!r}: {exc}") from None
    if geographic:
        raise ValueError(f"Profiles need a projected CRS (metres); {authid} is geographic")
    return srs


def _q(value: str) -> str:
    """SQL string literal."""
    return "'" + str(value).replace("'", "''") + "'"


def _dumps(obj) -> str:
    return json.dumps(obj, sort_keys=True)


def _real(feat, name, default=float("nan")) -> float:
    if feat.IsFieldNull(name) or not feat.IsFieldSet(name):
        return default
    return feat.GetFieldAsDouble(name)


def _text(feat, name) -> str:
    return "" if feat.IsFieldNull(name) else feat.GetFieldAsString(name)


def _make_layer(ds, name, fields, geom=ogr.wkbNone, srs=None):
    lyr = ds.CreateLayer(name, srs, geom)
    for fname, ftype in fields:
        lyr.CreateField(ogr.FieldDefn(fname, ftype))
    return lyr


class ProjectStore(InterpStoreMixin):
    def __init__(self, path: Path, crs_authid: str):
        self.path = Path(path)
        self.crs_authid = crs_authid

    # -- lifecycle ---------------------------------------------------------------------------
    @classmethod
    def create(cls, path: Path, crs_authid: str) -> "ProjectStore":
        path = Path(path)
        srs = _srs(crs_authid)  # validate before touching the disk
        if path.exists():
            raise FileExistsError(str(path))
        with _exceptions():
            ds = ogr.GetDriverByName("GPKG").CreateDataSource(str(path))
            try:
                _make_layer(ds, "profiles", [("id", _STR), ("name", _STR), ("metadata", _STR)],
                            ogr.wkbLineString, srs)
                _make_layer(ds, "stations", _STATION_FIELDS, ogr.wkbPoint25D, srs)
                _make_layer(ds, "station_sets", _STATION_SET_FIELDS)
                _make_layer(ds, "datasets", _DATASET_FIELDS)
                meta = _make_layer(ds, "wb_meta", [("key", _STR), ("value", _STR)])
                for k, v in (("schema_version", str(SCHEMA_VERSION)), ("crs_authid", crs_authid)):
                    f = ogr.Feature(meta.GetLayerDefn())
                    f["key"], f["value"] = k, v
                    meta.CreateFeature(f)
            finally:
                meta = ds = None
        return cls(path, crs_authid)

    @classmethod
    def open(cls, path: Path) -> "ProjectStore":
        path = Path(path)
        bad = ValueError(f"not a Geophysics Workbench project: {path}")
        if not path.is_file():
            raise bad
        try:
            with _exceptions():
                ds = ogr.Open(str(path), 0)
                try:
                    lyr = ds.GetLayerByName("wb_meta") if ds is not None else None
                    if lyr is None:
                        raise bad
                    meta = {f["key"]: f["value"] for f in lyr}
                finally:
                    ds = lyr = None
        except RuntimeError:
            raise bad from None
        version = meta.get("schema_version")
        if version is None or "crs_authid" not in meta:
            raise bad
        if version != str(SCHEMA_VERSION):
            raise ValueError(f"unsupported schema_version {version} in {path} "
                             f"(this plugin reads version {SCHEMA_VERSION})")
        return cls(path, meta["crs_authid"])

    def layer_uri(self, name: str) -> str:
        return f"{self.path}|layername={name}"

    # -- plumbing ----------------------------------------------------------------------------
    @contextmanager
    def _ds(self, write: bool = False):
        with _exceptions():
            ds = ogr.Open(str(self.path), 1 if write else 0)
            try:
                yield ds
            finally:
                ds = None

    @contextmanager
    def _tx(self):
        with self._ds(write=True) as ds:
            ds.StartTransaction()
            try:
                yield ds
            except BaseException:
                ds.RollbackTransaction()
                raise
            else:
                ds.CommitTransaction()

    @staticmethod
    def _delete_where(lyr, where: str) -> None:
        lyr.SetAttributeFilter(where)
        fids = [f.GetFID() for f in lyr]
        lyr.SetAttributeFilter(None)
        for fid in fids:
            lyr.DeleteFeature(fid)

    @staticmethod
    def _select(lyr, where: str | None = None) -> list:
        lyr.SetAttributeFilter(where)
        try:
            return [f for f in lyr]
        finally:
            lyr.SetAttributeFilter(None)

    # -- profiles ----------------------------------------------------------------------------
    def save_profile(self, p: Profile) -> None:
        with self._tx() as ds:
            line = ogr.Geometry(ogr.wkbLineString)
            for x, y in np.asarray(p.xy, dtype=float):
                line.AddPoint_2D(float(x), float(y))
            lyr = ds.GetLayerByName("profiles")
            self._delete_where(lyr, f"id = {_q(p.id)}")
            f = ogr.Feature(lyr.GetLayerDefn())
            f["id"], f["name"], f["metadata"] = p.id, p.name, _dumps(p.metadata)
            f.SetGeometry(line)
            lyr.CreateFeature(f)

    def _profile_from(self, f) -> Profile:
        g = f.GetGeometryRef()
        xy = np.array([(g.GetX(i), g.GetY(i)) for i in range(g.GetPointCount())], dtype=float)
        return Profile(_text(f, "id"), _text(f, "name"), xy.reshape(-1, 2), self.crs_authid,
                       json.loads(_text(f, "metadata") or "{}"))

    def profiles(self) -> list[Profile]:
        with self._ds() as ds:
            out = [self._profile_from(f) for f in ds.GetLayerByName("profiles")]
        return sorted(out, key=lambda p: (p.name, p.id))

    def profile(self, profile_id: str) -> Profile:
        with self._ds() as ds:
            rows = self._select(ds.GetLayerByName("profiles"), f"id = {_q(profile_id)}")
            if not rows:
                raise KeyError(profile_id)
            return self._profile_from(rows[0])

    # -- station sets ------------------------------------------------------------------------
    def save_station_set(self, s: StationSet) -> None:
        xyz = np.asarray(s.xyz, dtype=float)
        with self._tx() as ds:
            sets, pts = ds.GetLayerByName("station_sets"), ds.GetLayerByName("stations")
            self._delete_where(sets, f"id = {_q(s.id)}")
            self._delete_where(pts, f"set_id = {_q(s.id)}")
            f = ogr.Feature(sets.GetLayerDefn())
            f["id"], f["profile_id"], f["name"], f["method"] = s.id, s.profile_id, s.name, s.method
            f["metre0"], f["warnings"] = float(s.metre0), _dumps(list(s.warnings))
            sets.CreateFeature(f)
            for i in range(len(xyz)):
                f = ogr.Feature(pts.GetLayerDefn())
                f["set_id"], f["profile_id"], f["set_name"], f["method"] = (
                    s.id, s.profile_id, s.name, s.method)
                f["number"], f["seq"] = int(s.numbers[i]), i
                for key, arr in (("chainage", s.chainage), ("offset", s.offset)):
                    v = float(arr[i])
                    if not math.isnan(v):  # SQLite stores NaN as NULL; read back as NaN
                        f[key] = v
                g = ogr.Geometry(ogr.wkbPoint25D)
                g.AddPoint(float(xyz[i, 0]), float(xyz[i, 1]), float(xyz[i, 2]))
                f.SetGeometry(g)
                pts.CreateFeature(f)

    def station_sets(self, profile_id: str) -> list[StationSet]:
        out = []
        with self._ds() as ds:
            pts = ds.GetLayerByName("stations")
            rows = self._select(ds.GetLayerByName("station_sets"),
                                f"profile_id = {_q(profile_id)}")
            for r in sorted(rows, key=lambda r: (_text(r, "name"), _text(r, "id"))):
                sid = _text(r, "id")
                feats = sorted(self._select(pts, f"set_id = {_q(sid)}"),
                               key=lambda f: f.GetFieldAsInteger64("seq"))
                xyz = np.empty((len(feats), 3))
                for i, f in enumerate(feats):
                    g = f.GetGeometryRef()
                    xyz[i] = g.GetX(), g.GetY(), g.GetZ()
                out.append(StationSet(
                    sid, _text(r, "profile_id"), _text(r, "name"), _text(r, "method"),
                    np.array([f.GetFieldAsInteger64("number") for f in feats], dtype=int), xyz,
                    np.array([_real(f, "chainage") for f in feats], dtype=float),
                    np.array([_real(f, "offset") for f in feats], dtype=float),
                    _real(r, "metre0", 0.0), json.loads(_text(r, "warnings") or "[]")))
        return out

    # -- datasets ----------------------------------------------------------------------------
    def save_dataset(self, d: Dataset) -> None:
        with self._tx() as ds:
            lyr = ds.GetLayerByName("datasets")
            old = self._select(lyr, f"id = {_q(d.id)}")
            if old:
                seq = old[0].GetFieldAsInteger64("seq")
            else:
                seq = 1 + max((f.GetFieldAsInteger64("seq") for f in self._select(lyr)),
                              default=0)
            self._delete_where(lyr, f"id = {_q(d.id)}")
            f = ogr.Feature(lyr.GetLayerDefn())
            for key in ("id", "profile_id", "station_set_id", "kind", "source_path", "source_sha1",
                        "reader", "quantity", "unit", "name"):
                f[key] = getattr(d, key)
            f["source_mtime"] = float(d.source_mtime)
            f["version"] = int(d.version)
            f["reader_options"], f["provenance"] = _dumps(d.reader_options), _dumps(d.provenance)
            if d.parent_id is not None:
                f["parent_id"] = d.parent_id
            f["seq"] = seq
            lyr.CreateFeature(f)

    def datasets(self, profile_id: str) -> list[Dataset]:
        with self._ds() as ds:
            rows = self._select(ds.GetLayerByName("datasets"), f"profile_id = {_q(profile_id)}")
            rows.sort(key=lambda f: f.GetFieldAsInteger64("seq"))
            return [Dataset(
                _text(f, "id"), _text(f, "profile_id"), _text(f, "station_set_id"),
                _text(f, "kind"), _text(f, "source_path"), _real(f, "source_mtime", 0.0),
                _text(f, "source_sha1"), _text(f, "reader"),
                json.loads(_text(f, "reader_options") or "{}"),
                json.loads(_text(f, "provenance") or "{}"),
                f.GetFieldAsInteger("version"),
                None if f.IsFieldNull("parent_id") else f.GetFieldAsString("parent_id"),
                _text(f, "quantity"), _text(f, "unit"), _text(f, "name")) for f in rows]

    def delete_dataset(self, dataset_id: str) -> None:
        with self._tx() as ds:
            self._delete_where(ds.GetLayerByName("datasets"), f"id = {_q(dataset_id)}")
