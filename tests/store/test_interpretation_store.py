"""Interpretation in the workbench GeoPackage: versions, features, pieces, derived layers."""
import numpy as np
import pytest
from osgeo import ogr

from geophysics_workbench.core.chainage import Chainage
from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id
from geophysics_workbench.store.gpkg_store import ProjectStore

BENT = Chainage(np.array([[0.0, 0.0], [50.0, 0.0], [50.0, 50.0]]))


@pytest.fixture
def store(tmp_path):
    st = ProjectStore.create(tmp_path / "wb.gpkg", "EPSG:25832")
    st.ensure_interpretation()
    return st


def _add(st, kind="polygon", verts=((40, 0), (60, 0), (60, -5), (40, -5)), name="A"):
    v = st.current_version()
    f = InterpFeature(new_id(), v.id, type="anomaly", name=name)
    st.save_feature(f)
    p = InterpPiece(new_id(), v.id, f.id, "prof", kind, list(verts))
    st.save_piece(p)
    return f, p


def test_old_store_reads_empty_then_creates(tmp_path):
    st = ProjectStore.create(tmp_path / "old.gpkg", "EPSG:25832")
    assert not st.has_interpretation()
    assert ProjectStore.open(st.path).path == st.path
    st.ensure_interpretation()
    assert st.has_interpretation()
    assert st.current_version().name == "Current" and not st.current_version().frozen
    assert st.pieces(st.current_version().id) == []
    st.ensure_interpretation()                                  # idempotent
    assert len(st.versions()) == 1


def test_save_and_read_piece_roundtrip(store):
    f, p = _add(store)
    vid = store.current_version().id
    [got] = store.pieces(vid, "prof")
    assert got.feature_id == f.id and got.kind == "polygon"
    assert got.vertices[0] == got.vertices[-1] and len(got.vertices) == 5
    [gf] = store.features(vid)
    assert (gf.type, gf.name, gf.confidence) == ("anomaly", "A", "probable")
    assert store.pieces(vid, "other") == []


def test_frozen_version_rejects_writes(store):
    f, p = _add(store)
    frozen = store.freeze_current("Report 1")
    [ff] = store.features(frozen.id)
    with pytest.raises(PermissionError):
        store.save_feature(ff)
    [fp] = store.pieces(frozen.id)
    with pytest.raises(PermissionError):
        store.save_piece(fp)
    with pytest.raises(PermissionError):
        store.delete_piece(fp.id)


def test_freeze_is_a_deep_copy(store):
    f, p = _add(store)
    frozen = store.freeze_current("Report 1")
    before = ([(x.name, x.type) for x in store.features(frozen.id)],
              [x.vertices for x in store.pieces(frozen.id)])
    f.name = "Z"
    store.save_feature(f)
    p.vertices = [(0, 0), (5, 0), (5, -1)]
    store.save_piece(p)
    _add(store, name="B")
    store.delete_piece(p.id)
    after = ([(x.name, x.type) for x in store.features(frozen.id)],
             [x.vertices for x in store.pieces(frozen.id)])
    assert after == before
    store.restore_from(frozen.id)
    cur = store.current_version().id
    assert [x.name for x in store.features(cur)] == ["A"]
    assert {x.id for x in store.pieces(cur)}.isdisjoint({x.id for x in store.pieces(frozen.id)})


def test_delete_last_piece_deletes_feature(store):
    f, p = _add(store)
    store.delete_piece(p.id)
    assert store.features(store.current_version().id) == []


def _add_column(st, name):
    ds = ogr.Open(str(st.path), 1)
    ds.GetLayerByName("interp_features").CreateField(ogr.FieldDefn(name, ogr.OFTString))
    ds = None


def test_custom_field_survives_freeze_restore_rebuild(store):
    _add_column(store, "drill_target")
    f, p = _add(store)
    vid = store.current_version().id
    [f] = store.features(vid)
    f.extra["drill_target"] = "yes"
    store.save_feature(f)
    frozen = store.freeze_current("R1")
    assert store.features(frozen.id)[0].extra["drill_target"] == "yes"
    store.restore_from(frozen.id)
    assert store.features(vid)[0].extra["drill_target"] == "yes"
    store.rebuild_derived(vid, {"prof": BENT})
    ds = ogr.Open(str(store.path))
    [row] = list(ds.GetLayerByName("interp_polygons_3d"))
    assert row["drill_target"] == "yes" and row["name"] == "A"


def test_rebuild_derived_geometry(store):
    _add(store)
    _add(store, kind="line", verts=((10, 1), (30, 2)), name="L")
    _add(store, kind="point", verts=((5, 0),), name="P")
    vid = store.current_version().id
    store.rebuild_derived(vid, {"prof": BENT})
    store.rebuild_derived(vid, {"prof": BENT})                  # replaces, never appends
    ds = ogr.Open(str(store.path))
    poly = ds.GetLayerByName("interp_polygons_3d")
    assert poly.GetFeatureCount() == 1
    feat = poly.GetNextFeature()
    ring = feat.GetGeometryRef().GetGeometryRef(0)
    pts = {(round(ring.GetX(i), 6), round(ring.GetY(i), 6), round(ring.GetZ(i), 6))
           for i in range(ring.GetPointCount())}
    assert (50.0, 0.0, 0.0) in pts and (50.0, 0.0, -5.0) in pts
    assert ds.GetLayerByName("interp_lines_3d").GetFeatureCount() == 1
    assert ds.GetLayerByName("interp_points_3d").GetFeatureCount() == 1
    assert ds.GetLayerByName("interp_footprints").GetFeatureCount() == 2   # line + polygon


def test_restore_from_rejects_current_or_unknown(store):
    f, p = _add(store)
    cur = store.current_version().id
    for bad in (cur, "no-such-version"):
        with pytest.raises(ValueError):
            store.restore_from(bad)
    assert len(store.pieces(cur)) == 1
