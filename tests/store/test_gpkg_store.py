import sqlite3

import numpy as np
import pytest

from geophysics_workbench.core.model import Dataset, Profile, StationSet, profile_from_stations
from geophysics_workbench.store.gpkg_store import ProjectStore


def test_roundtrip_profile_stations_dataset(tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p, s = profile_from_stations("P1", "EPSG:25832", np.array([[0, 0, 100], [10, 0, 101.0]]))
    st.save_profile(p); st.save_station_set(s)
    d = Dataset("d1", p.id, s.id, "ert_model", "C:/x/f001_res.dat", 1.0, "abc", "r2_res_dat",
                {"chainage_offset": 0}, {"iteration": 1}, name="P1 model")
    st.save_dataset(d)
    st2 = ProjectStore.open(tmp_path / "p.gpkg")
    assert st2.profile(p.id).xy == pytest.approx(p.xy)
    assert st2.station_sets(p.id)[0].xyz[:, 2] == pytest.approx([100, 101])
    assert st2.datasets(p.id)[0].reader_options == {"chainage_offset": 0}


def test_upsert_dataset(tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p, s = profile_from_stations("P1", "EPSG:25832", np.array([[0, 0], [10, 0.0]]))
    st.save_profile(p)
    d = Dataset("d1", p.id, s.id, "ert_model", "a", 0, "", "r2_res_dat", {}, {}, name="a")
    st.save_dataset(d); d.name = "b"; st.save_dataset(d)
    assert [x.name for x in st.datasets(p.id)] == ["b"]


def test_create_rejects_geographic_crs(tmp_path):
    with pytest.raises(ValueError, match="projected CRS") as e:
        ProjectStore.create(tmp_path / "g.gpkg", "EPSG:4326")
    assert "EPSG:4326" in str(e.value)
    assert not (tmp_path / "g.gpkg").exists()


def test_create_unknown_crs_and_existing_path(tmp_path):
    with pytest.raises(ValueError):
        ProjectStore.create(tmp_path / "x.gpkg", "NOPE:1")
    (tmp_path / "e.gpkg").write_bytes(b"")
    with pytest.raises(FileExistsError):
        ProjectStore.create(tmp_path / "e.gpkg", "EPSG:25832")


def test_open_rejects_non_store(tmp_path):
    plain = tmp_path / "plain.gpkg"
    con = sqlite3.connect(plain); con.execute("create table t(a)"); con.commit(); con.close()
    with pytest.raises(ValueError, match="not a Geophysics Workbench project"):
        ProjectStore.open(plain)
    with pytest.raises(ValueError, match="not a Geophysics Workbench project"):
        ProjectStore.open(tmp_path / "missing.gpkg")


def test_open_rejects_unsupported_schema(tmp_path):
    path = tmp_path / "p.gpkg"
    ProjectStore.create(path, "EPSG:25832")
    con = sqlite3.connect(path)
    con.execute("update wb_meta set value='99' where key='schema_version'"); con.commit(); con.close()
    with pytest.raises(ValueError, match="99"):
        ProjectStore.open(path)


def test_crs_and_layer_uri(tmp_path):
    path = tmp_path / "p.gpkg"
    st = ProjectStore.create(path, "EPSG:25832")
    assert st.crs_authid == "EPSG:25832"
    assert ProjectStore.open(path).crs_authid == "EPSG:25832"
    assert st.layer_uri("profiles") == f"{path}|layername=profiles"
    from osgeo import ogr
    with ogr.ExceptionMgr(useExceptions=True):
        ds = ogr.Open(str(path))
        for name in ("profiles", "stations"):
            srs = ds.GetLayerByName(name).GetSpatialRef()
            assert srs.GetAuthorityCode(None) == "25832"
        ds = None


def test_nan_z_and_order_roundtrip(tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    xyz = np.array([[0, 0, np.nan], [10, 0, 5.5], [20, 0, np.nan], [30, 0, 7.0]])
    p, s = profile_from_stations("P", "EPSG:25832", xyz, numbers=np.array([4, 3, 2, 1]))
    s.warnings = ["w1", "ä"]
    st.save_profile(p); st.save_station_set(s)
    r = ProjectStore.open(tmp_path / "p.gpkg").station_sets(p.id)[0]
    assert np.array_equal(r.numbers, [4, 3, 2, 1])
    assert np.array_equal(np.isnan(r.xyz[:, 2]), [True, False, True, False])
    assert r.xyz[:, :2] == pytest.approx(xyz[:, :2])
    assert r.xyz[[1, 3], 2] == pytest.approx([5.5, 7.0])
    assert r.chainage == pytest.approx(s.chainage) and r.offset == pytest.approx(s.offset)
    assert r.metre0 == s.metre0 and r.warnings == ["w1", "ä"]
    assert (r.name, r.method, r.profile_id, r.id) == (s.name, s.method, s.profile_id, s.id)


def test_station_set_upsert_replaces_points(tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p, s = profile_from_stations("P", "EPSG:25832", np.array([[0, 0, 1], [10, 0, 2], [20, 0, 3.0]]))
    st.save_profile(p); st.save_station_set(s)
    p2, s2 = profile_from_stations("Q", "EPSG:25832", np.array([[0, 5, 1], [10, 5, 2.0]]))
    st.save_profile(p2); st.save_station_set(s2)
    s3 = StationSet(s.id, s.profile_id, "renamed", s.method, s.numbers[:2], s.xyz[:2],
                    s.chainage[:2], s.offset[:2], s.metre0, [])
    st.save_station_set(s3)
    st = ProjectStore.open(tmp_path / "p.gpkg")
    got = st.station_sets(p.id)
    assert len(got) == 1 and got[0].name == "renamed" and len(got[0].numbers) == 2
    assert len(st.station_sets(p2.id)[0].numbers) == 2


def test_profiles_ordering_upsert_and_metadata(tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    b = Profile("b", "B", np.array([[0, 0], [1, 1.0]]), "EPSG:25832", {"k": [1, 2.5], "n": 0})
    a = Profile("z", "A", np.array([[0, 0], [2, 2.0]]), "EPSG:25832")
    st.save_profile(b); st.save_profile(a)
    assert [p.id for p in st.profiles()] == ["z", "b"]
    assert st.profile("b").metadata == {"k": [1, 2.5], "n": 0}
    assert st.profile("b").crs_authid == "EPSG:25832"
    b.name = "C"; st.save_profile(b)
    assert [p.name for p in st.profiles()] == ["A", "C"]
    with pytest.raises(KeyError):
        st.profile("nope")


def test_dataset_fields_order_and_delete(tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    mk = lambda i, **k: Dataset(i, "p", "s", "ert_model", "src", 12.5, "sha", "rd",
                                {"a": 1, "b": 2.5}, {"c": [1, 2]}, **k)
    st.save_dataset(mk("z")); st.save_dataset(mk("a", version=3, parent_id="z", quantity="q",
                                                  unit="u", name="n"))
    st.save_dataset(mk("z"))  # upsert keeps its place
    ds = st.datasets("p")
    assert [d.id for d in ds] == ["z", "a"]
    a = ds[1]
    assert (a.version, a.parent_id, a.quantity, a.unit, a.name) == (3, "z", "q", "u", "n")
    assert ds[0].parent_id is None and ds[0].source_mtime == 12.5
    assert ds[0].reader_options == {"a": 1, "b": 2.5} and ds[0].provenance == {"c": [1, 2]}
    st.delete_dataset("nope")
    st.delete_dataset("z")
    assert [d.id for d in st.datasets("p")] == ["a"]


def test_files_released_and_no_global_gdal_state(tmp_path):
    from osgeo import gdal
    before = gdal.GetUseExceptions()
    path = tmp_path / "p.gpkg"
    st = ProjectStore.create(path, "EPSG:25832")
    p, s = profile_from_stations("P", "EPSG:25832", np.array([[0, 0, 1], [10, 0, 2.0]]))
    st.save_profile(p); st.save_station_set(s); st.profiles()
    assert gdal.GetUseExceptions() == before
    path.unlink()
