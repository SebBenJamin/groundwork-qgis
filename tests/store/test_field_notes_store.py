"""Field notes in the workbench GeoPackage, with derived map tables."""
import numpy as np
import pytest

from geophysics_workbench.core.chainage import Chainage
from geophysics_workbench.core.field_notes import FieldNote

BENT = Chainage(np.array([[0.0, 0.0], [50.0, 0.0], [50.0, 50.0]]))


@pytest.fixture
def store(tmp_path):
    from geophysics_workbench.store.gpkg_store import ProjectStore
    st = ProjectStore.create(tmp_path / "wb.gpkg", "EPSG:25832")
    st.ensure_field_notes()
    return st


def test_round_trip_point_and_stretch(store):
    store.save_field_note(FieldNote("n1", "prof", 12.0, None, "fence at the road",
                                    category="obstacle"))
    store.save_field_note(FieldNote("n2", "prof", 40.0, 60.0, "electrodes off\nfarmer",
                                    stations="23–28", shown=False))
    got = {n.id: n for n in store.field_notes("prof")}
    assert got["n1"].s_to is None and got["n1"].category == "obstacle"
    assert got["n2"].text == "electrodes off\nfarmer" and got["n2"].shown is False
    assert got["n2"].stations == "23–28" and got["n2"].created and got["n2"].modified
    store.delete_field_note("n1")
    assert [n.id for n in store.field_notes()] == ["n2"]


def test_geometry_rebuilt_on_bent_profile(store):
    from osgeo import ogr
    store.save_field_note(FieldNote("p", "prof", 25.0, None, "fence"))
    store.save_field_note(FieldNote("s", "prof", 40.0, 70.0, "wet ground"))
    store.rebuild_field_note_geometry({"prof": BENT})
    ds = ogr.Open(str(store.path))
    pts = {f["note_id"]: f.GetGeometryRef().Clone() for f in ds.GetLayerByName("field_notes_points")}
    lines = {f["note_id"]: f.GetGeometryRef().Clone() for f in ds.GetLayerByName("field_notes_lines")}
    assert (pts["p"].GetX(), pts["p"].GetY()) == pytest.approx((25.0, 0.0))
    assert (pts["s"].GetX(), pts["s"].GetY()) == pytest.approx((50.0, 5.0))   # middle at 55 m
    assert "p" not in lines
    xs = [lines["s"].GetPoint_2D(i) for i in range(lines["s"].GetPointCount())]
    assert xs[0] == pytest.approx((40.0, 0.0)) and xs[-1] == pytest.approx((50.0, 20.0))
    assert (50.0, 0.0) in [tuple(round(v, 6) for v in p) for p in xs]       # follows the bend


def test_store_without_notes_opens_and_lists_none(tmp_path):
    from geophysics_workbench.store.gpkg_store import ProjectStore
    st = ProjectStore.create(tmp_path / "old.gpkg", "EPSG:25832")
    assert st.field_notes() == [] and not st.has_field_notes()
