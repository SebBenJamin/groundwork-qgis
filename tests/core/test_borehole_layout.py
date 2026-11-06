import pytest

from geophysics_workbench.core.borehole_layout import (ColumnPlace, ViewTransform, extent_z, fit,
                                                       layout_even, layout_true,
                                                       vertical_exaggeration)
from geophysics_workbench.core.context import LogInterval, ProjectedPoint


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
