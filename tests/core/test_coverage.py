"""Model extent against station coverage (0.1.1, finding F1)."""
import numpy as np
import pytest

from groundwork_geophysics.core.coverage import (overhang_limit, station_coverage,
                                                station_overhang)
from groundwork_geophysics.core.model import (attach_station_set, profile_from_stations,
                                             x_to_chainage)


def _line(n=48, spacing=5.0):
    xyz = np.column_stack([np.arange(n) * spacing, np.zeros(n), np.full(n, 50.0)])
    return profile_from_stations("P4", "EPSG:25832", xyz)


def test_model_inside_the_stations_has_no_overhang():
    _p, s = _line()                                       # stations 0 .. 235 m
    assert station_overhang(0.0, 235.0, s) == (0.0, 0.0)
    assert station_overhang(10.0, 200.0, s) == (0.0, 0.0)


def test_overhang_at_the_start_and_at_the_end():
    _p, s = _line()
    assert station_overhang(-12.5, 100.0, s) == pytest.approx((12.5, 0.0))
    assert station_overhang(0.0, 355.0, s) == pytest.approx((0.0, 120.0))
    assert station_overhang(355.0, 0.0, s) == pytest.approx((0.0, 120.0))   # any order


def test_reversed_station_set_maps_through_chainage():
    p, _ = _line(21)                                      # profile 0 .. 100 m
    xyz = np.column_stack([np.arange(21) * 5.0, np.zeros(21), np.full(21, 50.0)])
    s = attach_station_set(p, "rev", "ert", xyz, numbers=np.arange(21, 0, -1))
    assert s.direction == -1 and s.metre0 == pytest.approx(100.0)
    # data metres 0 .. 120 from station 1 (at s = 100) run against the profile
    lo, hi = x_to_chainage(np.array([0.0, 120.0]), s)
    assert (lo, hi) == pytest.approx((100.0, -20.0))
    assert station_overhang(lo, hi, s) == pytest.approx((20.0, 0.0))


def test_overhang_limit_is_two_station_spacings():
    _p, s = _line(spacing=2.5)
    assert overhang_limit(s) == pytest.approx(5.0)
    _p, s = _line(spacing=5.0)
    assert overhang_limit(s) == pytest.approx(10.0)
    p, _ = _line(11)
    single = attach_station_set(p, "one", "ert", np.array([[10.0, 0.0, 50.0]]))
    assert overhang_limit(single) == 5.0


def test_station_coverage_spans_all_sets():
    p, _ = _line(15)                                      # profile 0 .. 70
    xyz = np.column_stack([np.arange(11) * 5.0, np.zeros(11), np.full(11, 50.0)])
    a = attach_station_set(p, "a", "ert", xyz)            # 0 .. 50
    xyz = np.column_stack([np.array([20.0, 70.0]), np.zeros(2), np.full(2, 50.0)])
    b = attach_station_set(p, "b", "ert", xyz)
    assert station_coverage([a]) == pytest.approx((0.0, 50.0))
    assert station_coverage([a, b]) == pytest.approx((0.0, 70.0))
    assert station_coverage([]) is None
