"""0.9: stations carry their distance in the model file's own in-line metres (``inline``),
and a dataset may exist without a station set. Stores are schema 3; a 0.8 store (schema 2)
is updated once when opened."""
import os
import stat

import numpy as np
import pytest

from groundwork_geophysics.core.model import Dataset, Profile, attach_station_set


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


def _dataset(profile_id="p1", station_set_id="s1"):
    return Dataset("d1", profile_id, station_set_id, "ert_model", "model.xyz", 12.5, "abc",
                   "res2dinv", {"chainage_offset": 2.0}, {"by": "test"}, name="Model 1")


def _make_schema_2(path, monkeypatch):
    """A store as 0.8 wrote it: no ``inline`` column on stations, schema_version 2."""
    from groundwork_geophysics.store import gpkg_store
    old_fields = [f for f in gpkg_store._STATION_FIELDS if f[0] not in ("inline", "name")]
    with monkeypatch.context() as m:
        m.setattr(gpkg_store, "SCHEMA_VERSION", 2)
        m.setattr(gpkg_store, "_STATION_FIELDS", old_fields)
        st = gpkg_store.ProjectStore.create(path, "EPSG:25832")
        p = _profile()
        st.save_profile(p)
        s = attach_station_set(p, "ERT", "ert", np.array([[0.0, 1.0, 50.0], [10.0, 0.0, 51.0],
                                                          [20.0, -1.0, 52.0]]))
        s.id = "s1"
        st.save_station_set(s)
        st.save_dataset(_dataset())
    assert _meta(path)["schema_version"] == "2"
    assert "inline" not in _columns(path, "stations")
    return s


def test_new_store_has_inline(tmp_path):
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    ProjectStore.create(tmp_path / "wb.gpkg", "EPSG:25832")
    assert "inline" in _columns(tmp_path / "wb.gpkg", "stations")


def test_inline_round_trip(tmp_path):
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    st = ProjectStore.create(tmp_path / "wb.gpkg", "EPSG:25832")
    p = _profile()
    st.save_profile(p)
    s = attach_station_set(p, "ERT", "ert", np.array([[0.0, 0.0], [10.0, 0.0], [25.0, 0.0]]),
                           inline=[0.0, np.nan, 25.0])
    st.save_station_set(s)
    [back] = st.station_sets(p.id)
    assert back.inline.dtype == float
    np.testing.assert_array_equal(back.inline, [0.0, np.nan, 25.0])


def test_station_set_inline_defaults_to_nan():
    p = _profile()
    s = attach_station_set(p, "ERT", "ert", np.array([[0.0, 0.0], [10.0, 0.0]]))
    assert s.inline.shape == (2,) and np.isnan(s.inline).all()
    with pytest.raises(ValueError):
        attach_station_set(p, "ERT", "ert", np.array([[0.0, 0.0], [10.0, 0.0]]), inline=[1.0])


def test_schema_2_store_is_migrated(tmp_path, monkeypatch):
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    path = tmp_path / "old.gpkg"
    s = _make_schema_2(path, monkeypatch)
    st = ProjectStore.open(path)
    assert _meta(path)["schema_version"] == "4"
    assert "inline" in _columns(path, "stations")
    [back] = st.station_sets("p1")
    assert back.inline.shape == (3,) and np.isnan(back.inline).all()
    np.testing.assert_array_equal(back.numbers, s.numbers)
    np.testing.assert_allclose(back.xyz, s.xyz)
    np.testing.assert_allclose(back.chainage, s.chainage)
    np.testing.assert_allclose(back.offset, s.offset)
    [p] = st.profiles()
    assert (p.id, p.name, p.metadata) == ("p1", "Line 1", {"note": "kept"})
    np.testing.assert_allclose(p.xy, _profile().xy)
    assert st.datasets("p1") == [_dataset()]
    ProjectStore.open(path)                                  # a second open changes nothing
    assert _meta(path)["schema_version"] == "4"


