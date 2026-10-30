"""Third-party context drawn on the section: band, DEM, crossings, boreholes, ties."""
import numpy as np
import pytest

# _render maps chainage 40 .. 80 m to x = 0 .. 400 px and z 1 .. -3 m to y = 0 .. 200 px
Z_RANGE = (-3.0, 1.0)


def _x(s):
    return int(round(10.0 * s - 400.0))


def _y(z):
    return int(round(50.0 - 50.0 * z))


def _mm(img, value):
    from qgis.core import Qgis, QgsRenderContext
    from qgis.PyQt.QtGui import QPainter

    painter = QPainter(img)
    try:
        return QgsRenderContext.fromQPainter(painter).convertToPainterUnits(value, Qgis.RenderUnit.Millimeters)
    finally:
        painter.end()


def _results(context, stations=(), z_range=Z_RANGE):
    from geophysics_workbench.section.data import SectionSnapshot
    from geophysics_workbench.section.profile_source import WorkbenchProfileResults

    topo = (np.array([40.0, 80.0]), np.array([0.0, 0.0]))
    snap = SectionSnapshot("p1", [], topo, [(float(s), "") for s in stations], None, context)
    station_z = np.interp([float(s) for s in stations], *topo) if stations else None
    return WorkbenchProfileResults(snap, [], z_range, station_z, None)


def _img(results):
    from test_beyond_stations import _render

    return _render(results)


def _close(pixel, rgb, tol=12):
    from qgis.PyQt.QtGui import QColor

    c = QColor(pixel)
    return max(abs(c.red() - rgb[0]), abs(c.green() - rgb[1]), abs(c.blue() - rgb[2])) <= tol


def _blend(rgb, alpha):
    return tuple(alpha * c + (1 - alpha) * 255 for c in rgb)


def test_band_colour_appears_above_surface(qgis_app):
    from geophysics_workbench.core.context import BandSegment, ContextItems
    from geophysics_workbench.core.lithology import lithology_colour

    img = _img(_results(ContextItems(band=[BandSegment(50.0, 70.0, "Sand")])))
    x, y = _x(55.0), _y(0.0) - round(_mm(img, 3.0))
    assert _close(img.pixel(x, y), _blend(lithology_colour("Sand"), 0.85))
    assert img.pixel(_x(45.0), y) == 0xFFFFFFFF            # outside the segment


def _orange_in_column(img, s):
    from qgis.PyQt.QtGui import QColor

    for x in range(_x(s) - 3, _x(s) + 4):
        for y in range(img.height()):
            c = QColor(img.pixel(x, y))
            if abs(c.red() - 255) < 30 and abs(c.green() - 120) < 30 and c.blue() < 40:
                return True
    return False


def test_powerline_crossing_is_orange(qgis_app):
    from geophysics_workbench.core.context import ContextItems, Crossing

    img = _img(_results(ContextItems(crossings=[Crossing(60.0, "HS 110 kV", "powerline", 90.0)])))
    assert _orange_in_column(img, 60.0)
    assert not _orange_in_column(img, 45.0)


def test_borehole_column_colours_by_lithology(qgis_app):
    from geophysics_workbench.core.context import ContextItems, LogInterval, ProjectedPoint
    from geophysics_workbench.core.lithology import lithology_colour

    bh = ProjectedPoint(60.0, 12.0, "BK1", "borehole", 0.0,
                        [LogInterval(0.0, 1.0, "Ton"), LogInterval(1.0, 2.5, "Sand")])
    img = _img(_results(ContextItems(points=[bh])))
    assert _close(img.pixel(_x(60.0), _y(-0.5)), lithology_colour("Ton"))
    assert _close(img.pixel(_x(60.0), _y(-1.8)), lithology_colour("Sand"))
    assert img.pixel(_x(48.0), _y(-0.5)) == 0xFFFFFFFF


def _is_red(pixel):
    from qgis.PyQt.QtGui import QColor

    c = QColor(pixel)
    return c.red() > 180 and c.green() < 80 and c.blue() < 80


