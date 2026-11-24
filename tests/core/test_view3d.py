"""3D geometry for the QGIS 3D view: model cells as vertical rings under the profile, and
borehole log intervals as vertical segments at the borehole's map position."""
import math

import numpy as np
import pytest

from groundwork_geophysics.core.chainage import Chainage
from groundwork_geophysics.core.context import LogInterval, ProjectedPoint
from groundwork_geophysics.core.section_mesh import SectionMesh
from groundwork_geophysics.core.view3d import borehole_intervals, curtain_cells

# an L-shaped profile: 10 m east, then 10 m north
L_SHAPE = Chainage(np.array([[100.0, 200.0], [110.0, 200.0], [110.0, 210.0]]))
RGBA = np.array([[10, 20, 30, 255], [158, 1, 66, 255]], dtype=np.uint8)


def _mesh(coverage=None, cut=None):
    verts = np.array([[0.0, 50.0], [15.0, 50.0], [15.0, 40.0], [0.0, 40.0]])
    cells = np.array([[0, 1, 2, -1], [0, 2, 3, -1]])
    return SectionMesh(verts, cells, np.array([400.0, 3000.0]), "p_velocity", "m/s",
                       coverage=coverage, coverage_cut=cut)


def test_cell_corners_follow_the_profile_and_keep_their_elevation():
    cells = curtain_cells(_mesh(), L_SHAPE, RGBA, None)
    assert len(cells) == 2
    ring = cells[0].ring
    assert ring[0] == (100.0, 200.0, 50.0)
    assert ring[1] == (110.0, 205.0, 50.0)          # 15 m along: 5 m past the bend, north
    assert ring[2] == (110.0, 205.0, 40.0)
    assert ring[-1] == ring[0]                       # closed
    assert cells[1].value == 3000.0


def test_colours_are_the_scale_rows_as_0_to_255():
    cells = curtain_cells(_mesh(), L_SHAPE, RGBA, None)
    assert cells[0].rgb == (10, 20, 30)
    assert cells[1].rgb == (158, 1, 66)              # not (158, 255, 66)


def test_without_a_threshold_every_cell_is_kept_and_marked():
    mesh = _mesh(coverage=np.array([-3.0, 1.0]), cut=0.0)
    cells = curtain_cells(mesh, L_SHAPE, RGBA, None)
    assert [c.resolved for c in cells] == [False, True]
    assert cells[0].coverage == -3.0


def test_a_threshold_leaves_out_cells_below_it_but_keeps_unknown_coverage():
    mesh = _mesh(coverage=np.array([-3.0, math.nan]), cut=0.0)
    cells = curtain_cells(mesh, L_SHAPE, RGBA, 0.0)
    assert len(cells) == 1 and cells[0].value == 3000.0 and cells[0].resolved
    assert math.isnan(cells[0].coverage)


def test_a_model_without_coverage_is_all_resolved():
    cells = curtain_cells(_mesh(), L_SHAPE, RGBA, 0.0)
    assert len(cells) == 2 and all(c.resolved for c in cells)
    assert all(math.isnan(c.coverage) for c in cells)


class _Symbol:
    def __init__(self, rgb):
        self.rgb = rgb


def _colour(text, symbol):
    return symbol.rgb if symbol is not None else {"clay": (128, 128, 128), "": (5, 6, 7)}[text]


def _borehole(**kw):
    base = dict(s=5.0, offset=2.0, label="B1", kind="borehole", z_top=60.0,
                log=[LogInterval(0.0, 2.0, "sand", _Symbol((230, 200, 80))),
                     LogInterval(2.0, 5.5, "clay", None)],
                x=501.0, y=7002.0)
    base.update(kw)
    return ProjectedPoint(**base)


def test_intervals_stand_at_the_borehole_from_its_collar_down():
    out = borehole_intervals(_borehole(), None, _colour)
    assert [(i.x, i.y, i.z_top, i.z_bottom, i.text) for i in out] == [
        (501.0, 7002.0, 60.0, 58.0, "sand"), (501.0, 7002.0, 58.0, 54.5, "clay")]
    assert out[0].rgb == (230, 200, 80) and out[1].rgb == (128, 128, 128)
    assert (out[1].top, out[1].bottom) == (2.0, 5.5)


def test_without_a_collar_height_the_surface_is_used_else_nothing():
    assert borehole_intervals(_borehole(z_top=None), 70.0, _colour)[0].z_top == 70.0
    assert borehole_intervals(_borehole(z_top=None), None, _colour) == []


def test_a_borehole_without_intervals_but_a_total_depth_is_one_segment():
    out = borehole_intervals(_borehole(log=[], total_depth=12.0), None, _colour)
    assert [(i.z_top, i.z_bottom, i.rgb, i.text) for i in out] == [(60.0, 48.0, (5, 6, 7), "")]
    assert borehole_intervals(_borehole(log=[]), None, _colour) == []


def test_a_borehole_without_map_position_is_left_out():
    assert borehole_intervals(_borehole(x=None, y=None), None, _colour) == []


