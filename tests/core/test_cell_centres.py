"""Cell reconstruction from cell-centre models (0.1.1, finding F3)."""
import time

import numpy as np
import pytest

from geophysics_workbench.core.section_mesh import SectionMesh


def _cell_box(mesh, i):
    p = mesh.vertices[mesh.cells[i]]
    return p[:, 0].min(), p[:, 0].max(), p[:, 1].min(), p[:, 1].max()


def test_rows_with_wider_cells_at_depth():
    # top row: 2 m cells over 0..8; second row: 4 m cells over the same 0..8
    x = np.array([1, 3, 5, 7, 2, 6.0])
    z = np.array([-0.5, -0.5, -0.5, -0.5, -1.5, -1.5])
    v = np.arange(1, 7, dtype=float) * 10
    mesh, kind = SectionMesh.from_cell_centres(x, z, v, z_kind="elevation")
    assert kind == "rows"
    assert len(mesh.cells) == len(x)
    assert mesh.bounds() == pytest.approx((0, 8, -2, 0))
    top = [_cell_box(mesh, i) for i in range(4)]
    deep = [_cell_box(mesh, i) for i in range(4, 6)]
    assert (min(b[0] for b in top), max(b[1] for b in top)) == pytest.approx((0, 8))
    assert (min(b[0] for b in deep), max(b[1] for b in deep)) == pytest.approx((0, 8))
    assert deep[0] == pytest.approx((0, 4, -2, -1))
    assert mesh.value_at(3.9, -1.9) == 50.0 and mesh.value_at(0.1, -0.1) == 10.0


def test_depth_rows_start_at_the_surface():
    x, z = np.meshgrid([1.25, 3.75, 6.25], [0.25, 0.775, 1.353])
    mesh, kind = SectionMesh.from_cell_centres(x.ravel(), z.ravel(), np.full(9, 50.0),
                                               z_kind="depth")
    assert kind == "rows"
    xmin, xmax, zmin, zmax = mesh.bounds()
    assert zmin == 0.0
    assert zmax == pytest.approx(1.353 + (1.353 - 0.775) / 2)
    assert (xmin, xmax) == pytest.approx((0, 7.5))


def test_columns_follow_topography():
    # three columns, each shifted up with the ground: no common rows
    cols = []
    for k, x0 in enumerate([1.0, 3.0, 5.0]):
        for z0 in (-0.5, -1.5, -3.0):
            cols.append((x0, z0 + 0.37 * k))
    pts = np.array(cols)
    mesh, kind = SectionMesh.from_cell_centres(pts[:, 0], pts[:, 1], np.full(len(pts), 20.0),
                                               z_kind="elevation")
    assert kind == "columns"
    assert len(mesh.cells) == len(pts)
    xmin, xmax, _, _ = mesh.bounds()
    assert (xmin, xmax) == pytest.approx((0, 6))
    # first column: edges at -1.0 / -2.25, top half a gap above, bottom half a gap below
    assert _cell_box(mesh, 0) == pytest.approx((0, 2, -1.0, 0.0))
    assert _cell_box(mesh, 2) == pytest.approx((0, 2, -3.75, -2.25))


def test_scattered_centres_use_delaunay_unchanged():
    rng = np.random.default_rng(7)
    x, z = rng.uniform(0, 50, 300), rng.uniform(-20, 0, 300)
    v = rng.uniform(10, 500, 300)
    mesh, kind = SectionMesh.from_cell_centres(x, z, v, z_kind="elevation")
    ref = SectionMesh.from_points(x, z, v)
    assert kind == "delaunay"
    np.testing.assert_array_equal(mesh.vertices, ref.vertices)
    np.testing.assert_array_equal(mesh.cells, ref.cells)
    np.testing.assert_array_equal(mesh.values, ref.values)


def test_masked_centre_keeps_a_nan_quad():
    x, z = np.meshgrid([1.0, 3.0, 5.0], [-0.5, -1.5])
    v = np.full(6, 40.0)
    v[4] = np.nan
    mesh, kind = SectionMesh.from_cell_centres(x.ravel(), z.ravel(), v, z_kind="elevation")
    assert kind == "rows" and len(mesh.cells) == 6
    assert np.isnan(mesh.values[4]) and np.isfinite(np.delete(mesh.values, 4)).all()
    assert np.isnan(mesh.value_at(3.0, -1.5))
    assert mesh.value_at(3.0, -0.5) == 40.0


def test_masked_scattered_points_are_dropped_for_delaunay():
    rng = np.random.default_rng(3)
    x, z = rng.uniform(0, 50, 100), rng.uniform(-20, 0, 100)
    v = rng.uniform(10, 500, 100)
    v[5] = np.nan
    mesh, kind = SectionMesh.from_cell_centres(x, z, v)
    keep = np.isfinite(v)
    ref = SectionMesh.from_points(x[keep], z[keep], v[keep])
    assert kind == "delaunay"
    np.testing.assert_array_equal(mesh.cells, ref.cells)


def test_hundred_thousand_centres_build_fast():
    x, z = np.meshgrid(np.arange(500) * 0.5 + 0.25, -(np.arange(200) * 0.5 + 0.25))
    v = np.full(x.size, 100.0)
    t0 = time.perf_counter()
    mesh, kind = SectionMesh.from_cell_centres(x.ravel(), z.ravel(), v)
    elapsed = time.perf_counter() - t0
    assert kind == "rows" and len(mesh.cells) == 100_000
    assert elapsed < 1.0, f"{elapsed:.2f} s"


def _topography_columns(xs, top, depths):
    X, D = np.meshgrid(xs, depths)
    return X.ravel(), np.round(top(X) - D, 3).ravel()


def test_mirror_symmetric_topography_is_not_read_as_rows():
    # 40 columns under a symmetric hill: every z occurs exactly twice (column j and its
    # mirror), which once passed as rows of two 97.5 m wide cells
    xs = 1.25 + 2.5 * np.arange(40)
    depths = np.cumsum(0.5 * 1.1 ** np.arange(10)) - 0.25
    x, z = _topography_columns(xs, lambda X: 50 + 5 * np.sin(np.pi * X / 100), depths)
    mesh, kind = SectionMesh.from_cell_centres(x, z, np.full(x.size, 30.0), z_kind="elevation")
    assert kind == "columns"
    widths = np.ptp(mesh.vertices[mesh.cells][..., 0], axis=1)
    assert widths == pytest.approx(2.5)
    assert mesh.bounds()[:2] == pytest.approx((0.0, 100.0))


def test_coarser_columns_at_depth_fall_back_to_delaunay():
    # fine columns near the surface, coarser columns in between at depth: grouped by x
    # they would draw as interleaved strips with gaps
    xf = 1.25 + 2.5 * np.arange(40)
    pts = [(x0, 50 + 0.03 * x0 - d) for x0 in xf for d in (0.25, 0.75, 1.25, 1.75)]
    pts += [(x0, 50 + 0.03 * x0 - d) for x0 in 2.5 + 5 * np.arange(20) for d in (3, 5, 7, 9)]
    pts = np.round(np.array(pts), 3)
    v = np.full(len(pts), 30.0)
    mesh, kind = SectionMesh.from_cell_centres(pts[:, 0], pts[:, 1], v, z_kind="elevation")
    assert kind == "delaunay"
    ref = SectionMesh.from_points(pts[:, 0], pts[:, 1], v)
    np.testing.assert_array_equal(mesh.cells, ref.cells)