def test_dem_disagreement_marks_station_red(qgis_app):
    from geophysics_workbench.core.context import ContextItems

    s = np.array([40.0, 50.0, 55.0, 60.0, 65.0, 70.0, 80.0])
    z = np.array([0.0, 0.0, 0.0, -2.0, 0.0, 0.0, 0.0])           # 2 m off at s = 60 only
    items = ContextItems(dem=(s, z), dem_tolerance=0.5)
    img = _img(_results(items, stations=(50.0, 60.0, 70.0)))
    half = max(3, round(_mm(img, 1.0)))
    probe = {st: img.pixel(_x(st), _y(0.0) - half) for st in (50.0, 60.0, 70.0)}
    assert _is_red(probe[60.0])
    for st in (50.0, 70.0):
        assert not _is_red(probe[st]) and _close(probe[st], (0, 0, 0), 60)


def test_dem_gap_keeps_station_black_and_breaks_the_line(qgis_app):
    from geophysics_workbench.core.context import ContextItems

    s = np.array([40.0, 50.0, 60.0, 70.0, 80.0])
    z = np.array([0.0, 0.0, np.nan, 0.0, 0.0])
    img = _img(_results(ContextItems(dem=(s, z)), stations=(60.0,)))
    half = max(3, round(_mm(img, 1.0)))
    assert not _is_red(img.pixel(_x(60.0), _y(0.0) - half))


def test_tie_column_uses_other_profiles_scale(qgis_app):
    from geophysics_workbench.core.colors import ColorScale
    from geophysics_workbench.core.context import ContextItems
    from geophysics_workbench.core.ties import Tie, TieColumn

    scale = ColorScale("Spectral_r", 1.0, 1000.0, True)
    col = TieColumn("P3 model", np.array([0.0, -1.0]), np.array([-1.0, -2.0]),
                    np.array([10.0, 500.0]), scale, "resistivity", "ohm.m")
    items = ContextItems(ties=[Tie(60.0, "p3", "P3", 30.0, 0.0, [col])])
    img = _img(_results(items))
    x = _x(60.0) + round(_mm(img, 1.5))
    assert _close(img.pixel(x, _y(-0.5)), tuple(scale.rgba(10.0)[0][:3]))
    assert _close(img.pixel(x, _y(-1.5)), tuple(scale.rgba(500.0)[0][:3]))
    assert img.pixel(x + round(_mm(img, 4.0)), _y(-0.5)) == 0xFFFFFFFF


def test_tie_without_scale_draws_no_strip(qgis_app):
    from geophysics_workbench.core.context import ContextItems
    from geophysics_workbench.core.ties import Tie, TieColumn

    col = TieColumn("P3 model", np.array([0.0]), np.array([-1.0]), np.array([np.nan]),
                    None, "resistivity", "ohm.m")
    img = _img(_results(ContextItems(ties=[Tie(60.0, "p3", "P3", 30.0, 6.0, [col])])))
    assert img.pixel(_x(60.0) + round(_mm(img, 1.5)), _y(-0.5)) == 0xFFFFFFFF


def test_zrange_includes_borehole_bottom(qgis_app):
    from geophysics_workbench.core.colors import ColorScale
    from geophysics_workbench.core.context import ContextItems, LogInterval, ProjectedPoint
    from geophysics_workbench.core.ties import Tie, TieColumn
    from geophysics_workbench.section.data import SectionSnapshot
    from geophysics_workbench.section.profile_source import WorkbenchProfileGenerator

    class Owner:
        last_results = None

    topo = (np.array([0.0, 100.0]), np.array([10.0, 12.0]))
    bh = ProjectedPoint(50.0, 3.0, "BK1", "borehole", None, [LogInterval(0.0, 30.0, "Kies")])
    col = TieColumn("P3", np.array([11.0, -40.0]), np.array([-40.0, -55.0]), np.array([1.0, 2.0]),
                    ColorScale(), "resistivity", "ohm.m")
    items = ContextItems(points=[bh], ties=[Tie(20.0, "p3", "P3", 5.0, 0.0, [col])])
    snap = SectionSnapshot("p1", [], topo, [], None, items)
    gen = WorkbenchProfileGenerator(snap, Owner())
    assert gen.generateProfile()
    rng = gen.takeResults().zRange()
    assert rng.lower() == pytest.approx(-55.0)
    assert rng.upper() == pytest.approx(12.0)
    # surface at s = 50 is 11 m, so the borehole bottom alone would be -19
    items.ties = []
    gen = WorkbenchProfileGenerator(SectionSnapshot("p1", [], topo, [], None, items), Owner())
    assert gen.generateProfile()
    assert gen.takeResults().zRange().lower() == pytest.approx(-19.0)