def test_cells_the_section_leaves_out_are_left_out_of_the_curtain():
    rgba = np.array([[10, 20, 30, 0], [158, 1, 66, 255]], dtype=np.uint8)   # NaN: alpha 0
    cells = curtain_cells(_mesh(), L_SHAPE, rgba, None)
    assert [c.value for c in cells] == [3000.0]


# -- the smooth field as points and lines (smooth / contours modes) -------------------------
def _grid_mesh():
    """20 x 10 quads over s 0..20, z 30..50; values 10..1000 rising with s, coverage
    falling with depth."""
    s = np.linspace(0.0, 20.0, 21)
    z = np.linspace(30.0, 50.0, 11)
    S, Z = np.meshgrid(s, z)
    verts = np.column_stack([S.ravel(), Z.ravel()])
    cells, values, coverage = [], [], []
    for j in range(10):
        for i in range(20):
            a = j * 21 + i
            cells.append([a, a + 1, a + 22, a + 21])
            values.append(10 ** (1 + 2 * (i + 0.5) / 20))
            coverage.append(float(j))                  # deeper rows: lower coverage
    return SectionMesh(verts, np.array(cells), np.array(values), "resistivity", "ohm.m",
                       coverage=np.array(coverage))


def _style(**kw):
    from types import SimpleNamespace

    from groundwork_geophysics.core.colors import ColorScale
    base = dict(scale=ColorScale("Spectral_r", 10.0, 1000.0, True), grid_cell=None,
                fade_mode="blank", contour_step=None, contour_major=(), contour_minor=())
    base.update(kw)
    return SimpleNamespace(**base)


STRAIGHT = Chainage(np.array([[500.0, 1000.0], [503.0, 1004.0], [506.0, 1008.0],
                              [509.0, 1012.0], [512.0, 1016.0]]))     # 20 m north-east


def _on_line(xyz, line=STRAIGHT):
    """Distance of each point from the straight line through ``line``'s ends."""
    a, b = line.xy[0], line.xy[-1]
    d = (b - a) / np.hypot(*(b - a))
    rel = xyz[:, :2] - a
    return np.abs(rel[:, 0] * d[1] - rel[:, 1] * d[0])


def test_the_field_is_the_sections_grid_and_leaves_out_above_ground():
    from groundwork_geophysics.core.view3d import field_grid
    topo = (np.array([0.0, 20.0]), np.array([45.0, 45.0]))
    grid = field_grid(_grid_mesh(), topo, _style(), None)
    S, Z = np.meshgrid(grid.s, grid.z)
    assert not np.isfinite(grid.values[Z > 45.0 + 1e-6]).any()
    assert np.isfinite(grid.values[Z < 44.0]).any()


def test_faded_nodes_are_left_out():
    from groundwork_geophysics.core.view3d import field_grid
    mesh = _grid_mesh()
    full = np.isfinite(field_grid(mesh, None, _style(), None).values).sum()
    faded = np.isfinite(field_grid(mesh, None, _style(), 5.0).values).sum()
    assert 0 < faded < full


def test_points_stand_under_the_line_in_the_section_colour():
    from groundwork_geophysics.core.view3d import field_grid, field_points
    style = _style()
    grid = field_grid(_grid_mesh(), None, style, None)
    pts = field_points(grid, STRAIGHT, style.scale)
    assert len(pts.value) > 100
    assert _on_line(pts.xyz).max() < 1e-6
    assert (pts.rgb == style.scale.rgba(pts.value)[:, :3]).all()
    assert pts.xyz[:, 2].min() >= 30.0 - 1e-9 and pts.xyz[:, 2].max() <= 50.0 + 1e-9


def test_points_are_thinned_to_the_spacing():
    from groundwork_geophysics.core.view3d import field_grid, field_points
    style = _style()
    grid = field_grid(_grid_mesh(), None, style, None)
    spacing = 4 * float(grid.s[1] - grid.s[0])
    dense = field_points(grid, STRAIGHT, style.scale, spacing=0.0)
    thin = field_points(grid, STRAIGHT, style.scale, spacing=spacing)
    assert len(dense.value) == np.isfinite(grid.values).sum()
    along = np.unique(np.round(np.hypot(*(thin.xyz[:, :2] - STRAIGHT.xy[0]).T), 9))
    across = np.unique(np.round(thin.xyz[:, 2], 9))
    assert np.diff(along).min() >= spacing - 1e-6
    assert np.diff(across).min() >= spacing - 1e-6
    assert len(thin.value) < len(dense.value) / 4


def test_contours_lie_under_the_line():
    from groundwork_geophysics.core.view3d import field_contours, field_grid
    style = _style()
    grid = field_grid(_grid_mesh(), None, style, None)
    lines = field_contours(grid, STRAIGHT, style.scale, [30.0, 100.0, 300.0])
    assert {level for level, _ in lines} == {30.0, 100.0, 300.0}
    for _level, xyz in lines:
        assert xyz.shape[1] == 3 and _on_line(xyz).max() < 1e-6