def test_schema_1_store_opens_through_both_updates(tmp_path):
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    from tests.store.test_schema_2 import _make_schema_1
    path = tmp_path / "old.gpkg"
    _make_schema_1(path)
    st = ProjectStore.open(path)
    assert _meta(path)["schema_version"] == "4"
    assert "inline" in _columns(path, "stations")
    assert sorted(f.name for f in st.features(st.current_version().id)) == ["A", "B"]


def test_read_only_schema_2_store_says_why(tmp_path, monkeypatch):
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    path = tmp_path / "old.gpkg"
    _make_schema_2(path, monkeypatch)
    os.chmod(path, stat.S_IREAD)
    try:
        with pytest.raises(ValueError, match="one-time update for 0.9"):
            ProjectStore.open(path)
    finally:
        os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
    assert _meta(path)["schema_version"] == "2"


def test_a_migration_failing_part_way_leaves_the_file_as_it_was(tmp_path, monkeypatch):
    """The ``inline`` column is added, then the schema_version update fails: the
    transaction rolls the column back, and the file stays a schema 2 store."""
    from osgeo import ogr

    from groundwork_geophysics.store.gpkg_store import ProjectStore
    path = tmp_path / "old.gpkg"
    s = _make_schema_2(path, monkeypatch)
    real = ogr.DataSource.ExecuteSQL
    seen = []

    def fail_on_the_version(ds, sql, *args, **kwargs):
        if sql.lstrip().upper().startswith("UPDATE WB_META"):
            defn = ds.GetLayerByName("stations").GetLayerDefn()
            seen.append(defn.GetFieldIndex("inline") >= 0)      # the column is there now
            raise RuntimeError("disk I/O error")
        return real(ds, sql, *args, **kwargs)

    monkeypatch.setattr(ogr.DataSource, "ExecuteSQL", fail_on_the_version)
    with pytest.raises(ValueError, match="one-time update for 0.9"):
        ProjectStore.open(path)
    monkeypatch.undo()
    assert seen == [True]
    assert _meta(path)["schema_version"] == "2"
    assert "inline" not in _columns(path, "stations")
    st = ProjectStore.open(path)                    # the next open updates it
    assert _meta(path)["schema_version"] == "4"
    [back] = st.station_sets("p1")
    np.testing.assert_allclose(back.xyz, s.xyz)


def test_newer_store_is_refused(tmp_path):
    from osgeo import ogr

    from groundwork_geophysics.store.gpkg_store import ProjectStore
    path = tmp_path / "new.gpkg"
    ProjectStore.create(path, "EPSG:25832")
    ds = ogr.Open(str(path), 1)
    ds.ExecuteSQL("UPDATE wb_meta SET value = '5' WHERE key = 'schema_version'")
    ds = None
    with pytest.raises(ValueError, match="unsupported schema_version 5"):
        ProjectStore.open(path)


def test_dataset_without_a_station_set(tmp_path):
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    st = ProjectStore.create(tmp_path / "wb.gpkg", "EPSG:25832")
    p = _profile()
    st.save_profile(p)
    st.save_dataset(_dataset(station_set_id=""))
    assert st.datasets(p.id)[0].station_set_id == ""
    assert st.datasets(p.id) == [_dataset(station_set_id="")]


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
    """The stations layer is loaded from the 0.8 file before the plugin updates it."""
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from groundwork_geophysics import classFactory
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    from groundwork_geophysics.ui.project_actions import add_store_layers
    path = tmp_path / "old.gpkg"
    _make_schema_2(path, monkeypatch)
    old = ProjectStore(path, "EPSG:25832")                 # as 0.8 saw it, not opened
    layer = add_store_layers(old, project)["stations"]
    assert layer.isValid() and layer.fields().indexOf("inline") < 0
    plug = classFactory(fake_iface)
    plug.initGui()
    try:
        plug.set_store(ProjectStore.open(path))            # updates the file to schema 4
        assert _meta(path)["schema_version"] == "4"
        assert layer.isValid() and layer.fields().indexOf("inline") >= 0
        assert layer.featureCount() == 3
    finally:
        plug.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
