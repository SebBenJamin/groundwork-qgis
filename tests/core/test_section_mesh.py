import numpy as np
import pytest

from geophysics_workbench.core.section_mesh import SectionMesh


def grid_points():
    x, z = np.meshgrid(np.arange(0, 11.0), -np.arange(0, 6.0))
    return x.ravel(), z.ravel(), np.full(x.size, 100.0)


def test_from_points_covers_grid():
    m = SectionMesh.from_points(*grid_points())
    assert m.bounds() == pytest.approx((0, 10, -5, 0))
    assert m.value_at(5.2, -2.3) == pytest.approx(100)
    assert np.isnan(m.value_at(20, -2))


def test_max_edge_drops_bridging_triangles():
    x, z, v = grid_points()
    keep = ~((x > 3) & (x < 7) & (z < -2))          # a notch in the model
    m = SectionMesh.from_points(x[keep], z[keep], v[keep], max_edge=1.5)
    assert np.isnan(m.value_at(5, -4))


def test_depth_to_elevation_uses_surface():
    m = SectionMesh.from_points(np.array([0, 10, 0, 10.0]), np.array([0, 0, 5, 5.0]), np.ones(4))
    e = m.depth_to_elevation(np.array([0, 10.0]), np.array([100, 110.0]))
    assert e.bounds() == pytest.approx((0, 10, 95, 110))


def test_depth_to_elevation_sign_agnostic_and_clamped():
    m = SectionMesh.from_points(np.array([-5, 15, -5, 15.0]), np.array([0, 0, -5, -5.0]), np.ones(4), max_edge=100)
    e = m.depth_to_elevation(np.array([0, 10.0]), np.array([100, 110.0]))
    # beyond the surface ends np.interp clamps: x=-5 -> 100, x=15 -> 110
    assert e.bounds() == pytest.approx((-5, 15, 95, 110))


def test_with_x_shifts():
    m = SectionMesh.from_points(*grid_points()).with_x(lambda x: x + 20)
    assert m.bounds()[0] == pytest.approx(20)


def test_resistivity_uses_geometric_mean():
    x = np.array([0, 1, 0.0])
    z = np.array([0, 0, -1.0])
    m = SectionMesh.from_points(x, z, np.array([10.0, 100.0, 1000.0]))
    assert m.values[0] == pytest.approx(100.0)
    a = SectionMesh.from_points(x, z, np.array([10.0, 100.0, 1000.0]), quantity="chargeability", unit="mV/V")
    assert a.values[0] == pytest.approx(370.0)
    assert a.unit == "mV/V"


def test_resistivity_rejects_non_positive():
    with pytest.raises(ValueError, match="positive"):
        SectionMesh.from_points(np.array([0, 1, 0.0]), np.array([0, 0, -1.0]), np.array([1.0, 0.0, 5.0]))


def test_from_points_degenerate_input():
    with pytest.raises(ValueError, match="3 points"):
        SectionMesh.from_points(np.array([0, 1.0]), np.array([0, 1.0]), np.ones(2))
    with pytest.raises(ValueError, match="collinear"):
        SectionMesh.from_points(np.arange(5.0), np.arange(5.0), np.ones(5))


def test_constructor_validates_shapes():
    v = np.zeros((3, 2))
    with pytest.raises(ValueError):
        SectionMesh(np.zeros((3, 3)), np.zeros((1, 4), int), np.zeros(1))
    with pytest.raises(ValueError):
        SectionMesh(v, np.zeros((1, 3), int), np.zeros(1))
    with pytest.raises(ValueError):
        SectionMesh(v, np.zeros((1, 4), int), np.zeros(2))


def test_quad_cells_and_polygons():
    verts = np.array([[0, 0], [2, 0], [2, 1], [0, 1], [4, 0.0]])
    cells = np.array([[0, 1, 2, 3], [1, 4, 2, -1]])
    m = SectionMesh(verts, cells, np.array([5.0, 7.0]))
    polys = m.polygons()
    assert [p.shape for p in polys] == [(4, 2), (3, 2)]
    assert m.value_at(1, 0.5) == 5.0
    assert m.value_at(3, 0.2) == 7.0
    assert np.isnan(m.value_at(1, 1.5))
    assert m.bounds() == (0.0, 4.0, 0.0, 1.0)
