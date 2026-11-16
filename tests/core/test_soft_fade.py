"""Round 2, F2: the coverage fade of the smooth field changes softly, not in one step."""
import numpy as np


def test_soft_alpha_monotone():
    from groundwork_geophysics.core.gridding import FADE_ALPHA, soft_coverage_alpha
    cov = np.linspace(-2.0, 2.0, 41)
    a = soft_coverage_alpha(cov, 0.0, "fade", band=1.0)
    assert a[0] == FADE_ALPHA and a[-1] == 1.0
    assert (np.diff(a) >= 0).all()
    inside = a[(cov > -0.5) & (cov < 0.5)]
    assert len(np.unique(np.round(inside, 6))) >= 3


def test_blank_reaches_zero():
    from groundwork_geophysics.core.gridding import soft_coverage_alpha
    a = soft_coverage_alpha(np.array([-3.0, 0.0, 3.0, np.nan]), 0.0, "blank", band=1.0)
    assert a[0] == 0.0 and 0.0 < a[1] < 1.0 and a[2] == 1.0 and a[3] == 1.0


def test_band_zero_is_hard_step():
    from groundwork_geophysics.core.gridding import coverage_alpha, soft_coverage_alpha
    cov = np.array([-1.0, -0.1, 0.0, 0.1, np.nan])
    for mode in ("fade", "blank"):
        assert np.array_equal(soft_coverage_alpha(cov, 0.0, mode, band=0.0),
                              coverage_alpha(cov, 0.0, mode))


def test_fade_band():
    from groundwork_geophysics.core.gridding import fade_band
    cov = np.linspace(0.0, 10.0, 101)
    assert abs(fade_band(cov) - 0.1 * (np.percentile(cov, 95) - np.percentile(cov, 5))) < 1e-9
    assert fade_band(np.array([1.0])) == 0.0 and fade_band(np.array([np.nan, np.nan])) == 0.0
