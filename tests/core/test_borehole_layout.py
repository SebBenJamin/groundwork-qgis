import pytest

from groundwork_geophysics.core.borehole_layout import (ColumnPlace, ViewTransform, extent_z, fit,
                                                       layout_even, layout_true,
                                                       vertical_exaggeration)
from groundwork_geophysics.core.context import LogInterval, ProjectedPoint


def test_even_layout_keeps_order_and_gap():
    p = layout_even([16, 56, 16], gap_px=24)
    assert [c.x for c in p] == [0, 40, 120]
    assert [c.index for c in p] == [0, 1, 2]


def test_true_layout_centres_on_chainage_and_keeps_overlap():
    p = layout_true([10.0, 10.5], [16, 16])
    assert p[0] == ColumnPlace(0, 10.0, 16) and p[1].x == 10.5      # no pushing apart


def test_zoom_keeps_point_under_cursor():
    t = ViewTransform(0, 2.0, 30, 10.0)
    before = t.from_px(100, 50)
    t2 = t.zoom_at(100, 50, 1.5, 1.5)
    assert t2.from_px(100, 50) == pytest.approx(before)
    assert t2.x_scale == pytest.approx(3.0) and t2.z_scale == pytest.approx(15.0)


def test_to_px_and_back():
    t = ViewTransform(5.0, 2.0, 30.0, 10.0)
    px, py = t.to_px(10.0, 28.0)
    assert (px, py) == (10.0, 20.0)                    # z grows upward: lower z, larger y
    assert t.from_px(px, py) == pytest.approx((10.0, 28.0))


def test_ve_reported_for_true_distance():
    assert vertical_exaggeration(ViewTransform(0, 2.0, 0, 10.0)) == pytest.approx(5.0)


def test_fit_fills_the_view_and_keeps_ve():
    t = fit((0.0, 100.0), (10.0, 30.0), (500, 400), keep_ve=None)
    assert t.to_px(0.0, 30.0)[0] >= 0 and t.to_px(100.0, 10.0)[0] <= 500
    assert t.to_px(0.0, 30.0)[1] >= 0 and t.to_px(0.0, 10.0)[1] <= 400
    t5 = fit((0.0, 100.0), (10.0, 30.0), (500, 400), keep_ve=5.0)
    assert vertical_exaggeration(t5) == pytest.approx(5.0)


def test_depth_extent_includes_heightless_borehole_but_elevation_does_not():
    a = ProjectedPoint(10.0, 0.0, "A", "borehole", 25.0, [LogInterval(0.0, 4.0, "x")])
    b = ProjectedPoint(20.0, 0.0, "B", "borehole", None, [LogInterval(0.0, 9.0, "y")])
    no_surface = lambda s: None
    assert extent_z([a, b], "depth", no_surface) == (0.0, 9.0)
    assert extent_z([a, b], "elevation", no_surface) == (21.0, 25.0)
    assert extent_z([b], "elevation", no_surface) is None
    assert extent_z([b], "elevation", lambda s: 30.0) == (21.0, 30.0)


# -- layer text spread apart (thin layers) ------------------------------------------------------
def test_spread_texts_far_apart_unchanged():
    from groundwork_geophysics.core.borehole_layout import spread_texts
    assert spread_texts([(0, 40), (40, 80)], 10, -10, 90) == [20, 60]


def test_spread_texts_thin_layers_pushed_apart():
    from groundwork_geophysics.core.borehole_layout import spread_texts
    ys = spread_texts([(0, 2), (2, 4), (4, 6)], 10, -10, 100)
    assert ys == sorted(ys)
    assert all(b - a >= 10 - 1e-9 for a, b in zip(ys, ys[1:]))
    assert all(-5 - 1e-9 <= y <= 95 + 1e-9 for y in ys)


def test_spread_texts_too_many_drops_thinnest():
    from groundwork_geophysics.core.borehole_layout import spread_texts
    ys = spread_texts([(0, 10), (10, 11), (11, 30)], 10, 0, 20)
    assert ys[1] is None and ys[0] is not None and ys[2] is not None
    assert ys[2] - ys[0] >= 10 - 1e-9


def test_spread_texts_empty():
    from groundwork_geophysics.core.borehole_layout import spread_texts
    assert spread_texts([], 10, 0, 100) == []


# -- even spacing fits the window ----------------------------------------------------------------
def test_even_gap_shrinks_to_fit():
    from groundwork_geophysics.core.borehole_layout import even_gap
    assert even_gap([100] * 5, 600) == 25


def test_even_gap_never_below_min():
    from groundwork_geophysics.core.borehole_layout import even_gap
    assert even_gap([100] * 9, 600) == 12


def test_even_gap_room_to_spare():
    from groundwork_geophysics.core.borehole_layout import even_gap
    assert even_gap([50] * 3, 2000) == 40


def test_fit_even_one_column():
    from groundwork_geophysics.core.borehole_layout import even_gap
    assert even_gap([100], 50) == 40 and even_gap([], 50) == 40
