import numpy as np, pytest
from geophysics_workbench.core.context import (
    BandSegment, Crossing, LogInterval, ProjectedPoint,
    line_crossings, polygon_intervals, profile_ties, project_points)

L = np.array([[0.0, 0.0], [100.0, 0.0]])
BENT = np.array([[0.0, 0.0], [50.0, 0.0], [50.0, 50.0]])


def test_line_crossing_chainage_and_angle():
    c = line_crossings(L, np.array([[30.0, -10.0], [30.0, 10.0]]), "380 kV", "powerline")
    assert len(c) == 1 and c[0].s == pytest.approx(30.0)
    assert c[0].angle_deg == pytest.approx(90.0) and c[0].kind == "powerline"


def test_line_crossing_multiple_and_at_vertex_no_duplicates():
    zig = np.array([[10.0, -5], [20.0, 5], [30.0, -5]])
    assert [round(c.s) for c in line_crossings(L, zig, "x", "line")] == [15, 25]
    at_vertex = line_crossings(BENT, np.array([[40.0, 10.0], [60.0, -10.0]]), "v", "line")
    assert len(at_vertex) == 1 and at_vertex[0].s == pytest.approx(50.0)


def test_project_points_buffer_offset_sign_and_ends():
    pts = np.array([[20.0, 5.0], [20.0, -30.0], [120.0, 0.0], [60.0, -8.0]])
    got = project_points(L, pts, buffer=10.0)
    assert [(i, round(s), round(o)) for i, s, o in got] == [(0, 20, 5), (3, 60, -8)]


def test_polygon_intervals_with_hole_and_touching_boundary():
    sq = np.array([[20.0, -10], [80, -10], [80, 10], [20, 10], [20, -10]])
    hole = np.array([[40.0, -5], [60, -5], [60, 5], [40, 5], [40, -5]])
    segs = polygon_intervals(L, [(sq, [hole])], ["Talsand"])
    assert [(round(b.s0), round(b.s1), b.label) for b in segs] == [(20, 40, "Talsand"), (60, 80, "Talsand")]
    touch = np.array([[0.0, 0], [100, 0], [100, 10], [0, 10], [0, 0]])   # shares the profile edge
    assert all(b.s1 - b.s0 > 1e-9 for b in polygon_intervals(L, [(touch, [])], ["t"]))


def test_profile_ties_crossing_near_miss_and_shared_end():
    cross = profile_ties(L, np.array([[40.0, -20.0], [40.0, 20.0]]), near_miss=10.0)
    assert np.array(cross).round(6).tolist() == [[40.0, 20.0, 0.0]]
    near = profile_ties(L, np.array([[70.0, 6.0], [70.0, 40.0]]), near_miss=10.0)
    assert len(near) == 1 and near[0][2] == pytest.approx(6.0) and near[0][0] == pytest.approx(70.0)
    assert profile_ties(L, np.array([[70.0, 16.0], [70.0, 40.0]]), near_miss=10.0) == []
    shared = profile_ties(L, np.array([[100.0, 0.0], [100.0, 50.0]]), near_miss=10.0)
    assert len(shared) == 1


def test_dataclasses_have_independent_default_logs():
    a, b = ProjectedPoint(1.0, 0.0, "a", "point"), ProjectedPoint(2.0, 0.0, "b", "point")
    a.log.append(LogInterval(0.0, 1.0, "sand"))
    assert b.log == [] and a.z_top is None
    assert Crossing(1.0, "x", "line", 90.0).kind == "line" and BandSegment(0.0, 1.0, "g").label == "g"
