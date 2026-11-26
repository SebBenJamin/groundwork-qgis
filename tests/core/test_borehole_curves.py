import numpy as np
import pytest

from groundwork_geophysics.core.borehole_curves import (CurveStyle, data_range, track_fraction,
                                                       value_at)
from groundwork_geophysics.core.context import Curve


def _curve(depth, values, key="k"):
    return Curve(key, "gr", "API", np.array(depth, float), np.array(values, float))


def test_log_fraction_skips_non_positive():
    f = track_fraction(np.array([0.0, -1.0, 10.0, 100.0]), 1.0, 100.0, log=True)
    assert np.isnan(f[0]) and np.isnan(f[1])
    assert f[2] == pytest.approx(0.5) and f[3] == pytest.approx(1.0)


def test_linear_fraction_and_nan_kept():
    f = track_fraction(np.array([0.0, np.nan, 150.0]), 0.0, 150.0, log=False)
    assert f[0] == 0.0 and np.isnan(f[1]) and f[2] == 1.0


def test_flat_range_does_not_divide_by_zero():
    f = track_fraction(np.array([5.0, 5.0]), 5.0, 5.0, log=False)
    assert np.all(np.isfinite(f))


def test_value_at_never_crosses_a_gap():
    c = _curve([1.0, 1.5, 2.0], [40.0, np.nan, 50.0])
    assert value_at(c, 1.25) is None and value_at(c, 1.0) == 40.0
    assert value_at(c, 0.5) is None and value_at(c, 2.5) is None


def test_value_at_interpolates():
    c = _curve([1.0, 2.0], [40.0, 50.0])
    assert value_at(c, 1.5) == pytest.approx(45.0)


def test_data_range_over_curves_log_ignores_non_positive():
    a, b = _curve([1, 2], [0.0, 10.0]), _curve([1, 2], [100.0, np.nan])
    assert data_range([a, b], log=False) == (0.0, 100.0)
    assert data_range([a, b], log=True) == (10.0, 100.0)
    assert data_range([_curve([1], [np.nan])], log=False) is None


def test_curve_style_defaults():
    s = CurveStyle()
    assert s.fill == "none" and s.log is False and s.vmin is None



def test_value_at_on_a_log_scale_skips_non_positive_neighbours():
    """Minor 4: on a log scale a sample <= 0 is a gap in the line; the readout agrees."""
    c = _curve([1.0, 2.0, 3.0], [10.0, 0.0, 30.0])
    assert value_at(c, 1.5) == pytest.approx(5.0)
    assert value_at(c, 1.5, log=True) is None and value_at(c, 3.0, log=True) == 30.0


def test_nice_range_rounds_the_scale_ends_outward():
    """Scale ends the eye can read: 1-2-5 steps on a linear track (about ten per span),
    whole decades on a log track; the data always fits inside."""
    from groundwork_geophysics.core.borehole_curves import nice_range
    assert nice_range(0.0175, 10.964, False) == (0.0, 12.0)
    assert nice_range(2.8, 68.8, False) == (0.0, 70.0)
    assert nice_range(10.0, 140.0, False) == (0.0, 140.0)
    assert nice_range(-3.2, 4.1, False) == (-4.0, 5.0)
    assert nice_range(0.0175, 10.964, True) == (0.01, 100.0)
    assert nice_range(5.0, 500.0, True) == (1.0, 1000.0)
    assert nice_range(10.0, 100.0, True) == (10.0, 100.0)
    assert nice_range(5.0, 5.0, False) == (5.0, 5.0)              # flat: left as it is
