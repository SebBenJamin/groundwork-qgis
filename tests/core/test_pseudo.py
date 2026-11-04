"""Pseudosection position of a reading: midpoint and Edwards median depth of investigation."""
import numpy as np
import pytest

from geophysics_workbench.core.pseudo import median_depth, midpoint

NAN = np.nan


def test_wenner_dipole_dipole_pole_pole_match_edwards():
    a = 2.0
    wenner = median_depth(np.array([0.0]), np.array([3 * a]), np.array([a]), np.array([2 * a]))
    assert wenner[0] == pytest.approx(0.519 * a, abs=0.002 * a)
    dd = median_depth(np.array([a]), np.array([0.0]), np.array([2 * a]), np.array([3 * a]))
    assert dd[0] == pytest.approx(0.416 * a, abs=0.002 * a)
    pp = median_depth(np.array([0.0]), np.array([NAN]), np.array([a]), np.array([NAN]))
    assert pp[0] == pytest.approx(0.866 * a, abs=0.002 * a)


def test_vectorised_and_scales_with_spacing():
    a = np.array([0.0, 0.0]); b = np.array([3.0, 30.0])
    m = np.array([1.0, 10.0]); n = np.array([2.0, 20.0])
    d = median_depth(a, b, m, n)
    assert d[1] == pytest.approx(10 * d[0])


def test_midpoint_ignores_absent_poles():
    assert midpoint(np.array([0.0]), np.array([NAN]), np.array([2.0]), np.array([4.0]))[0] == 2.0


def test_degenerate_reading_gives_nan():
    assert np.isnan(median_depth(np.array([0.0]), np.array([0.0]), np.array([1.0]),
                                 np.array([1.0]))[0])
