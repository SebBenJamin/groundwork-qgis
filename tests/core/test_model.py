import numpy as np
import pytest

from geophysics_workbench.core.model import (
    Dataset, Profile, StationSet, attach_station_set, data_to_chainage,
    file_fingerprint, profile_from_line, profile_from_stations)


def test_profile_from_stations_chainage_and_metre0():
    xyz = np.array([[0, 0, 100], [5, 0, 101], [10, 0, 103]], float)
    p, st = profile_from_stations("P1", "EPSG:25832", xyz)
    assert p.chainage.length == pytest.approx(10)
    assert st.chainage == pytest.approx([0, 5, 10])
    assert st.metre0 == 0 and list(st.numbers) == [1, 2, 3]
    assert st.xyz[:, 2] == pytest.approx([100, 101, 103])
    assert st.profile_id == p.id


def test_profile_from_stations_2d_gives_nan_z():
    p, st = profile_from_stations("P", "EPSG:25832", np.array([[0, 0], [5, 0.0]]))
    assert st.xyz.shape == (2, 3) and np.isnan(st.xyz[:, 2]).all()


def test_profile_from_line_spacing():
    p, st = profile_from_line("P2", "EPSG:25832", np.array([[0, 0], [0, 12.0]]), spacing=5)
    assert st.chainage == pytest.approx([0, 5, 10])
    assert np.isnan(st.xyz[:, 2]).all()
    assert st.xyz[:, :2] == pytest.approx(np.array([[0, 0], [0, 5], [0, 10.0]]))
    assert list(st.numbers) == [1, 2, 3]


def test_profile_from_line_first_number_and_bad_spacing():
    _, st = profile_from_line("P", "EPSG:25832", np.array([[0, 0], [10, 0.0]]),
                              spacing=5, first_number=11)
    assert list(st.numbers) == [11, 12, 13]
    with pytest.raises(ValueError):
        profile_from_line("P", "EPSG:25832", np.array([[0, 0], [10, 0.0]]), spacing=0)


def test_metre0_follows_station_one_after_reverse():
    xyz = np.array([[0, 0], [5, 0], [10, 0]], float)
    p, _ = profile_from_stations("P", "EPSG:25832", xyz)
    rp = p.reversed()
    assert rp.id == p.id and rp.name == p.name and rp.crs_authid == p.crs_authid
    assert rp.xy[0] == pytest.approx([10, 0])
    st = attach_station_set(rp, "electrodes", "ert", xyz, numbers=np.array([1, 2, 3]))
    assert st.metre0 == pytest.approx(10)


def test_reversed_copies_metadata():
    p = Profile("i", "n", np.array([[0, 0], [1, 0.0]]), "EPSG:1", {"a": 1})
    rp = p.reversed()
    rp.metadata["a"] = 2
    assert p.metadata["a"] == 1


def test_attach_warns_when_off_line():
    p, _ = profile_from_stations("P", "EPSG:25832", np.array([[0, 0], [100, 0.0]]))
    st = attach_station_set(p, "geophones", "seismic", np.array([[10, 1], [20, 8.0]]), tolerance=5)
    assert st.warnings == ["station 2: 8.0 m off line"]


def test_attach_warning_uses_signed_offset():
    p, _ = profile_from_stations("P", "EPSG:25832", np.array([[0, 0], [100, 0.0]]))
    st = attach_station_set(p, "g", "seismic", np.array([[10, -8.0]]))
    assert st.warnings == ["station 1: -8.0 m off line"]


def test_data_to_chainage_applies_both_offsets():
    p, st = profile_from_stations("P", "EPSG:25832", np.array([[0, 0], [100, 0.0]]))
    st.metre0 = 20.0
    ds = Dataset("d", p.id, st.id, "ert_model", "x", 0, "", "zondres_xyz", {"chainage_offset": -2.5}, {})
    assert data_to_chainage(np.array([0, 10.0]), st, ds) == pytest.approx([17.5, 27.5])
    assert ds.version == 1 and ds.parent_id is None
    assert ds.quantity == "resistivity" and ds.unit == "ohm.m" and ds.name == ""


