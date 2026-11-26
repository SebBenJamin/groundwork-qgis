"""Reads in one pass share one open GeoPackage (opening it is slow on a USB stick)."""
import numpy as np


def _store(tmp_path):
    from groundwork_geophysics.core.model import profile_from_stations
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p, s = profile_from_stations("P1", "EPSG:25832", np.array([[0, 0, 100], [50, 0, 102.0]]))
    st.save_profile(p)
    st.save_station_set(s)
    return st, p


def test_reads_in_a_pass_open_the_file_once(qgis_app, tmp_path, monkeypatch):
    from osgeo import ogr

    from groundwork_geophysics.store import gpkg_store
    st, p = _store(tmp_path)
    opened = []
    real = ogr.Open
    monkeypatch.setattr(gpkg_store.ogr, "Open", lambda *a: opened.append(a) or real(*a))
    with st.reading():
        for _ in range(5):
            assert st.profile(p.id).name == "P1"
            assert len(st.station_sets(p.id)) == 1
            assert st.datasets(p.id) == []
    assert len(opened) == 1
    opened.clear()
    st.profiles()                                      # outside a pass: as before
    st.profiles()
    assert len(opened) == 2


def test_a_write_during_a_pass_is_seen_by_the_next_read(qgis_app, tmp_path):
    from dataclasses import replace
    st, p = _store(tmp_path)
    with st.reading():
        assert [q.name for q in st.profiles()] == ["P1"]
        st.save_profile(replace(p, id="p2", name="P2"))
        assert [q.name for q in st.profiles()] == ["P1", "P2"]
        with st.reading():                             # nested: still the one pass
            assert st.profile("p2").name == "P2"
