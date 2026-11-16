"""Where another profile crosses: what its interpretation looks like at the crossing."""
from groundwork_geophysics.core.interp_cross import CrossMark, crossing_marks
from groundwork_geophysics.core.interpretation import InterpPiece, normalise


def _p(kind, verts, fid="f"):
    return InterpPiece("p", "v", fid, "o", kind, verts)


def test_line_mark():
    assert crossing_marks([_p("line", [(0, 0), (10, -10)])], 4.0, 1.0) == [
        CrossMark("f", "line", -4.0, -4.0)]


def test_line_crossing_twice():
    m = crossing_marks([_p("line", [(0, 0), (10, -10), (0, -20)])], 5.0, 1.0)
    assert sorted(x.z_top for x in m) == [-15.0, -5.0]


def test_polygon_interval():
    sq = normalise(_p("polygon", [(0, 0), (10, 0), (10, -5), (0, -5)]))
    m = crossing_marks([sq], 5.0, 1.0)
    assert [(x.kind, x.z_top, x.z_bottom) for x in m] == [("polygon", 0.0, -5.0)]


def test_u_shaped_polygon_gives_two_intervals():
    u = normalise(_p("polygon", [(0, 0), (3, 0), (3, -6), (7, -6), (7, 0), (10, 0),
                                 (10, -10), (0, -10)]))
    m = crossing_marks([u], 5.0, 1.0)
    assert [(x.z_top, x.z_bottom) for x in m] == [(-6.0, -10.0)]
    m = crossing_marks([u], 1.0, 1.0)
    assert [(x.z_top, x.z_bottom) for x in m] == [(0.0, -10.0)]


def test_point_within_tol_only():
    pt = _p("point", [(5.0, -1.0)])
    assert crossing_marks([pt], 5.8, 1.0) == [CrossMark("f", "point", -1.0, -1.0)]
    assert crossing_marks([pt], 7.0, 1.0) == []


def test_outside_piece_no_mark():
    assert crossing_marks([_p("line", [(0, 0), (3, 0)])], 5.0, 1.0) == []
