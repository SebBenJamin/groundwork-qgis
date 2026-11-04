"""Interpretation model and geometry (no QGIS)."""
import numpy as np
import pytest

from geophysics_workbench.core.chainage import Chainage
from geophysics_workbench.core.interpretation import (STARTER_TYPES, InterpPiece, footprint,
                                                      label_point, normalise, to_3d,
                                                      type_suggestions)

STRAIGHT = Chainage(np.array([[0.0, 0.0], [100.0, 0.0]]))
BENT = Chainage(np.array([[0.0, 0.0], [50.0, 0.0], [50.0, 50.0]]))


def _piece(kind, vertices):
    return InterpPiece("p", "v", "f", "prof", kind, list(vertices))


def _signed_area(ring):
    a = np.asarray(ring, float)
    return 0.5 * float(np.sum(a[:-1, 0] * a[1:, 1] - a[1:, 0] * a[:-1, 1]))


def test_normalise_closes_and_orients_polygon():
    p = normalise(_piece("polygon", [(0, 0), (0, 1), (1, 0)]))     # clockwise
    assert p.vertices[0] == p.vertices[-1]
    assert _signed_area(p.vertices) > 0


def test_normalise_rejects_short_pieces():
    for kind, verts in (("line", [(0, 0)]), ("polygon", [(0, 0), (1, 1), (0, 0)]),
                        ("point", [(0, 0), (1, 1)]), ("blob", [(0, 0)])):
        with pytest.raises(ValueError):
            normalise(_piece(kind, verts))


def test_normalise_drops_repeated_vertices():
    p = normalise(_piece("line", [(0, 0), (0, 0), (5, 1)]))
    assert p.vertices == [(0.0, 0.0), (5.0, 1.0)]


def test_line_3d_on_straight_profile():
    assert to_3d(_piece("line", [(10, 5), (30, 1)]), STRAIGHT) == [(10.0, 0.0, 5.0),
                                                                   (30.0, 0.0, 1.0)]


def test_polygon_over_bend_gets_bend_vertex():
    p = normalise(_piece("polygon", [(40, 0), (60, 0), (60, -5), (40, -5)]))
    ring = to_3d(p, BENT)
    pts = {tuple(round(c, 6) for c in v) for v in ring}
    assert (50.0, 0.0, 0.0) in pts and (50.0, 0.0, -5.0) in pts
    assert ring[0] == ring[-1]


def test_line_crossing_bend_interpolates_z():
    ring = to_3d(_piece("line", [(40, 0), (60, -10)]), BENT)
    assert ring == [(40.0, 0.0, 0.0), (50.0, 0.0, -5.0), (50.0, 10.0, -10.0)]


def test_footprint_spans_bend():
    p = normalise(_piece("polygon", [(40, 0), (60, 0), (60, -5), (40, -5)]))
    assert footprint(p, BENT) == [(40.0, 0.0), (50.0, 0.0), (50.0, 10.0)]


def test_point_3d_and_footprint():
    p = _piece("point", [(70, 3)])
    assert to_3d(p, BENT) == [(50.0, 20.0, 3.0)]
    assert footprint(p, BENT) == [(50.0, 20.0)]


def test_label_point_by_kind():
    assert label_point(_piece("point", [(3, 4)])) == (3.0, 4.0)
    assert label_point(_piece("line", [(0, 0), (2, 2), (10, 0)])) == (2.0, 2.0)
    sq = normalise(_piece("polygon", [(0, 0), (2, 0), (2, 2), (0, 2)]))
    assert label_point(sq) == pytest.approx((1.0, 1.0))


def test_type_suggestions_merge_case_insensitive():
    got = type_suggestions(["Clay lens", "anomaly", "ANOMALY"])
    assert "Clay lens" in got and [t.lower() for t in got].count("anomaly") == 1
    assert set(STARTER_TYPES) <= set(got)
    assert got == sorted(got, key=str.lower)


def test_clamp_to_surface_moves_points_above_ground_down():
    from geophysics_workbench.core.interpretation import clamp_to_surface
    surface = (np.array([0.0, 10.0]), np.array([5.0, 7.0]))
    assert clamp_to_surface([(0, 6), (5, 2), (10, 9)], surface) == [(0.0, 5.0), (5.0, 2.0),
                                                                    (10.0, 7.0)]
    assert clamp_to_surface([(1, 9)], None) == [(1.0, 9.0)]
