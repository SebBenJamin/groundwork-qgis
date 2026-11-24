import numpy as np
import pytest

from groundwork_geophysics.core.section_mesh import SectionMesh


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


def _bent_model_points():
    """Cell centres of a model under a hill (elevation space): fine rows near the surface,
    coarse rows at depth, every row following the topography."""
    s = np.arange(1.25, 200.0, 2.5)
    topo = 60.0 + 4.0 * np.sin(np.pi * s / 200.0)                      # hill in the middle
    edges = np.r_[0.0, np.cumsum(0.5 * 1.1 ** np.arange(30))]
    depth = 0.5 * (edges[:-1] + edges[1:])
    ss, dd = np.meshgrid(s, depth)
    zz = np.interp(ss, s, topo) - dd
    return ss.ravel(), zz.ravel(), s, topo, depth


def test_default_drops_hull_slivers_of_bent_rows():
    """The convex hull bridges the bulging bottom row (and the top row in hollows) with
    near-collinear slivers; they must not add area outside the rows."""
    x, z, s, topo, depth = _bent_model_points()
    m = SectionMesh.from_points(x, z, np.full(x.size, 30.0))
    cent = m.vertices[m.cells[:, :3]].mean(axis=1)
    top = np.interp(cent[:, 0], s, topo) - depth[0]
    bottom = np.interp(cent[:, 0], s, topo) - depth[-1]
    tol = 1e-6
    assert (cent[:, 1] >= bottom - tol).all(), "cells below the deepest row"
    assert (cent[:, 1] <= top + tol).all(), "cells above the shallowest row"
    # nothing inside the rows is lost: a regular grid splits into 2 triangles per cell
    assert len(m.cells) == 2 * (len(s) - 1) * (len(depth) - 1)


def _stepped():
    """Two quads with their own vertices: top z 10 over x 0..5, 12 over x 5..10."""
    from groundwork_geophysics.core.cell_centres import quads
    verts, cells = quads(np.array([[0.0, 5.0, 0.0, 10.0], [5.0, 10.0, 0.0, 12.0]]))
    return SectionMesh(verts, cells, np.array([10.0, 20.0]))


def test_top_edge_and_below_top():
    m = _stepped()
    s, z = m.top_edge()
    assert s.tolist() == [0.0, 5.0, 5.0, 10.0] and z.tolist() == [10.0, 10.0, 12.0, 12.0]
    below = m.below_top()
    v = below.vertices
    on_top = np.isin(np.arange(len(v)), m.cells[:, 2:].ravel())     # each quad's two top corners
    assert (v[on_top, 1] == 0.0).all()
    assert sorted(v[~on_top, 1].tolist()) == [10.0, 10.0, 12.0, 12.0]
    assert (v[:, 1] >= 0.0).all() and (v[:, 0] == m.vertices[:, 0]).all()


def test_hung_from_its_own_top_keeps_the_shape():
    m = _stepped()
    s, z = m.top_edge()
    back = m.below_top().depth_to_elevation(s, z - 12.0)
    np.testing.assert_allclose(back.vertices, m.vertices - [0.0, 12.0])
    # a triangulated mesh under a hill: the top row is its top edge
    x, zz, srow, topo, depth = _bent_model_points()
    tri = SectionMesh.from_points(x, zz, np.full(x.size, 30.0))
    ts, tz = tri.top_edge()
    np.testing.assert_allclose(ts, srow)
    np.testing.assert_allclose(tz, topo - depth[0])
    back = tri.below_top().depth_to_elevation(ts, tz)
    np.testing.assert_allclose(back.vertices, tri.vertices, atol=1e-9)


