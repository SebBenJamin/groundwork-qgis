"""3D geometry for the QGIS 3D view: model cells as vertical rings under the profile, and
borehole log intervals as vertical segments at the borehole's map position."""
import math

import numpy as np

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