# -- two faces per curtain: an interpretation in the curtain's plane is never hidden ---------
def test_the_gap_grows_with_the_profile_within_limits():
    from groundwork_geophysics.core.view3d import curtain_gap
    assert curtain_gap(60.0) == pytest.approx(0.12)
    assert curtain_gap(10.0) == pytest.approx(0.05)
    assert curtain_gap(5000.0) == pytest.approx(0.5)


def test_each_side_sees_a_face_behind_the_plane():
    """A ring counter-clockwise in (s, z) faces the right of the line (south, for a line
    running east); it is moved to the left (north), so a viewer in the south sees it behind
    the plane, and its reversed copy, facing north, goes south."""
    from groundwork_geophysics.core.view3d import two_faces
    line = Chainage(np.array([[0.0, 0.0], [60.0, 0.0]]))
    ring_s, ring_z = [10.0, 20.0, 20.0, 10.0], [0.0, 0.0, 5.0, 5.0]   # counter-clockwise
    front, back = two_faces(ring_s, ring_z, line, 0.1)
    assert all(y == pytest.approx(0.1) for _x, y, _z in front)        # north of the line
    assert all(y == pytest.approx(-0.1) for _x, y, _z in back)        # south of it
    assert [(x, z) for x, _y, z in front] == [(10.0, 0.0), (20.0, 0.0), (20.0, 5.0),
                                              (10.0, 5.0), (10.0, 0.0)]
    assert [(x, z) for x, _y, z in back] == [(10.0, 0.0), (10.0, 5.0), (20.0, 5.0),
                                             (20.0, 0.0), (10.0, 0.0)]
    cw_front, _ = two_faces(ring_s[::-1], ring_z[::-1], line, 0.1)     # the same, either way
    assert cw_front == front


def test_the_faces_follow_a_bend():
    from groundwork_geophysics.core.view3d import two_faces
    corner = Chainage(np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]]))
    front, _ = two_faces([5.0, 15.0, 15.0, 5.0], [0.0, 0.0, 1.0, 1.0], corner, 0.1)
    x, y, _z = front[1]                       # s = 15: 5 m up the northward leg
    assert (x, y) == pytest.approx((9.9, 5.0))                        # left of it is west


def _mixed_mesh():
    """Quads both ways round, triangles, a cell without a value, coverage below and above."""
    verts = np.array([[0, 50], [5, 50], [5, 45], [0, 45], [10, 50], [10, 45], [12, 40],
                      [3, 40]], dtype=float)
    cells = np.array([[0, 1, 2, 3], [1, 4, 5, 2], [2, 5, 6, -1], [3, 2, 7, -1],
                      [2, 6, 7, -1]])
    return SectionMesh(verts, cells, np.array([10.0, 20.0, np.nan, 40.0, 50.0]),
                       coverage=np.array([1.0, -2.0, 1.0, np.nan, -5.0]), coverage_cut=0.0)


@pytest.mark.parametrize("threshold, gap, keep_faded", [
    (None, 0.0, False), (None, 0.5, False), (0.0, 0.5, False), (0.0, 0.5, True)])
def test_curtain_arrays_hold_the_same_cells_as_the_curtain_cells(threshold, gap, keep_faded):
    # 3D cells of a big model are built as arrays (one Python object per cell took 26 s for
    # 370 000 cells); they must be the very cells the curtain had
    from groundwork_geophysics.core.view3d import curtain_arrays
    mesh = _mixed_mesh()
    rgba = np.array([[1, 2, 3, 255], [4, 5, 6, 255], [0, 0, 0, 0], [7, 8, 9, 255],
                     [10, 11, 12, 255]], dtype=np.uint8)
    cells = curtain_cells(mesh, L_SHAPE, rgba, threshold, gap, keep_faded=keep_faded)
    arr = curtain_arrays(mesh, L_SHAPE, rgba, threshold, gap, keep_faded=keep_faded)
    assert len(arr.index) == len(cells)
    for k, cell in enumerate(cells):
        n = int(arr.points[k])
        assert np.allclose(arr.ring[k, :n], cell.ring)
        assert float(arr.value[k]) == cell.value
        assert (math.isnan(cell.coverage) and math.isnan(arr.coverage[k])) or \
            arr.coverage[k] == cell.coverage
        assert bool(arr.resolved[k]) == cell.resolved and bool(arr.faded[k]) == cell.faded
        assert tuple(int(c) for c in arr.rgb[k]) == cell.rgb
        if gap > 0:
            assert np.allclose(arr.front[k, :n], cell.faces[0])
            assert np.allclose(arr.back[k, :n], cell.faces[1])
        else:
            assert cell.faces == ()


def test_the_faces_are_written_in_chunks_with_the_same_bytes(monkeypatch):
    # 2 million cells at once took about 1 GB more: written a chunk of cells at a time
    from groundwork_geophysics.core import view3d
    a = view3d.curtain_arrays(_mixed_mesh(), L_SHAPE, np.full((5, 4), 255, np.uint8), None,
                              0.5)
    whole = view3d.faces_wkb(a)
    monkeypatch.setattr(view3d, "_WKB_CHUNK", 1)
    assert view3d.faces_wkb(a) == whole
