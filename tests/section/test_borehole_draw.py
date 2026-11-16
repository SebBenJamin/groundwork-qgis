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
    assert curve_range(c, CurveStyle(log=True, vmin=0.0), None) == (5.0, 500.0)
    assert curve_range(c, CurveStyle(log=True), (0.0, 500.0)) == (5.0, 500.0)
    assert curve_range(Curve("k", "r", "", np.array([0.0]), np.array([-1.0])),
                       CurveStyle(log=True), None) is None
