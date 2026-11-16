"""Readings of an inversion: misfit, RMS, checks, and their pseudosection mesh."""
import numpy as np
import pytest

from groundwork_geophysics.core.readings import Readings, check, readings_mesh


def _readings(calc=None, n=12, **kw):
    x = np.arange(n, dtype=float)
    s = np.where(np.arange(n) % 2 == 0, 1.0, 2.0)          # two spacings: two depth levels
    meas = np.full(n, 100.0)
    return Readings(a=x, b=x + 3 * s, m=x + s, n=x + 2 * s, measured=meas,
                    calculated=np.full(n, 110.0) if calc is None else calc, **kw)


def test_misfit_rms_chi2():
    r = _readings(error=np.full(12, 0.05))
    assert np.allclose(r.misfit_percent(), 10.0)
    assert r.rms_percent() == pytest.approx(10.0)
    assert r.chi2() == pytest.approx(4.0)                 # (0.10 / 0.05)^2
    assert _readings().chi2() is None


def test_nan_and_zero_readings_left_out():
    calc = np.full(12, 110.0); calc[0] = np.nan
    r = _readings(calc=calc)
    r.measured[1] = 0.0
    mis = r.misfit_percent()
    assert np.isnan(mis[:2]).all() and r.rms_percent() == pytest.approx(10.0)


def test_check_fails_loudly():
    with pytest.raises(ValueError):
        check(_readings(calc=np.zeros(12)))
    with pytest.raises(ValueError):
        check(_readings(calc=np.full(12, np.nan)))
    with pytest.raises(ValueError):
        check(_readings(stated_rms=1.0))                  # computed 10 %, file says 1 %
    check(_readings(stated_rms=9.0))
    check(_readings(calc=np.full(12, np.nan), has_calculated=False))   # measured only


def test_mesh_carries_readings_and_values():
    r = _readings()
    mesh = readings_mesh(r, "misfit")
    assert mesh.quantity == "misfit" and mesh.unit == "%"
    assert len(mesh.readings) == 12 and np.array_equal(mesh.readings.a, r.a)
    assert len(mesh.point_values) == 12
    assert np.allclose(mesh.point_values, 10.0)
    assert (mesh.vertices[:, 1] < 0).all()                 # depths, below the surface
    moved = mesh.with_x(lambda x: 100.0 - x)
    assert np.allclose(moved.readings.a, 100.0 - r.a)
    meas = readings_mesh(r, "measured")
    assert meas.quantity == "resistivity" and np.allclose(meas.point_values, 100.0)


def test_single_depth_level_gives_a_readable_error():
    x = np.arange(6, dtype=float)
    r = Readings(a=x, b=x + 3, m=x + 1, n=x + 2, measured=np.full(6, 100.0),
                 calculated=np.full(6, 100.0))
    with pytest.raises(ValueError, match="pseudosection"):
        readings_mesh(r, "misfit")
