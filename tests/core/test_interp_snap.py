"""Snapping targets for interpretation drawing."""
import numpy as np
import pytest

from geophysics_workbench.core.interp_snap import SnapTargets, snap

T = SnapTargets(vertices=[(10.0, -2.0)], boundaries=[(20.0, -3.0)],
                ground=(np.array([0.0, 40.0]), np.array([0.0, 4.0])))


def test_vertex_wins():
    assert snap(10.2, -2.1, T, 1, 1) == (10.0, -2.0)


def test_boundary():
    assert snap(20.3, -3.2, T, 1, 1) == (20.0, -3.0)


def test_ground_line():
    assert snap(30.0, 2.6, T, 1, 1) == pytest.approx((30.0, 3.0))


def test_nothing_near():
    assert snap(30.0, -10.0, T, 1, 1) is None


def test_scaled_tolerance():
    assert snap(10.0, -2.9, T, 1, 0.5) is None


def test_beyond_ground_ends_and_empty_targets():
    assert snap(50.0, 5.0, T, 1, 1) is None
    assert snap(1.0, 1.0, SnapTargets(), 1, 1) is None


def test_line_target_projects_onto_segment():
    t = SnapTargets(lines=[np.array([[0.0, -5.0], [10.0, -5.0]])])
    assert snap(3.0, -4.8, t, 1, 1) == pytest.approx((3.0, -5.0))
    assert snap(3.0, -3.0, t, 1, 1) is None


def test_priority_vertex_boundary_line_ground():
    line = [np.array([[0.0, -2.0], [40.0, -2.0]])]
    t = SnapTargets(vertices=[(10.0, -2.1)], boundaries=[(20.0, -2.1)], lines=line,
                    ground=(np.array([0.0, 40.0]), np.array([-1.5, -1.5])))
    assert snap(10.1, -2.0, t, 1, 1) == (10.0, -2.1)
    assert snap(20.1, -2.0, t, 1, 1) == (20.0, -2.1)
    assert snap(30.0, -1.9, t, 1, 1) == pytest.approx((30.0, -2.0))
    assert snap(30.0, -1.4, t, 1, 0.3) == pytest.approx((30.0, -1.5))
