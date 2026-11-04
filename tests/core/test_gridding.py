"""Gridded display of section models: smooth field, masks, levels and contour lines."""
import warnings

import numpy as np
import pytest

from geophysics_workbench.core.colors import ColorScale
from geophysics_workbench.core.gridding import (contour_lines, default_levels, grid_model,
                                                grid_shape)
from geophysics_workbench.core.section_mesh import SectionMesh


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
