"""0.12: stations carry their point name (``name``, NULL where none). Stores are schema 4; a
0.9-0.11 store (schema 3) is updated once when opened."""
import os
import stat

import numpy as np
import pytest

from groundwork_geophysics.core.model import (Profile, attach_station_set,
                                              profile_from_positions)
from groundwork_geophysics.core.placement import Positions


def _meta(path):
    from osgeo import ogr
    ds = ogr.Open(str(path))
    try:
        return {f["key"]: f["value"] for f in ds.GetLayerByName("wb_meta")}
    finally:
        ds = None


def _columns(path, table):
    from osgeo import ogr
    ds = ogr.Open(str(path))
    try:
        defn = ds.GetLayerByName(table).GetLayerDefn()
        return [defn.GetFieldDefn(i).GetName() for i in range(defn.GetFieldCount())]
    finally:
        ds = None


def _profile():
    return Profile("p1", "Line 1", np.array([[0.0, 0.0], [100.0, 0.0]]), "EPSG:25832",
                   {"note": "kept"})


def _make_schema_3(path, monkeypatch):
    """A store as 0.11 wrote it: no ``name`` column on stations, schema_version 3."""
    from groundwork_geophysics.store import gpkg_store
    old_fields = [f for f in gpkg_store._STATION_FIELDS if f[0] != "name"]
    with monkeypatch.context() as m:
        m.setattr(gpkg_store, "SCHEMA_VERSION", 3)
        m.setattr(gpkg_store, "_STATION_FIELDS", old_fields)
        st = gpkg_store.ProjectStore.create(path, "EPSG:25832")
        p = _profile()
        st.save_profile(p)
        s = attach_station_set(p, "ERT", "ert", np.array([[0.0, 1.0, 50.0], [10.0, 0.0, 51.0],
                                                          [20.0, -1.0, 52.0]]),
                               inline=[0.0, 10.0, np.nan])
        s.id = "s1"
        st.save_station_set(s)
    assert _meta(path)["schema_version"] == "3"
    assert "name" not in _columns(path, "stations")
    return s


def test_new_store_is_schema_4(tmp_path):
    from groundwork_geophysics.store.gpkg_store import SCHEMA_VERSION, ProjectStore
    ProjectStore.create(tmp_path / "wb.gpkg", "EPSG:25832")
    assert SCHEMA_VERSION == 4 and _meta(tmp_path / "wb.gpkg")["schema_version"] == "4"
    assert "name" in _columns(tmp_path / "wb.gpkg", "stations")


def test_names_round_trip(tmp_path):
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    st = ProjectStore.create(tmp_path / "wb.gpkg", "EPSG:25832")
    p = _profile()
    st.save_profile(p)
    s = attach_station_set(p, "ERT", "ert", np.array([[0.0, 0.0], [10.0, 0.0], [25.0, 0.0]]),
                           names=["ERT03_01", "", "Base2"])
    st.save_station_set(s)
    [back] = st.station_sets(p.id)
    assert back.names == ["ERT03_01", "", "Base2"]


def test_station_set_names_default_and_length():
    p = _profile()
    s = attach_station_set(p, "ERT", "ert", np.array([[0.0, 0.0], [10.0, 0.0]]))
    assert s.names == ["", ""]
    with pytest.raises(ValueError):
        attach_station_set(p, "ERT", "ert", np.array([[0.0, 0.0], [10.0, 0.0]]), names=["a"])


def test_profile_from_positions_orders_names():
    xyz = np.array([[20.0, 0.0, 1.0], [0.0, 0.0, 1.0], [10.0, 0.0, 1.0]])
    _, s = profile_from_positions("L", "EPSG:25832",
                                  Positions(xyz, np.array([3, 1, 2]), names=["c", "a", "b"]))
    assert s.numbers.tolist() == [1, 2, 3] and s.names == ["a", "b", "c"]


def test_schema_3_store_is_migrated(tmp_path, monkeypatch):
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    path = tmp_path / "old.gpkg"
    s = _make_schema_3(path, monkeypatch)
    st = ProjectStore.open(path)
    assert _meta(path)["schema_version"] == "4"
    assert "name" in _columns(path, "stations")
    [back] = st.station_sets("p1")
    assert back.names == ["", "", ""]
    np.testing.assert_array_equal(back.numbers, s.numbers)
    np.testing.assert_allclose(back.xyz, s.xyz)
    np.testing.assert_allclose(back.chainage, s.chainage)
    np.testing.assert_array_equal(back.inline, [0.0, 10.0, np.nan])
    ProjectStore.open(path)                                  # a second open changes nothing
    assert _meta(path)["schema_version"] == "4"


def test_read_only_schema_3_store_says_why(tmp_path, monkeypatch):
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    path = tmp_path / "old.gpkg"
    _make_schema_3(path, monkeypatch)
    os.chmod(path, stat.S_IREAD)
    try:
        with pytest.raises(ValueError, match="one-time update for 0.12"):
            ProjectStore.open(path)
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    assert _meta(path)["schema_version"] == "3"


def test_a_migration_failing_part_way_leaves_the_file_as_it_was(tmp_path, monkeypatch):
    from osgeo import ogr

    from groundwork_geophysics.store.gpkg_store import ProjectStore
    path = tmp_path / "old.gpkg"
    s = _make_schema_3(path, monkeypatch)
    real = ogr.DataSource.ExecuteSQL
    seen = []

    def fail_on_the_version(ds, sql, *args, **kwargs):
        if sql.lstrip().upper().startswith("UPDATE WB_META"):
            defn = ds.GetLayerByName("stations").GetLayerDefn()
            seen.append(defn.GetFieldIndex("name") >= 0)
            raise RuntimeError("disk I/O error")
        return real(ds, sql, *args, **kwargs)

    monkeypatch.setattr(ogr.DataSource, "ExecuteSQL", fail_on_the_version)
    with pytest.raises(ValueError, match="one-time update for 0.12"):
        ProjectStore.open(path)
    monkeypatch.undo()
    assert seen == [True]
    assert _meta(path)["schema_version"] == "3"
    assert "name" not in _columns(path, "stations")
    st = ProjectStore.open(path)
    assert _meta(path)["schema_version"] == "4"
    [back] = st.station_sets("p1")
    np.testing.assert_allclose(back.xyz, s.xyz)


@pytest.fixture
def project(qgis_app):
    from qgis.core import QgsProject
    prj = QgsProject.instance()
    prj.clear()
    yield prj
    prj.removeAllMapLayers()
    prj.clear()


def test_open_project_layers_survive_migration(qgis_app, tmp_path, monkeypatch, project,
                                               fake_iface):
    """The stations layer is loaded from the 0.11 file before the plugin updates it."""
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from groundwork_geophysics import classFactory
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    from groundwork_geophysics.ui.project_actions import add_store_layers
    path = tmp_path / "old.gpkg"
    _make_schema_3(path, monkeypatch)
    old = ProjectStore(path, "EPSG:25832")
    layer = add_store_layers(old, project)["stations"]
    assert layer.isValid() and layer.fields().indexOf("name") < 0
    plug = classFactory(fake_iface)
    plug.initGui()
    try:
        plug.set_store(ProjectStore.open(path))
        assert _meta(path)["schema_version"] == "4"
        assert layer.isValid() and layer.fields().indexOf("name") >= 0
        assert layer.featureCount() == 3
    finally:
        plug.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
