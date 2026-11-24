"""Scattered-point interpolation for the smooth display: nearest, inverse distance, spline,
ordinary kriging (numpy/scipy only)."""
import numpy as np
import pytest

from groundwork_geophysics.core.interpolators import (Interpolation, estimate_anisotropy,
                                                      fit_variogram, interpolate)


def test_settings_round_trip_and_defaults():
    s = Interpolation(method="kriging", range_m=12.0, variogram="exponential", neighbours=20)
    assert Interpolation.from_dict(s.to_dict()) == s
    assert Interpolation.from_dict({"method": "bogus", "power": "x"}) == Interpolation()
    assert Interpolation.from_dict(None) == Interpolation()
    assert Interpolation().is_linear and not s.is_linear
    assert s.key() != Interpolation(method="kriging").key()


def _run(points, values, targets, aniso=1.0, **kw):
    out, _info = interpolate(np.asarray(points, float), np.asarray(values, float),
                             np.asarray(targets, float), Interpolation(**kw), aniso)
    return out


def test_nearest_takes_the_closest_point():
    out = _run([[0, 0], [10, 0]], [1, 5], [[2, 0], [9, 0]], method="nearest")
    assert out.tolist() == [1, 5]


def test_idw_is_exact_at_data_and_the_mean_midway():
    out = _run([[0, 0], [10, 0]], [1, 5], [[0, 0], [5, 0]], method="idw")
    assert out == pytest.approx([1, 3])


def test_idw_with_duplicate_points_does_not_divide_by_zero():
    out = _run([[0, 0], [0, 0], [4, 0]], [2, 4, 9], [[0, 0]], method="idw")
    assert np.isfinite(out).all() and out[0] == pytest.approx(3)


def test_spline_reproduces_a_plane():
    rng = np.random.default_rng(1)
    pts = rng.uniform(0, 10, (50, 2))
    targets = rng.uniform(3, 7, (20, 2))
    out = _run(pts, 2 * pts[:, 0] + 3 * pts[:, 1], targets, method="spline")
    assert out == pytest.approx(2 * targets[:, 0] + 3 * targets[:, 1], abs=1e-6)


def _smooth_field(n=400, seed=2):
    rng = np.random.default_rng(seed)
    pts = np.column_stack([rng.uniform(0, 40, n), rng.uniform(0, 10, n)])
    return pts, np.sin(pts[:, 0] / 10) + pts[:, 1] / 20


def test_kriging_reproduces_a_smooth_field_and_reports_the_fit():
    pts, v = _smooth_field()
    targets = np.column_stack([np.linspace(5, 35, 30), np.linspace(2, 8, 30)])
    out, info = interpolate(pts, v, targets, Interpolation(method="kriging"), 1.0)
    truth = np.sin(targets[:, 0] / 10) + targets[:, 1] / 20
    assert np.abs(out - truth).max() < 0.1
    assert info["range"] > 0 and info["sill"] > 0 and info["nugget"] >= 0


def test_kriging_with_a_given_variogram_is_exact_at_data_without_nugget():
    pts, v = _smooth_field(100)
    out = _run(pts, v, pts[:5], method="kriging", range_m=10.0, sill=1.0, nugget=0.0)
    assert out == pytest.approx(v[:5], abs=1e-6)


@pytest.mark.parametrize("method", ["nearest", "idw", "spline", "kriging"])
def test_fewer_points_than_neighbours(method):
    pts = [[0, 0], [1, 0], [0, 1], [1, 1], [0.5, 0.2]]
    kw = {"range_m": 2.0, "sill": 1.0, "nugget": 0.0} if method == "kriging" else {}
    out = _run(pts, [1, 2, 3, 4, 2.5], [[0.5, 0.5], [0.2, 0.7]], method=method,
               neighbours=16, **kw)
    assert np.isfinite(out).all()


def test_constant_values_cannot_be_fitted():
    pts, _v = _smooth_field(100)
    with pytest.raises(ValueError):
        fit_variogram(pts, np.full(len(pts), 3.0), "spherical")
    with pytest.raises(ValueError):
        _run(pts, np.full(len(pts), 3.0), pts[:3], method="kriging")


def test_anisotropy_stretches_the_vertical():
    # the target is 1 m above the first point and 2 m beside the second, at its height:
    # with layers (horizontal ranges 10 x the vertical) the point at the same height is nearer
    pts, vals, target = [[0, 0], [2, 1]], [0, 10], [[0, 1]]
    assert _run(pts, vals, target, 1.0, method="nearest")[0] == 0
    assert _run(pts, vals, target, 10.0, method="nearest")[0] == 10


def test_estimate_anisotropy_finds_layering():
    rng = np.random.default_rng(3)
    pts = np.column_stack([rng.uniform(0, 100, 2000), rng.uniform(0, 20, 2000)])
    layered = np.sin(pts[:, 1] / 2) + 0.05 * np.sin(pts[:, 0] / 15)
    assert estimate_anisotropy(pts, layered, "spherical") >= 3
    assert 1.0 <= estimate_anisotropy(pts, rng.normal(size=2000), "spherical") <= 20
