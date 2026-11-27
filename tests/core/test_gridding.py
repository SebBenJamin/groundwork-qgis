"""Gridded display of section models: smooth field, masks, levels and contour lines."""
import warnings

import numpy as np
import pytest

from groundwork_geophysics.core.colors import ColorScale
from groundwork_geophysics.core.gridding import (contour_lines, default_levels, grid_model,
                                                grid_shape)
from groundwork_geophysics.core.section_mesh import SectionMesh


def regular_mesh(nx=10, nz=5, fn=lambda s, z: s, x0=0.0, z0=-5.0, d=1.0):
    xs, zs = x0 + d * np.arange(nx + 1), z0 + d * np.arange(nz + 1)
    vx, vz = np.meshgrid(xs, zs)
    verts = np.column_stack([vx.ravel(), vz.ravel()])
    cells, vals = [], []
    for j in range(nz):
        for i in range(nx):
            a = j * (nx + 1) + i
            cells.append([a, a + 1, a + nx + 2, a + nx + 1])
            vals.append(fn(x0 + d * (i + 0.5), z0 + d * (j + 0.5)))
    return SectionMesh(verts, np.array(cells), np.array(vals, float), quantity="x", unit="")


def test_grid_inside_and_above_topo_empty():
    mesh = regular_mesh()
    topo = (np.array([0.0, 10.0]), np.array([-1.0, -3.0]))       # slopes down to the right
    g = grid_model(mesh, topo, (21, 11), log=False)
    assert g.values.shape == (11, 21) and g.cell.shape == (11, 21)
    s, z = np.meshgrid(g.s, g.z)
    above = z > np.interp(s, *topo) + 1e-9
    assert np.isnan(g.values[above]).all()
    assert np.isfinite(g.values[~above & (g.cell >= 0)]).all()


