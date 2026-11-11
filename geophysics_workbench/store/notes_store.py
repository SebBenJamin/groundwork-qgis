"""Field-note tables of the workbench GeoPackage (mixed into ``ProjectStore``).

Created on first use (``ensure_field_notes``), so older stores keep opening. ``field_notes``
holds the notes (chainage is the truth); ``field_notes_points`` (a point note at its
chainage, a stretch at its middle) and ``field_notes_lines`` (stretches along the profile)
are derived for the map and rebuilt from the notes, never edited."""
from __future__ import annotations

from osgeo import ogr

from ..core.field_notes import FieldNote, note_range
from .interp_store import now

_S, _I, _R = ogr.OFTString, ogr.OFTInteger, ogr.OFTReal
NOTE_FIELDS = [("id", _S), ("profile_id", _S), ("s_from", _R), ("s_to", _R), ("text", _S),
               ("category", _S), ("shown", _I), ("stations", _S), ("author", _S),
               ("created", _S), ("modified", _S)]
MAP_FIELDS = [("note_id", _S), ("profile_id", _S), ("text", _S), ("category", _S),
              ("shown", _I), ("stations", _S)]
MAP_TABLES = {"field_notes_points": ogr.wkbPoint, "field_notes_lines": ogr.wkbLineString}


def _q(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


class FieldNotesMixin:
    def has_field_notes(self) -> bool:
        with self._ds() as ds:
            return ds.GetLayerByName("field_notes") is not None

    def _note_tables_exist(self) -> bool:
        with self._ds() as ds:
            return all(ds.GetLayerByName(n) is not None for n in ("field_notes", *MAP_TABLES))

    def ensure_field_notes(self) -> None:
        """Create the note tables when missing. Opens the file for writing only then: every
        extra write-open under QGIS's loaded layers is a chance to upset them (B3)."""
        from .gpkg_store import _make_layer, _srs
        if self._note_tables_exist():
            return
        with self._ds(write=True) as ds:
            if ds.GetLayerByName("field_notes") is None:
                _make_layer(ds, "field_notes", NOTE_FIELDS)
            srs = _srs(self.crs_authid)
            for name, geom in MAP_TABLES.items():
                if ds.GetLayerByName(name) is None:
                    _make_layer(ds, name, MAP_FIELDS, geom, srs)

    @staticmethod
    def _note_from(f) -> FieldNote:
        s_to = f["s_to"]
        return FieldNote(f["id"], f["profile_id"] or "", float(f["s_from"]),
                         None if s_to is None else float(s_to), f["text"] or "",
                         f["category"] or "", bool(f["shown"]), f["stations"] or "",
                         f["author"] or "", f["created"] or "", f["modified"] or "")

    def field_notes(self, profile_id: str | None = None) -> list[FieldNote]:
        if not self.has_field_notes():
            return []
        where = None if profile_id is None else f"profile_id = {_q(profile_id)}"
        with self._ds() as ds:
            notes = [self._note_from(f)
                     for f in self._select(ds.GetLayerByName("field_notes"), where)]
        return sorted(notes, key=lambda n: (n.profile_id, note_range(n)))

    def save_field_note(self, note: FieldNote) -> None:
        self.ensure_field_notes()
        note.created = note.created or now()
        note.modified = now()
        with self._tx() as ds:
            lyr = ds.GetLayerByName("field_notes")
            self._delete_where(lyr, f"id = {_q(note.id)}")
            f = ogr.Feature(lyr.GetLayerDefn())
            for name, _ in NOTE_FIELDS:
                value = getattr(note, name)
                if name == "shown":
                    value = int(bool(value))
                if value is not None:
                    f[name] = value
            lyr.CreateFeature(f)

    def delete_field_note(self, note_id: str) -> None:
        if not self.has_field_notes():
            return
        with self._tx() as ds:
            self._delete_where(ds.GetLayerByName("field_notes"), f"id = {_q(note_id)}")

    def rebuild_field_note_geometry(self, chainage_by_profile: dict) -> None:
        """Rebuild the map tables from the notes (profiles without a chainage are left out)."""
        from ..core.interpretation import _densified
        notes = self.field_notes()
        self.ensure_field_notes()
        with self._ds(write=True) as ds:
            ds.StartTransaction()
            try:
                for name in MAP_TABLES:
                    ds.ExecuteSQL(f"DELETE FROM {name}")
                for n in notes:
                    ch = chainage_by_profile.get(n.profile_id)
                    if ch is None:
                        continue
                    lo, hi = note_range(n)
                    x, y = ch.to_xy(float((lo + hi) / 2))
                    point = ogr.Geometry(ogr.wkbPoint)
                    point.AddPoint_2D(float(x), float(y))
                    self._map_row(ds.GetLayerByName("field_notes_points"), n, point)
                    if n.s_to is not None and hi > lo:
                        line = ogr.Geometry(ogr.wkbLineString)
                        for s, _z in _densified([(lo, 0.0), (hi, 0.0)], ch):
                            px, py = ch.to_xy(float(s))
                            line.AddPoint_2D(float(px), float(py))
                        self._map_row(ds.GetLayerByName("field_notes_lines"), n, line)
            except BaseException:
                ds.RollbackTransaction()
                raise
            ds.CommitTransaction()

    @staticmethod
    def _map_row(lyr, n: FieldNote, geom) -> None:
        f = ogr.Feature(lyr.GetLayerDefn())
        f["note_id"], f["profile_id"], f["text"] = n.id, n.profile_id, n.text
        f["category"], f["shown"], f["stations"] = n.category, int(n.shown), n.stations
        f.SetGeometry(geom)
        lyr.CreateFeature(f)
