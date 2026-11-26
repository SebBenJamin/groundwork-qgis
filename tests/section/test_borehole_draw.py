"""One borehole drawing for the section and the viewer."""
import numpy as np

from test_context_render import _close


def _draw(p, opts, y_of_depth=lambda d: 20.0 + 40.0 * d, styles=None, ranges=None,
          x=100.0):
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtGui import QImage, QPainter

    from groundwork_geophysics.section.borehole_draw import draw_borehole

    img = QImage(400, 300, QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    try:
        rc = QgsRenderContext.fromQPainter(painter)
        rect = draw_borehole(painter, rc, x, y_of_depth, p, opts, styles or {}, ranges or {})
    finally:
        painter.end()
    return img, rect


def _bh(intervals=(), curves=(), total=None):
    from groundwork_geophysics.core.context import LogInterval, ProjectedPoint
    from groundwork_geophysics.section.borehole_style import default_symbol
    log = []
    for top, bottom, text, rgb in intervals:
        sym = default_symbol(text)
        if rgb is not None:
            from qgis.PyQt.QtGui import QColor
            sym.setColor(QColor(*rgb))
        log.append(LogInterval(top, bottom, text, sym))
    return ProjectedPoint(50.0, 0.0, "B1", "borehole", 10.0, log, total_depth=total,
                          curves=list(curves))


def test_interval_drawn_with_its_symbol_colour(qgis_app):
    from groundwork_geophysics.section.borehole_draw import ColumnOptions
    img, _ = _draw(_bh([(0, 2, "a", (200, 20, 20)), (2, 4, "b", (20, 20, 200))]),
                   ColumnOptions(width_px=16))
    assert _close(img.pixel(100, 60), (200, 20, 20))      # depth 1 -> y 60
    assert _close(img.pixel(100, 140), (20, 20, 200))     # depth 3 -> y 140


def test_column_width_is_screen_pixels_under_any_scale(qgis_app):
    from groundwork_geophysics.section.borehole_draw import ColumnOptions
    p = _bh([(0, 2, "a", (200, 20, 20))])
    _, r1 = _draw(p, ColumnOptions(width_px=16), y_of_depth=lambda d: 20 + 40 * d)
    _, r2 = _draw(p, ColumnOptions(width_px=16), y_of_depth=lambda d: 20 + 120 * d)
    assert round(r1.width()) == round(r2.width()) == 16
    assert r2.height() > r1.height()


def test_curve_track_right_of_column(qgis_app):
    from groundwork_geophysics.core.borehole_curves import CurveStyle
    from groundwork_geophysics.core.context import Curve
    from groundwork_geophysics.section.borehole_draw import ColumnOptions
    c = Curve("t:gr", "gr", "API", np.linspace(0, 4, 41), np.linspace(10, 140, 41))
    p = _bh([(0, 4, "a", (200, 200, 200))], curves=[c])
    img, rect = _draw(p, ColumnOptions(width_px=16, curve_keys=("t:gr",), track_px=60),
                      styles={"t:gr": CurveStyle(colour="#00b400", width_mm=0.6)},
                      ranges={"t:gr": (0.0, 150.0)})
    green = [(x, y) for x in range(0, 400) for y in range(40, 180)
             if _close(img.pixel(x, y), (0, 180, 0), tol=40)]
    assert green and min(x for x, _y in green) > 108         # never inside the column
    assert rect.right() >= 108 + 60


def test_curves_off_draw_no_track(qgis_app):
    from groundwork_geophysics.core.context import Curve
    from groundwork_geophysics.section.borehole_draw import ColumnOptions
    c = Curve("t:gr", "gr", "API", np.linspace(0, 4, 5), np.linspace(10, 140, 5))
    _, rect = _draw(_bh([(0, 4, "a", None)], curves=[c]), ColumnOptions(width_px=16))
    assert round(rect.width()) == 16


def test_highlight_frame(qgis_app):
    from groundwork_geophysics.section.borehole_draw import HIGHLIGHT_RGB, ColumnOptions
    img, rect = _draw(_bh([(0, 2, "a", (255, 255, 255))]),
                      ColumnOptions(width_px=16, highlight=True))
    edge = [img.pixel(int(rect.left()) - 1 + dx, 60) for dx in range(0, 3)]
    assert any(_close(px, HIGHLIGHT_RGB, tol=40) for px in edge)


def test_total_depth_only_draws_outlined_empty_column(qgis_app):
    from groundwork_geophysics.section.borehole_draw import ColumnOptions
    img, rect = _draw(_bh(total=5.0), ColumnOptions(width_px=16))
    assert round(rect.bottom()) == 220                     # depth 5 -> y 220
    assert img.pixel(100, 120) == 0xFFFFFFFF               # empty inside
    assert not _close(img.pixel(int(rect.left()), 120), (255, 255, 255))


def test_opacity_lightens_the_fill(qgis_app):
    from groundwork_geophysics.section.borehole_draw import ColumnOptions
    img, _ = _draw(_bh([(0, 2, "a", (0, 0, 200))]), ColumnOptions(width_px=16, opacity=0.5))
    assert _close(img.pixel(100, 60), (127, 127, 227), tol=20)


def test_symbol_pool_starts_each_symbol_once_without_copying(qgis_app):
    """Performance: one frame starts each distinct interval symbol once and draws with it
    directly (copying a pattern symbol per interval made panning slow)."""
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtGui import QImage, QPainter

    from groundwork_geophysics.section.borehole_draw import SymbolPool
    from groundwork_geophysics.section.borehole_style import default_symbol
    img = QImage(10, 10, QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    try:
        rc = QgsRenderContext.fromQPainter(painter)
        sym = default_symbol("sand")
        with SymbolPool(rc) as pool:
            assert pool.get(sym) is sym and pool.get(sym) is sym
            assert pool.started == 1
    finally:
        painter.end()


def test_frame_draws_many_shared_intervals_with_one_pool(qgis_app):
    from groundwork_geophysics.core.context import LogInterval
    from groundwork_geophysics.section.borehole_draw import ColumnOptions
    from groundwork_geophysics.section.borehole_style import default_symbol
    p = _bh()
    shared = default_symbol("sand")
    p.log = [LogInterval(i * 0.1, i * 0.1 + 0.1, "sand", shared) for i in range(40)]
    img, _ = _draw(p, ColumnOptions(width_px=16))
    assert _close(img.pixel(100, 62), (shared.color().red(), shared.color().green(),
                                       shared.color().blue()))



def test_log_scale_with_min_at_or_below_zero_uses_the_smallest_positive_value(qgis_app):
    """Minor 3: a log track with min <= 0 still shows the curve (min = smallest positive
    sample), instead of an empty track."""
    from groundwork_geophysics.core.borehole_curves import CurveStyle
    from groundwork_geophysics.core.context import Curve
    from groundwork_geophysics.section.borehole_draw import curve_range
    c = Curve("k", "res", "ohm.m", np.array([0.0, 1.0, 2.0]), np.array([0.0, 5.0, 500.0]))
    assert curve_range(c, CurveStyle(log=True, vmin=0.0), None) == (1.0, 1000.0)   # decades
    assert curve_range(c, CurveStyle(log=True), (0.0, 500.0)) == (1.0, 1000.0)
    assert curve_range(Curve("k", "r", "", np.array([0.0]), np.array([-1.0])),
                       CurveStyle(log=True), None) is None


def _text_rows(img, x0, x1):
    """Rows with dark text pixels between x0 and x1, grouped into runs of touching rows."""
    from qgis.PyQt.QtGui import qGray
    rows = [y for y in range(img.height())
            if any(qGray(img.pixel(x, y)) < 120 for x in range(x0, x1))]
    runs = []
    for y in rows:
        if runs and y == runs[-1][-1] + 1:
            runs[-1].append(y)
        else:
            runs.append([y])
    return runs


def _thin_layers():
    return _bh([(0, 0.05, "loam Sl4", (255, 255, 255)), (0.05, 0.1, "silt Ut3", (255, 255, 255)),
                (0.1, 3, "sand", (255, 255, 255))])


def test_thin_layer_texts_do_not_overlap(qgis_app):
    from groundwork_geophysics.section.borehole_draw import TEXT_GAP_PX, ColumnOptions
    img, _ = _draw(_thin_layers(), ColumnOptions(width_px=16, layer_text=True))
    rows = [y for run in _text_rows(img, int(108 + TEXT_GAP_PX + 1), 400) for y in run]
    upper = [y for y in rows if y < 60]               # the two thin layers' texts (sand: y 82)
    # both texts sit at their layers' middles (y 21 and 23) unless spread: two lines of
    # the 9 px text are at least 14 px from the top of the first to the bottom of the second
    assert max(upper) - min(upper) >= 14


def test_moved_text_gets_a_leader(qgis_app):
    from groundwork_geophysics.section.borehole_draw import TEXT_GAP_PX, ColumnOptions
    img, _ = _draw(_thin_layers(), ColumnOptions(width_px=16, layer_text=True))
    assert _text_rows(img, 110, int(108 + TEXT_GAP_PX - 1))


def test_the_users_own_scale_ends_are_kept(qgis_app):
    from groundwork_geophysics.core.borehole_curves import CurveStyle
    from groundwork_geophysics.core.context import Curve
    from groundwork_geophysics.section.borehole_draw import curve_range
    c = Curve("k", "toc", "%", np.array([0.0, 1.0]), np.array([0.0175, 10.964]))
    assert curve_range(c, CurveStyle(), None) == (0.0, 12.0)              # rounded outward
    assert curve_range(c, CurveStyle(vmin=0.5, vmax=11.5), None) == (0.5, 11.5)
    assert curve_range(c, CurveStyle(vmax=11.5), None) == (0.0, 11.5)


def test_a_borehole_without_the_curve_gets_no_empty_track(qgis_app):
    """Tracks only where the borehole has values: cores without lab samples stay narrow."""
    from groundwork_geophysics.core.context import Curve
    from groundwork_geophysics.section.borehole_draw import ColumnOptions, shown_curve_keys
    c = Curve("t:toc", "toc", "%", np.linspace(0, 4, 5), np.linspace(1, 5, 5))
    keys = ("t:toc", "t:clay")
    p = _bh([(0, 4, "a", None)], curves=[c])
    assert shown_curve_keys(p, keys) == ("t:toc",)
    assert shown_curve_keys(_bh([(0, 4, "a", None)]), keys) == ()
    _, rect = _draw(p, ColumnOptions(width_px=16, curve_keys=keys, track_px=60))
    assert 16 + 60 <= round(rect.width()) < 16 + 2 * 60          # one track, not two
    _, bare = _draw(_bh([(0, 4, "a", None)]), ColumnOptions(width_px=16, curve_keys=keys,
                                                            track_px=60))
    assert round(bare.width()) == 16


def test_a_track_backdrop_hides_what_lies_behind(qgis_app):
    """The viewer's tracks are drawn on white, so a neighbour's track behind them (true
    distance, cores close together) does not mix with this one's line."""
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtGui import QColor, QImage, QPainter

    from groundwork_geophysics.core.context import Curve
    from groundwork_geophysics.section.borehole_draw import ColumnOptions, draw_borehole
    c = Curve("t:toc", "toc", "%", np.linspace(0, 4, 5), np.full(5, 1.0))   # line on the left
    p = _bh([(0, 4, "a", None)], curves=[c])
    for backdrop, expect_white in ((True, True), (False, False)):
        img = QImage(400, 300, QImage.Format.Format_ARGB32)
        img.fill(QColor(90, 90, 90))
        painter = QPainter(img)
        try:
            rc = QgsRenderContext.fromQPainter(painter)
            draw_borehole(painter, rc, 100.0, lambda d: 20.0 + 40.0 * d, p,
                          ColumnOptions(width_px=16, curve_keys=("t:toc",), track_px=60,
                                        track_backdrop=(255, 255, 255) if backdrop else None),
                          {}, {"t:toc": (0.0, 2.0)})
        finally:
            painter.end()
        assert _close(img.pixel(160, 100), (255, 255, 255)) is expect_white


def test_section_room_right_of_a_column_counts_only_its_own_curves(qgis_app):
    from groundwork_geophysics.core.context import BoreholeView, ContextItems, Curve
    from groundwork_geophysics.section.borehole_draw import TRACK_GAP_PX
    from groundwork_geophysics.section.context_render_points import (SECTION_TRACK_PX,
                                                                      right_extent_px)
    c = Curve("t:toc", "toc", "%", np.linspace(0, 4, 5), np.linspace(1, 5, 5))
    with_lab, without = _bh([(0, 4, "a", None)], curves=[c]), _bh([(0, 4, "a", None)])
    items = ContextItems(points=[with_lab, without],
                         borehole_views={-1: BoreholeView(curve_keys=("t:toc", "t:clay"))})
    assert right_extent_px(items, with_lab) == SECTION_TRACK_PX + TRACK_GAP_PX
    assert right_extent_px(items, without) == 0.0