def test_concave_mesh_not_bridged():
    mesh = regular_mesh(4, 4)
    keep = [i for i in range(16) if not (i % 4 >= 2 and i // 4 >= 2)]     # L-shape
    mesh = SectionMesh(mesh.vertices, mesh.cells[keep], mesh.values[keep], quantity="x", unit="")
    g = grid_model(mesh, None, (41, 41), log=False)
    s, z = np.meshgrid(g.s, g.z)
    notch = (s > 2.2) & (z > -2.8)
    assert np.isnan(g.values[notch]).all() and (g.cell[notch] == -1).all()


def test_nan_cells_stay_empty():
    mesh = regular_mesh()
    mesh.values[12] = np.nan                                        # cell (2, 1): s 2..3, z -4..-3
    g = grid_model(mesh, None, (101, 51), log=False)
    s, z = np.meshgrid(g.s, g.z)
    inside = (s > 2.05) & (s < 2.95) & (z > -3.95) & (z < -3.05)
    assert np.isnan(g.values[inside]).all()


def test_log_nonpositive():
    mesh = regular_mesh(fn=lambda s, z: s - 3.0)                   # some values <= 0
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        g = grid_model(mesh, None, (21, 11), log=True)
    assert np.isnan(g.values[g.cell >= 0]).any() and np.isfinite(g.values).any()


def test_smooth_matches_cell_values_at_centres():
    mesh = regular_mesh(fn=lambda s, z: 2 * s + z)
    g = grid_model(mesh, None, (21, 11), log=False)                 # nodes every 0.5 m
    i, j = list(g.s).index(2.5), list(g.z).index(-3.5)
    assert g.values[j, i] == pytest.approx(2 * 2.5 - 3.5, abs=1e-6)


def test_grid_size_capped():
    mesh = regular_mesh(500, 400, d=0.5)                            # 200k cells
    nx, nz = grid_shape(mesh, None)
    assert nx * nz <= 250_000 and nx > 10 and nz > 10
    nx, nz = grid_shape(regular_mesh(1, 1), None)
    assert nx >= 2 and nz >= 2


def test_default_levels_log_and_linear():
    assert default_levels(ColorScale(vmin=1, vmax=1000, log=True), None) == pytest.approx(
        [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000])
    assert default_levels(ColorScale(vmin=10, vmax=1000, log=True), 0.5) == pytest.approx(
        [10, 10 ** 1.5, 100, 10 ** 2.5, 1000])
    lin = default_levels(ColorScale(vmin=0, vmax=10, log=False), None)
    assert lin[0] >= 0 and lin[-1] <= 10 and 4 <= len(lin) <= 11
    assert np.allclose(np.diff(lin), lin[1] - lin[0])
    assert default_levels(ColorScale(vmin=0, vmax=10, log=False), 2.5) == [0, 2.5, 5, 7.5, 10]


def test_contour_lines_level_position():
    mesh = regular_mesh(fn=lambda s, z: s)
    g = grid_model(mesh, None, (41, 21), log=False)
    [(level, lines)] = contour_lines(g, [5.0], log=False)
    assert level == 5.0 and lines
    pts = np.vstack(lines)
    assert np.allclose(pts[:, 0], 5.0, atol=1e-6)


def test_mesh_with_duplicated_vertices_grids_and_blends():
    """R2 models store every cell with its own corners: grid it as one connected mesh."""
    base = regular_mesh(2, 1, fn=lambda s, z: s)                    # values 0.5 and 1.5
    verts = base.vertices[base.cells].reshape(-1, 2)                # 4 own corners per cell
    cells = np.arange(8).reshape(2, 4)
    mesh = SectionMesh(verts, cells, base.values, quantity="x", unit="")
    g = grid_model(mesh, None, (5, 3), log=False)
    i, j = list(g.s).index(1.0), 1                                  # on the shared edge
    assert g.values[j, i] == pytest.approx(1.0)


def test_ungriddable_mesh_raises_value_error():
    verts = np.array([[0.0, 0.0], [1.0, 0.0], [2.0, 0.0]])          # all collinear
    mesh = SectionMesh(verts, np.array([[0, 1, 2, -1]]), np.array([1.0]), quantity="x", unit="")
    with pytest.raises(ValueError):
        grid_model(mesh, None, (5, 5), log=False)


def test_levels_capped():
    assert len(default_levels(ColorScale(vmin=0, vmax=5000, log=False), 0.001)) <= 100
    assert len(default_levels(ColorScale(vmin=300, vmax=5000, log=False), 0.25)) <= 100
    assert len(default_levels(ColorScale(vmin=1, vmax=1e6, log=True), 0.001)) <= 100


def test_field_reaches_up_to_the_ground_over_a_stepped_mesh_top():
    """Flat-topped cells leave steps under a sloping ground: the field fills them up to the
    ground, from the top cell of each column (never above the ground, never past the mesh
    ends)."""
    mesh = regular_mesh(10, 3, fn=lambda s, z: s, z0=-3.0)          # top at z = 0
    topo = (np.array([0.0, 10.0]), np.array([0.0, 2.0]))           # ground rises to 2 m
    g = grid_model(mesh, topo, (21, 11), log=False, fill_to_ground=True)
    s, z = np.meshgrid(g.s, g.z)
    ground = np.interp(s, *topo)
    between = (z > 0.01) & (z <= ground - 1e-9)
    assert between.any() and np.isfinite(g.values[between]).all()
    assert np.isnan(g.values[z > ground + 1e-9]).all()
    assert (g.cell[between] >= 0).all()                             # treated as inside
    plain = grid_model(mesh, topo, (21, 11), log=False)
    assert plain.z.max() == pytest.approx(0.0)                      # off by default: mesh only


def test_default_threshold_prefers_the_files_cut():
    from groundwork_geophysics.core.gridding import default_threshold
    assert default_threshold([0, 1, 2, 3], cut=1.5) == 1.5
    assert default_threshold([0, 1, 2, 3], cut=None) == default_threshold([0, 1, 2, 3])
    assert np.isfinite(default_threshold([np.nan, 1.0], cut=float("nan")))


def test_automatic_grid_size_is_worked_out_once_per_mesh(monkeypatch):
    # every redraw of a smooth or contour display asks for it
    from groundwork_geophysics.core import gridding
    m = regular_mesh()
    calls = []
    real = gridding._longest_edges
    monkeypatch.setattr(gridding, "_longest_edges", lambda mesh: calls.append(1) or real(mesh))
    assert grid_shape(m, None) == grid_shape(m, None)
    assert len(calls) == 1
    grid_shape(m, 0.5)                                  # an own cell needs no guess
    assert len(calls) == 1


def test_grid_nodes_are_located_as_matplotlib_locates_them():
    # the grid's own locator (big models: matplotlib's TriFinder took 15 s) finds the same
    # triangle for every node, or one that shares the edge the node lies on
    import matplotlib.tri as mtri

    from groundwork_geophysics.core.gridding import locate_nodes
    rng = np.random.default_rng(3)
    pts = rng.uniform([0, -20], [100, 0], size=(400, 2))
    tri = mtri.Triangulation(pts[:, 0], pts[:, 1])
    s, z = np.linspace(-5, 105, 137), np.linspace(-25, 3, 41)
    S, Z = np.meshgrid(s, z)
    t, w = locate_nodes(pts, tri.triangles, s, z)
    ref = tri.get_trifinder()(S.ravel(), Z.ravel())
    assert ((t >= 0) == (ref >= 0)).all()
    inside = t >= 0
    differ = inside & (t != ref)
    assert (w[differ].min(axis=1) < 1e-9).all()             # only on a shared edge
    corners = pts[tri.triangles[t[inside]]]
    back = (w[inside, :, None] * corners).sum(axis=1)
    assert np.allclose(back, np.column_stack([S.ravel(), Z.ravel()])[inside])


# -- gridding methods (nearest, inverse distance, spline, kriging) ---------------------------
def _layered(nx=12, nz=6):
    return regular_mesh(nx, nz, fn=lambda s, z: 50 + 20 * np.sin(s / 3) + 4 * z)


def test_linear_method_is_todays_grid():
    from groundwork_geophysics.core.interpolators import Interpolation
    mesh = _layered()
    a = grid_model(mesh, None, (25, 13), log=False)
    b = grid_model(mesh, None, (25, 13), log=False, interp=Interpolation())
    assert np.array_equal(a.values, b.values, equal_nan=True) and b.note == ""


@pytest.mark.parametrize("method", ["nearest", "idw", "spline", "kriging"])
def test_each_method_fills_the_same_nodes_as_linear(method):
    from groundwork_geophysics.core.interpolators import Interpolation
    mesh = _layered()
    mesh.values[14] = np.nan                                       # one empty cell
    topo = (np.array([0.0, 12.0]), np.array([1.0, -1.5]))          # cuts the top corner
    linear = grid_model(mesh, topo, (49, 25), log=False, fill_to_ground=True)
    other = grid_model(mesh, topo, (49, 25), log=False, fill_to_ground=True,
                       interp=Interpolation(method=method))
    assert other.note == ""
    assert np.array_equal(np.isfinite(other.values), np.isfinite(linear.values))
    assert np.nanmax(np.abs(other.values - linear.values)) < 15          # same field, roughly


def test_nearest_grid_takes_the_cell_values():
    from groundwork_geophysics.core.interpolators import Interpolation
    mesh = regular_mesh(fn=lambda s, z: 10 * s + z)
    g = grid_model(mesh, None, (41, 21), log=False, interp=Interpolation(method="nearest"),)
    i, j = list(g.s).index(2.5), list(g.z).index(-3.5)                # a cell centre
    assert g.values[j, i] == pytest.approx(10 * 2.5 - 3.5)


def test_a_failed_fit_falls_back_to_linear_and_says_so():
    from groundwork_geophysics.core.interpolators import Interpolation
    mesh = regular_mesh(fn=lambda s, z: 7.0)                          # nothing varies
    linear = grid_model(mesh, None, (21, 11), log=False)
    g = grid_model(mesh, None, (21, 11), log=False, interp=Interpolation(method="kriging"))
    assert np.array_equal(g.values, linear.values, equal_nan=True)
    assert "kriging" in g.note.lower() and "linear" in g.note.lower()


def test_methods_work_in_log10_on_a_log_scale():
    from groundwork_geophysics.core.interpolators import Interpolation
    mesh = regular_mesh(2, 1, fn=lambda s, z: 10.0 if s < 1 else 1000.0)
    g = grid_model(mesh, None, (21, 3), log=True,
                   interp=Interpolation(method="idw", anisotropy=1.0))
    mid = g.values[1, list(g.s).index(1.0)]
    assert mid == pytest.approx(100.0, rel=1e-6)                     # geometric mean


def test_kriging_reports_what_it_fitted():
    from groundwork_geophysics.core.interpolators import Interpolation
    g = grid_model(_layered(), None, (25, 13), log=False,
                   interp=Interpolation(method="kriging"))
    assert set(g.fitted) >= {"range", "sill", "nugget", "anisotropy"}


def test_cell_aspect_is_the_default_anisotropy():
    from groundwork_geophysics.core.gridding import cell_aspect
    mesh = regular_mesh(4, 4, d=1.0)
    mesh.vertices[:, 0] *= 3                                          # 3 m wide, 1 m tall
    assert cell_aspect(mesh) == pytest.approx(3.0)


def test_running_out_of_memory_falls_back_to_linear(monkeypatch):
    from groundwork_geophysics.core import interpolators
    from groundwork_geophysics.core.interpolators import Interpolation

    def no_memory(*_a, **_k):
        raise MemoryError()

    monkeypatch.setattr(interpolators, "interpolate", no_memory)
    mesh = _layered()
    linear = grid_model(mesh, None, (25, 13), log=False)
    g = grid_model(mesh, None, (25, 13), log=False, interp=Interpolation(method="idw"))
    assert np.array_equal(g.values, linear.values, equal_nan=True)
    assert "not enough memory" in g.note and "()" not in g.note


def test_the_cell_used_is_the_typed_one_unless_the_grid_is_too_big():
    from groundwork_geophysics.core.gridding import MAX_GRID_NODES, grid_cell_used
    mesh = regular_mesh(200, 40)                                    # 200 m x 40 m
    assert grid_cell_used(mesh, 1.0) == pytest.approx(1.0)
    used = grid_cell_used(mesh, 0.05)                               # 4001 x 801 nodes asked
    assert used > 0.17 and used < 0.2
    nx, nz = grid_shape(mesh, 0.05)
    assert nx * nz <= MAX_GRID_NODES
    assert used == pytest.approx(max(200.0 / (nx - 1), 40.0 / (nz - 1)), rel=0.02)
