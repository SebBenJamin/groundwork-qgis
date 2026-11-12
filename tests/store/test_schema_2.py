"""Round 2, F6: interpretation features have a name instead of a letter. Stores are schema 2;
a 0.7 store (schema 1, ``letter`` columns) is updated once when opened."""
import os
import stat

import numpy as np
import pytest

from geophysics_workbench.core.chainage import Chainage
from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id

TABLES = ("interp_features", "interp_lines_3d", "interp_polygons_3d", "interp_points_3d",
          "interp_footprints")


def _columns(path, table):
    from osgeo import ogr
    ds = ogr.Open(str(path))
    try:
        defn = ds.GetLayerByName(table).GetLayerDefn()
        return [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
    finally:
        ds = None


def _meta(path):
    from osgeo import ogr
    ds = ogr.Open(str(path))
    try:
        return {f["key"]: f["value"] for f in ds.GetLayerByName("wb_meta")}
    finally:
        ds = None


def _make_schema_1(path, names=("A", "B"), user_name=None):
    """A store as 0.7 wrote it: ``letter`` columns and schema_version 1. ``user_name``:
    values of a user-added ``name`` field (a field the user created in QGIS)."""
    from osgeo import ogr

    from geophysics_workbench.store.gpkg_store import ProjectStore
    st = ProjectStore.create(path, "EPSG:25832")
    st.ensure_interpretation()
    v = st.current_version()
    ids = []
    for n in names:
        f = InterpFeature(new_id(), v.id, type="clay", name=n)
        st.save_feature(f)
        st.save_piece(InterpPiece(new_id(), v.id, f.id, "prof", "line", [(0, -1), (10, -2)]))
        ids.append(f.id)
    st.rebuild_derived(v.id, {"prof": Chainage(np.array([[0.0, 0.0], [50.0, 0.0]]))})
    st = None
    ds = ogr.Open(str(path), 1)
    for table in TABLES:
        lyr = ds.GetLayerByName(table)
        defn = lyr.GetLayerDefn()
        lyr.AlterFieldDefn(defn.GetFieldIndex("name"), ogr.FieldDefn("letter", ogr.OFTString),
                           ogr.ALTER_NAME_FLAG)
    if user_name is not None:
        lyr = ds.GetLayerByName("interp_features")
        lyr.CreateField(ogr.FieldDefn("name", ogr.OFTString))
        for f in lyr:
            f["name"] = user_name.get(f["letter"], "")
            lyr.SetFeature(f)
    ds.ExecuteSQL("UPDATE wb_meta SET value = '1' WHERE key = 'schema_version'")
    ds = None
    return ids


def test_new_store_is_schema_2(tmp_path):
    from geophysics_workbench.store.gpkg_store import SCHEMA_VERSION, ProjectStore
    ProjectStore.create(tmp_path / "wb.gpkg", "EPSG:25832")
    assert SCHEMA_VERSION == 3 and _meta(tmp_path / "wb.gpkg")["schema_version"] == "3"


def test_migrate_1_to_2(tmp_path):
    from geophysics_workbench.store.gpkg_store import ProjectStore
    path = tmp_path / "old.gpkg"
    _make_schema_1(path)
    assert "letter" in _columns(path, "interp_features")
    st = ProjectStore.open(path)
    assert sorted(f.name for f in st.features(st.current_version().id)) == ["A", "B"]
    assert _meta(path)["schema_version"] == "3"          # and on through 2 -> 3
    for table in TABLES:
        cols = _columns(path, table)
        assert "name" in cols and "letter" not in cols, table


def test_migrate_with_user_name_field(tmp_path):
    """Review Focus 2: a user field ``name`` already there - nothing is lost."""
    from geophysics_workbench.store.gpkg_store import ProjectStore
    path = tmp_path / "old.gpkg"
    _make_schema_1(path, user_name={"A": "x"})
    st = ProjectStore.open(path)
    feats = {f.extra.get("letter"): f for f in st.features(st.current_version().id)}
    assert feats["A"].name == "x" and feats["B"].name == "B"
    assert set(feats) == {"A", "B"}


def test_read_only_store_message(tmp_path):
    from geophysics_workbench.store.gpkg_store import ProjectStore
    path = tmp_path / "old.gpkg"
    _make_schema_1(path)
    os.chmod(path, stat.S_IREAD)
    try:
        with pytest.raises(ValueError, match="one-time update"):
            ProjectStore.open(path)
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)


def test_twins_by_name():
    from geophysics_workbench.section.interp_render import twin_features
    frozen = [InterpFeature("f1", "v0", type="clay", name="Clay A")]
    current = [InterpFeature("c1", "v1", type="clay", name="Clay A"),
               InterpFeature("c2", "v1", type="clay", name="Clay B")]
    assert twin_features(frozen, current) == {"f1": "c1"}
