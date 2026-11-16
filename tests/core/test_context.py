import numpy as np, pytest
from groundwork_geophysics.core.context import (
    BandSegment, Crossing, LogInterval, ProjectedPoint,
    line_crossings, polygon_intervals, profile_ties, project_points)

L = np.array([[0.0, 0.0], [100.0, 0.0]])
BENT = np.array([[0.0, 0.0], [50.0, 0.0], [50.0, 50.0]])


def test_line_crossing_chainage_and_angle():
    c = line_crossings(L, np.array([[30.0, -10.0], [30.0, 10.0]]), "380 kV", "line")
    assert len(c) == 1 and c[0].s == pytest.approx(30.0)
    assert c[0].angle_deg == pytest.approx(90.0) and c[0].kind == "line"


def test_line_crossing_carries_colour_and_layer():
    [c] = line_crossings(L, np.array([[30.0, -10.0], [30.0, 10.0]]), "380 kV",
                         rgb=(220, 0, 0), layer="Powerline (OSM)")
    assert (c.rgb, c.layer, c.kind, c.label) == ((220, 0, 0), "Powerline (OSM)", "line", "380 kV")


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


def test_polygon_intervals_unclosed_ring_is_closed():
    sq = np.array([[20.0, -10], [80, -10], [80, 10], [20, 10]])   # no closing vertex
    segs = polygon_intervals(L, [(sq, [])], ["a"])
    assert [(round(b.s0), round(b.s1)) for b in segs] == [(20, 80)]


def _box(x0, x1):
    return np.array([[x0, -5.0], [x1, -5], [x1, 5], [x0, 5], [x0, -5]])


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
def test_polygon_intervals_overlapping_same_label_merge(order):
    polys = [(_box(10, 60), []), (_box(20, 40), [])]
    segs = polygon_intervals(L, [polys[i] for i in order], ["a", "a"])
    assert [(round(b.s0), round(b.s1), b.label) for b in segs] == [(10, 60, "a")]


def test_context_items_defaults_are_empty():
    from groundwork_geophysics.core.context import ContextItems
    items = ContextItems()
    assert items.crossings == [] and items.ties == [] and items.dem is None
    assert items.dem_tolerance == 1.0


def test_context_items_mirrored():
    from groundwork_geophysics.core.context import (BandSegment, ContextItems, Crossing,
                                                   LogInterval, ProjectedPoint)
    from groundwork_geophysics.core.ties import Tie
    col = object()
    items = ContextItems(
        crossings=[Crossing(10, "a", "line", 30.0), Crossing(70, "b", "line", 80.0, (1, 2, 3), "Lyr")],
        points=[ProjectedPoint(20, 5.0, "p", "borehole", 101.0, [LogInterval(0, 1, "sand")])],
        band=[BandSegment(0, 40, "x"), BandSegment(40, 100, "y")],
        ties=[Tie(25, "id", "other", 7.0, 0.0, [col])],
        dem=(np.array([0.0, 20.0, 100.0]), np.array([1.0, 2.0, np.nan])), dem_tolerance=2.0)
    m = items.mirrored(100.0)
    assert [(c.s, c.label, c.angle_deg) for c in m.crossings] == [(30, "b", 80.0), (90, "a", 30.0)]
    assert (m.points[0].s, m.points[0].offset, m.points[0].z_top) == (80, 5.0, 101.0)
    assert m.points[0].log == items.points[0].log
    assert [(b.s0, b.s1, b.label) for b in m.band] == [(0, 60, "y"), (60, 100, "x")]
    assert m.ties[0].s == 75 and m.ties[0].s_other == 7.0 and m.ties[0].columns == [col]
    np.testing.assert_allclose(m.dem[0], np.array([0, 80, 100]))       # asymmetric grid
    np.testing.assert_allclose(m.dem[0], 100.0 - items.dem[0][::-1])
    np.testing.assert_allclose(m.dem[1], [np.nan, 2.0, 1.0])
    assert m.dem_tolerance == 2.0
    assert (m.crossings[0].rgb, m.crossings[0].layer) == ((1, 2, 3), "Lyr")
    assert items.crossings[0].s == 10                      # original untouched
    assert ContextItems().mirrored(10.0).dem is None


def test_mirrored_keeps_strip_and_title():
    from groundwork_geophysics.core.context import BandSegment, ContextItems
    m = ContextItems(band=[BandSegment(0, 40, "x", strip=1, title="T")]).mirrored(100)
    assert (m.band[0].s0, m.band[0].strip, m.band[0].title) == (60, 1, "T")


def test_strips_of_orders_by_strip_and_drops_empty():
    from groundwork_geophysics.core.context import BandSegment, strips_of
    band = [BandSegment(50, 60, "b2", strip=2, title="C"), BandSegment(10, 20, "a2", strip=0, title="A"),
            BandSegment(0, 10, "a1", strip=0, title="A")]
    assert [(t, [s.label for s in segs]) for t, segs in strips_of(band)] == [
        ("A", ["a1", "a2"]), ("C", ["b2"])]
