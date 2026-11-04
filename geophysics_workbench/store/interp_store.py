"""Interpretation tables of the workbench GeoPackage (mixed into ``ProjectStore``).

Tables are created on first use (``ensure_interpretation``), so stores written before M3 keep
opening (no schema bump). ``interp_versions`` holds exactly one unfrozen "Current" version;
frozen versions are read-only copies. ``interp_features`` may carry fields the user added in
QGIS; they are read into ``InterpFeature.extra`` and carried through copies and derived layers.
The derived tables (3D pieces, footprints) are rebuilt from the pieces, never edited.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from osgeo import ogr

from ..core.interpretation import (InterpFeature, InterpPiece, InterpVersion, footprint, new_id,
                                   normalise, to_3d)

_S, _I = ogr.OFTString, ogr.OFTInteger
VERSION_FIELDS = [("id", _S), ("name", _S), ("frozen", _I), ("created", _S), ("note", _S)]
FEATURE_FIELDS = [("id", _S), ("version_id", _S), ("type", _S), ("letter", _S),
                  ("confidence", _S), ("note", _S), ("author", _S), ("created", _S),
                  ("modified", _S)]
PIECE_FIELDS = [("id", _S), ("version_id", _S), ("feature_id", _S), ("profile_id", _S),
                ("kind", _S), ("axis", _S), ("vertices", _S), ("based_on_dataset", _S),
                ("based_on_version", _S), ("created", _S), ("modified", _S)]
DERIVED = {"interp_lines_3d": ogr.wkbLineString25D, "interp_polygons_3d": ogr.wkbPolygon25D,
           "interp_points_3d": ogr.wkbPoint25D, "interp_footprints": ogr.wkbLineString}
DERIVED_KEYS = [("piece_id", _S), ("feature_id", _S), ("profile_id", _S), ("version_id", _S)]
_BASE = {n for n, _ in FEATURE_FIELDS}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _q(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


class InterpStoreMixin:
    # -- schema ------------------------------------------------------------------------------
    def has_interpretation(self) -> bool:
        with self._ds() as ds:
            return ds.GetLayerByName("interp_versions") is not None

    def ensure_interpretation(self) -> None:
        from .gpkg_store import _make_layer, _srs
        with self._ds(write=True) as ds:
            if ds.GetLayerByName("interp_versions") is None:
                v = _make_layer(ds, "interp_versions", VERSION_FIELDS)
                f = ogr.Feature(v.GetLayerDefn())
                f["id"], f["name"], f["frozen"], f["created"] = new_id(), "Current", 0, now()
                v.CreateFeature(f)
            for name, fields in (("interp_features", FEATURE_FIELDS),
                                 ("interp_pieces", PIECE_FIELDS)):
                if ds.GetLayerByName(name) is None:
                    _make_layer(ds, name, fields)
            srs = _srs(self.crs_authid)
            for name, geom in DERIVED.items():
                if ds.GetLayerByName(name) is None:
                    _make_layer(ds, name, DERIVED_KEYS + FEATURE_FIELDS[2:], geom, srs)

    # -- versions ----------------------------------------------------------------------------
    def versions(self) -> list[InterpVersion]:
        with self._ds() as ds:
            out = [InterpVersion(f["id"], f["name"] or "", bool(f["frozen"]), f["created"] or "",
                                 f["note"] or "") for f in ds.GetLayerByName("interp_versions")]
        return sorted(out, key=lambda v: (v.frozen, v.created))

    def current_version(self) -> InterpVersion:
        return next(v for v in self.versions() if not v.frozen)

    def _writable(self, version_id: str) -> None:
        v = next((x for x in self.versions() if x.id == version_id), None)
        if v is None or v.frozen:
            raise PermissionError(f"interpretation version {version_id} is frozen or unknown")

    # -- features ----------------------------------------------------------------------------
    @staticmethod
    def _feature_from(f) -> InterpFeature:
        defn = f.GetDefnRef()
        names = [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
        base = {n: (f[n] if f[n] is not None else "") for n in names if n in _BASE}
        extra = {n: f[n] for n in names if n not in _BASE}
        return InterpFeature(**base, extra=extra)

    def features(self, version_id: str) -> list[InterpFeature]:
        with self._ds() as ds:
            return [self._feature_from(f) for f in
                    self._select(ds.GetLayerByName("interp_features"),
                                 f"version_id = {_q(version_id)}")]

    def _write_feature(self, lyr, feat: InterpFeature) -> None:
        self._delete_where(lyr, f"id = {_q(feat.id)}")
        f = ogr.Feature(lyr.GetLayerDefn())
        for n, _ in FEATURE_FIELDS:
            f[n] = getattr(feat, n) or ""
        defn = lyr.GetLayerDefn()
        for k, v in feat.extra.items():
            if defn.GetFieldIndex(k) >= 0 and v is not None:
                f[k] = v
        lyr.CreateFeature(f)

    def save_feature(self, feat: InterpFeature) -> None:
        self._writable(feat.version_id)
        feat.created = feat.created or now()
        feat.modified = now()
        with self._tx() as ds:
            self._write_feature(ds.GetLayerByName("interp_features"), feat)

    def delete_feature(self, feature_id: str) -> None:
        with self._tx() as ds:
            fl = ds.GetLayerByName("interp_features")
            rows = self._select(fl, f"id = {_q(feature_id)}")
            if not rows:
                return
            self._writable(rows[0]["version_id"])
            self._delete_where(fl, f"id = {_q(feature_id)}")
            self._delete_where(ds.GetLayerByName("interp_pieces"),
                               f"feature_id = {_q(feature_id)}")

    # -- pieces ------------------------------------------------------------------------------
    @staticmethod
    def _piece_from(f) -> InterpPiece:
        kw = {n: (f[n] or "") for n, _ in PIECE_FIELDS if n != "vertices"}
        return InterpPiece(**kw, vertices=[tuple(v) for v in json.loads(f["vertices"] or "[]")])

    def pieces(self, version_id: str, profile_id: str | None = None) -> list[InterpPiece]:
        where = f"version_id = {_q(version_id)}"
        if profile_id is not None:
            where += f" AND profile_id = {_q(profile_id)}"
        with self._ds() as ds:
            return [self._piece_from(f) for f in
                    self._select(ds.GetLayerByName("interp_pieces"), where)]

    def _write_piece(self, lyr, p: InterpPiece) -> None:
        self._delete_where(lyr, f"id = {_q(p.id)}")
        f = ogr.Feature(lyr.GetLayerDefn())
        for n, _ in PIECE_FIELDS:
            f[n] = (json.dumps([[float(s), float(z)] for s, z in p.vertices])
                    if n == "vertices" else (getattr(p, n) or ""))
        lyr.CreateFeature(f)

    def save_piece(self, piece: InterpPiece) -> InterpPiece:
        self._writable(piece.version_id)
        p = normalise(piece)
        p.created = p.created or now()
        p.modified = now()
        with self._tx() as ds:
            self._write_piece(ds.GetLayerByName("interp_pieces"), p)
        piece.vertices = p.vertices
        return p

    def delete_piece(self, piece_id: str) -> None:
        with self._tx() as ds:
            pl = ds.GetLayerByName("interp_pieces")
            rows = self._select(pl, f"id = {_q(piece_id)}")
            if not rows:
                return
            self._writable(rows[0]["version_id"])
            fid = rows[0]["feature_id"]
            self._delete_where(pl, f"id = {_q(piece_id)}")
            if not self._select(pl, f"feature_id = {_q(fid)}"):
                self._delete_where(ds.GetLayerByName("interp_features"), f"id = {_q(fid)}")

    # -- copying versions --------------------------------------------------------------------
    def _copy_into(self, ds, src_id: str, dst_id: str) -> None:
        fl, pl = ds.GetLayerByName("interp_features"), ds.GetLayerByName("interp_pieces")
        ids = {}
        for row in self._select(fl, f"version_id = {_q(src_id)}"):
            feat = self._feature_from(row)
            ids[feat.id] = new_id()
            feat.id, feat.version_id = ids[feat.id], dst_id
            self._write_feature(fl, feat)
        for row in self._select(pl, f"version_id = {_q(src_id)}"):
            p = self._piece_from(row)
            p.id, p.version_id, p.feature_id = new_id(), dst_id, ids.get(p.feature_id, "")
            self._write_piece(pl, p)

    def freeze_current(self, name: str, note: str = "") -> InterpVersion:
        cur = self.current_version()
        v = InterpVersion(new_id(), name, True, now(), note)
        with self._tx() as ds:
            vl = ds.GetLayerByName("interp_versions")
            f = ogr.Feature(vl.GetLayerDefn())
            f["id"], f["name"], f["frozen"], f["created"], f["note"] = (v.id, v.name, 1,
                                                                      v.created, v.note)
            vl.CreateFeature(f)
            self._copy_into(ds, cur.id, v.id)
        return v

    def restore_from(self, version_id: str) -> None:
        cur = self.current_version()
        source = next((v for v in self.versions() if v.id == version_id), None)
        if source is None or not source.frozen:
            raise ValueError(f"can only start from a frozen version, not {version_id!r}")
        with self._tx() as ds:
            for name in ("interp_features", "interp_pieces"):
                self._delete_where(ds.GetLayerByName(name), f"version_id = {_q(cur.id)}")
            self._copy_into(ds, version_id, cur.id)

    def drop_orphan_pieces(self, version_id: str) -> int:
        """Delete pieces whose feature no longer exists (e.g. deleted in QGIS's attribute
        table); returns how many were removed."""
        self._writable(version_id)
        feats = {f.id for f in self.features(version_id)}
        gone = [p.id for p in self.pieces(version_id) if p.feature_id not in feats]
        if gone:
            with self._tx() as ds:
                pl = ds.GetLayerByName("interp_pieces")
                for pid in gone:
                    self._delete_where(pl, f"id = {_q(pid)}")
        return len(gone)

    def used_types(self) -> list[str]:
        with self._ds() as ds:
            return sorted({f["type"] for f in ds.GetLayerByName("interp_features")
                           if f["type"]}, key=str.lower)

    # -- derived layers ----------------------------------------------------------------------
    def rebuild_derived(self, version_id: str, chainage_by_profile: dict) -> None:
        feats = {f.id: f for f in self.features(version_id)}
        pieces = self.pieces(version_id)
        with self._ds(write=True) as ds:
            src = ds.GetLayerByName("interp_features").GetLayerDefn()
            extra = [src.GetFieldDefn(i) for i in range(src.GetFieldCount())
                     if src.GetFieldDefn(i).GetName() not in _BASE]
            for name in DERIVED:                               # keep columns in step
                lyr = ds.GetLayerByName(name)
                for fd in extra:
                    if lyr.GetLayerDefn().GetFieldIndex(fd.GetName()) < 0:
                        lyr.CreateField(ogr.FieldDefn(fd.GetName(), fd.GetType()))
            ds.StartTransaction()
            try:
                for name in DERIVED:
                    ds.ExecuteSQL(f"DELETE FROM {name}")
                for p in pieces:
                    ch = chainage_by_profile.get(p.profile_id)
                    if ch is None:
                        continue
                    target = {"line": "interp_lines_3d", "polygon": "interp_polygons_3d",
                              "point": "interp_points_3d"}[p.kind]
                    self._derived_row(ds.GetLayerByName(target), p, feats.get(p.feature_id),
                                      _geom3d(p, ch))
                    if p.kind != "point":
                        line = ogr.Geometry(ogr.wkbLineString)
                        for x, y in footprint(p, ch):
                            line.AddPoint_2D(x, y)
                        self._derived_row(ds.GetLayerByName("interp_footprints"), p,
                                          feats.get(p.feature_id), line)
            except BaseException:
                ds.RollbackTransaction()
                raise
            ds.CommitTransaction()

    @staticmethod
    def _derived_row(lyr, p: InterpPiece, feat: InterpFeature | None, geom) -> None:
        f = ogr.Feature(lyr.GetLayerDefn())
        f["piece_id"], f["feature_id"] = p.id, p.feature_id
        f["profile_id"], f["version_id"] = p.profile_id, p.version_id
        if feat is not None:
            for n, _ in FEATURE_FIELDS[2:]:
                f[n] = getattr(feat, n) or ""
            for k, v in feat.extra.items():
                if lyr.GetLayerDefn().GetFieldIndex(k) >= 0 and v is not None:
                    f[k] = v
        f.SetGeometry(geom)
        lyr.CreateFeature(f)


def _geom3d(p: InterpPiece, chainage):
    pts = to_3d(p, chainage)
    if p.kind == "point":
        g = ogr.Geometry(ogr.wkbPoint25D)
        g.AddPoint(*pts[0])
        return g
    line = ogr.Geometry(ogr.wkbLinearRing if p.kind == "polygon" else ogr.wkbLineString25D)
    for x, y, z in pts:
        line.AddPoint(x, y, z)
    if p.kind == "line":
        return line
    poly = ogr.Geometry(ogr.wkbPolygon25D)
    poly.AddGeometry(line)
    return poly
