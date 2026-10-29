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


def test_default_keeps_graded_mesh():
    thick = 0.5 * 1.4 ** np.arange(25)
    depth = np.r_[0.0, np.cumsum(thick)]
    xs, zs = np.meshgrid(np.arange(60) * 0.5, -depth)
    m = SectionMesh.from_points(xs.ravel(), zs.ravel(), np.full(xs.size, 100.0))
    assert len(m.cells) >= 0.99 * (59 * 25 * 2)
    mid = -(depth[-1] + depth[-2]) / 2
    assert m.value_at(10.1, mid) == pytest.approx(100.0)


def test_default_removes_trapezoid_bridge():
    # trapezoid outline (wide top, narrow bottom) with a deep notch cut into the middle
    pts = []
    for k in range(8):
        half = 30 - 1.5 * k
        xs = np.arange(-half, half + 1e-9, 1.0)
        for x in xs:
            if k >= 3 and abs(x) < 8:
                continue
            pts.append((x, -float(k)))
    pts = np.array(pts)
    m = SectionMesh.from_points(pts[:, 0], pts[:, 1], np.full(len(pts), 50.0))
    assert np.isnan(m.value_at(0.0, -5.0))
    assert m.value_at(20.0, -1.5) == pytest.approx(50.0)
    # the old global rule (3 x median nearest-neighbour distance = 3) also removes the bridge
    g = SectionMesh.from_points(pts[:, 0], pts[:, 1], np.full(len(pts), 50.0), max_edge=3.0)
    assert np.isnan(g.value_at(0.0, -5.0))


def test_all_filtered_raises():
    with pytest.raises(ValueError, match="filtered"):
        SectionMesh.from_points(np.array([0, 1, 0.0]), np.array([0, 0, -1.0]), np.ones(3), max_edge=0.1)