def test_shared_vertices_do_not_fold_at_a_surface_step():
    """A grid whose cells share vertices, in any cell order, hangs from a stepped surface
    without inverting a cell edge: every vertex at one x takes the same surface value."""
    xs, ds = np.arange(5.0), np.arange(4.0)                  # 4 columns x 3 rows of quads
    verts = np.array([[x, d] for d in ds for x in xs])
    node = lambda i, j: j * len(xs) + i                       # noqa: E731
    cells = np.array([[node(i, j), node(i + 1, j), node(i + 1, j + 1), node(i, j + 1)]
                      for j in range(3) for i in range(4)])
    rng = np.random.default_rng(0)
    for _ in range(20):
        order = rng.permutation(len(cells))
        m = SectionMesh(verts, cells[order], np.ones(len(cells)))
        hung = m.depth_to_elevation(np.array([0.0, 2.0, 2.0, 4.0]),
                                    np.array([10.0, 10.0, 15.0, 15.0]))
        top = hung.vertices[:, 1] + np.abs(m.vertices[:, 1])   # the surface each vertex took
        for x in xs:
            assert np.ptp(top[m.vertices[:, 0] == x]) == 0.0, (x, order)


def test_point_mesh_keeps_the_middle_coverage():
    """A triangle gets the middle of its corners' coverages (nan counted lowest): one
    unresolved corner (an isolated ray-less cell) leaves no hole; two make the edge."""
    x, z = [0.0, 1.0, 0.0, 1.0], [0.0, 0.0, 1.0, 1.0]
    v = [100.0, 200.0, 300.0, 400.0]
    cov = [1.0, 2.0, np.nan, 3.0]
    m = SectionMesh.from_points(x, z, v, coverage=cov, quantity="p_velocity", unit="m/s")
    assert m.coverage is not None and len(m.coverage) == len(m.values)
    for tri, c, val in zip(m.cells[:, :3], m.coverage, m.values):
        corners = np.sort(np.nan_to_num(np.asarray(cov)[tri], nan=-np.inf))
        middle = corners[1]
        assert (np.isnan(c) if np.isinf(middle) else c == middle)
        assert val == pytest.approx(np.asarray(v)[tri].mean())   # arithmetic, not log
    two_nan = SectionMesh.from_points([0, 1, 0], [0, 0, 1], [1.0, 2, 3],
                                      coverage=[np.nan, np.nan, 5.0], quantity="p_velocity")
    assert np.isnan(two_nan.coverage).all()


def test_velocity_points_free_of_resistivity_rule():
    from groundwork_geophysics.readers.base import mesh_from_points
    mesh, _n, _kind = mesh_from_points([0, 1, 0, 1], [0, 0, 1, 1], [0.0, 200, 300, 400],
                                       "v.txt", quantity="p_velocity", unit="m/s")
    assert mesh.quantity == "p_velocity"


def test_mesh_from_points_puts_minus_inf_coverage_below_the_rest():
    """-inf (no ray at all, as pyGIMLi writes it) must fade like low coverage, not count as
    unknown (nan, drawn in full): it becomes one unit below the lowest finite coverage."""
    from groundwork_geophysics.readers.base import mesh_from_points
    mesh, _n, _kind = mesh_from_points([0, 1, 0, 1, 2], [0, 0, 1, 1, 0],
                                       [100.0, 200, 300, 400, 500], "v.txt",
                                       quantity="p_velocity", unit="m/s",
                                       coverage=[-np.inf, 1.0, 2.0, 3.0, np.nan],
                                       coverage_cut=1.5)
    assert np.isfinite(mesh.coverage).any() and not np.isinf(mesh.coverage).any()
    assert np.nanmin(mesh.coverage) >= 0.0 - 1e-9          # -inf -> 1.0 - 1 = 0.0
    assert mesh.coverage_cut == 1.5


def test_bounds_are_worked_out_once_per_mesh():
    # every redraw asks for them; a big model took over a second each time
    m = SectionMesh.from_points(*grid_points())
    assert m.bounds() is m.bounds()


def test_a_moved_copy_of_a_mesh_has_its_own_bounds():
    from dataclasses import replace
    m = SectionMesh.from_points(*grid_points())
    m.bounds()
    moved = replace(m, vertices=m.vertices + [100.0, 10.0])
    assert moved.bounds() == pytest.approx((100, 110, 5, 10))