def test_mutable_defaults_not_shared():
    a = Profile("a", "a", np.zeros((2, 2)), "x")
    b = Profile("b", "b", np.zeros((2, 2)), "x")
    a.metadata["k"] = 1
    assert b.metadata == {}


def test_file_fingerprint(tmp_path):
    import hashlib
    import os
    f = tmp_path / "f.bin"
    f.write_bytes(b"hello" * 100000)
    mtime, sha = file_fingerprint(str(f))
    assert mtime == os.stat(f).st_mtime
    assert sha == hashlib.sha1(b"hello" * 100000).hexdigest()


# -- numbering direction (stations numbered against the line direction) --------------------
def _model_at(x_data, profile, st, offset=0.0):
    """World (x, y) where data metre ``x_data`` of a model on ``st`` is drawn."""
    ds = Dataset("d", profile.id, st.id, "ert_model", "m", 0, "", "r2_res_dat",
                 {"chainage_offset": offset}, {})
    return profile.chainage.to_xy(data_to_chainage(np.asarray(x_data, float), st, ds))


def _station_xy(st, number):
    return st.xyz[list(st.numbers).index(number), :2]


def test_descending_station_file_puts_data_on_its_station():
    xyz = np.column_stack([np.arange(10) * 5.0, np.zeros(10)])       # numbered 10..1 along +x
    p, st = profile_from_stations("P", "EPSG:25832", xyz, numbers=np.arange(10, 0, -1))
    assert p.chainage.length == pytest.approx(45)
    # data x = 20 m is 4 spacings from station 1, i.e. station 5
    assert _model_at([20.0], p, st)[0] == pytest.approx(_station_xy(st, 5))
    assert _model_at([0.0], p, st)[0] == pytest.approx(_station_xy(st, 1))


def test_unsorted_station_file_builds_a_straight_line():
    rng = np.random.default_rng(1)
    order = rng.permutation(10)
    xyz = np.column_stack([np.arange(10) * 5.0, np.zeros(10)])[order]
    p, st = profile_from_stations("P", "EPSG:25832", xyz, numbers=np.arange(1, 11)[order])
    assert p.chainage.length == pytest.approx(45)                     # no zigzag
    assert list(st.numbers) == list(range(1, 11))
    assert _model_at([20.0, 45.0], p, st) == pytest.approx(
        np.array([_station_xy(st, 5), _station_xy(st, 10)]))


def test_reversed_profile_maps_data_against_chainage():
    xyz = np.array([[0, 0], [5, 0], [10, 0]], float)
    p, _ = profile_from_stations("P", "EPSG:25832", xyz)
    rp = p.reversed()
    st = attach_station_set(rp, "electrodes", "ert", xyz, numbers=np.array([1, 2, 3]))
    assert st.direction == -1
    assert _model_at([5.0], rp, st)[0] == pytest.approx(_station_xy(st, 2))
    # the chainage offset shifts along the numbering too: x=3 + offset 2 -> station 2
    assert _model_at([3.0], rp, st, offset=2.0)[0] == pytest.approx(_station_xy(st, 2))


def test_line_profile_with_descending_numbers_attached():
    p, _ = profile_from_line("P", "EPSG:25832", np.array([[0, 0], [20, 0.0]]), spacing=5)
    xyz = np.column_stack([np.arange(5) * 5.0, np.zeros(5)])
    st = attach_station_set(p, "e", "ert", xyz, numbers=np.array([5, 4, 3, 2, 1]))
    assert st.metre0 == pytest.approx(20) and st.direction == -1
    assert _model_at([5.0], p, st)[0] == pytest.approx(_station_xy(st, 2))


def test_profile_from_line_numbered_from_end():
    p, st = profile_from_line("P", "EPSG:25832", np.array([[0, 0], [12, 0.0]]), spacing=5,
                              from_end=True)
    assert p.xy[0] == pytest.approx([12, 0]) and p.xy[-1] == pytest.approx([0, 0])
    assert st.xyz[:, :2] == pytest.approx(np.array([[12, 0], [7, 0], [2, 0.0]]))
    assert list(st.numbers) == [1, 2, 3] and st.direction == 1
