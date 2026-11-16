"""Measured station heights on the section whatever the topography choice (R18, spec 4.2:
"show both when they disagree"), and context drawing that cannot drop the stations."""
import numpy as np
import pytest

# _render_wide maps chainage -10 .. 60 m to x = 0 .. 700 px and z 106 .. 96 m to y = 0 .. 200
def _x(s):
    return int(round(10.0 * (s + 10.0)))


def _y(z):
    return int(round(20.0 * (106.0 - z)))


def _render_wide(results):
    from qgis.core import QgsProfileRenderContext, QgsRenderContext
    from qgis.PyQt.QtGui import QImage, QPainter, QTransform

    img = QImage(700, 200, QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    try:
        ctx = QgsProfileRenderContext(QgsRenderContext.fromQPainter(painter))
        ctx.setWorldTransform(QTransform(10.0, 0.0, 0.0, -20.0, 100.0, 2120.0))
        results.renderResults(ctx)
    finally:
        painter.end()
    return img


def _rgb(pixel):
    from qgis.PyQt.QtGui import QColor
    c = QColor(pixel)
    return c.red(), c.green(), c.blue()


def _is_red(pixel):
    r, g, b = _rgb(pixel)
    return r > 180 and g < 80 and b < 80


def _is_dark(pixel):
    return max(_rgb(pixel)) < 60


def _generate(provider, profile_id):
    from groundwork_geophysics.section.profile_source import WorkbenchProfileGenerator

    class Owner:
        last_results = None

    snap = provider.snapshot(profile_id)
    gen = WorkbenchProfileGenerator(snap, Owner())
    assert gen.generateProfile()
    return snap, gen.takeResults()


@pytest.fixture
def dem_mode(qgis_app, store_with_model):
    """P1's stations measure 100 m at s = 0 and 102 m at s = 50; the DEM agrees at s = 0
    and rises to 2 m above the station at s = 50. The models hang from the DEM."""
    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.section.data import SectionDataProvider

    st, p, _ = store_with_model
    s = np.linspace(0.0, 50.0, 11)
    dem = (s, 100.0 + 4.0 * s / 50.0)                   # 104 m at s = 50, 2 m above
    prov = SectionDataProvider(st)
    prov.context_source = lambda profile: ContextItems(dem=dem, dem_tolerance=0.5)
    prov.set_topography_source(p.id, "dem")
    return prov, p


def test_dem_mode_draws_the_station_at_its_measured_height_in_red(dem_mode):
    from groundwork_geophysics.section.profile_source import MEASURED_COLOUR

    prov, p = dem_mode
    snap, results = _generate(prov, p.id)
    assert snap.dem_topo is True
    assert snap.topo[1][-1] == pytest.approx(104.0)             # models hang from the DEM
    np.testing.assert_allclose(snap.station_heights, np.array([100.0, 102.0]))
    np.testing.assert_allclose(results._station_z, np.array([100.0, 102.0]))
    img = _render_wide(results)
    half = 4                                                     # triangle: 2 * max(3, 1 mm) tall
    assert _is_red(img.pixel(_x(50.0), _y(102.0) - half))      # measured height, flagged
    assert not _is_red(img.pixel(_x(50.0), _y(104.0) - half))  # nothing at the DEM height
    assert _is_dark(img.pixel(_x(0.0), _y(100.0) - half))      # agrees: a black tick
    # the thin solid line through the measured heights, apart from the DEM surface
    grey = MEASURED_COLOUR.getRgb()[:3]
    assert grey[0] == grey[1] == grey[2]
    col = [_rgb(img.pixel(_x(25.0), y)) for y in range(_y(101.0) - 2, _y(101.0) + 3)]
    # antialiased, the 1 px line may spread over two rows: grey, clearly off white
    assert any(c[0] == c[1] == c[2] and c[0] < 200 for c in col), col
    assert all(_rgb(img.pixel(_x(25.0), y)) == (255, 255, 255)
               for y in range(_y(101.0) - 12, _y(101.0) - 6))


def test_stations_mode_has_no_extra_line_and_still_flags(dem_mode):
    prov, p = dem_mode
    prov.set_topography_source(p.id, "stations")
    snap, results = _generate(prov, p.id)
    assert snap.dem_topo is False
    np.testing.assert_allclose(results._station_z, np.array([100.0, 102.0]))
    img = _render_wide(results)
    assert _is_red(img.pixel(_x(50.0), _y(102.0) - 4))


def test_reverse_snapshot_keeps_heights_aligned_with_the_stations(dem_mode):
    prov, p = dem_mode
    snap = prov.snapshot(p.id, reverse=True)
    assert [s for s, _ in snap.stations] == pytest.approx([50.0, 0.0])
    np.testing.assert_allclose(snap.station_heights, np.array([100.0, 102.0]))


def test_failing_band_drawing_keeps_the_stations(qgis_app, monkeypatch):
    """R19f: an exception in the geology band (or later context) is logged; the stations
    are still drawn."""
    from test_context_render import _img, _mm, _results, _x as x_, _y as y_

    from groundwork_geophysics.core.context import BandSegment, ContextItems
    from groundwork_geophysics.section import profile_source

    def boom(*_a, **_k):
        raise RuntimeError("band broke")

    monkeypatch.setattr(profile_source, "draw_band", boom)
    monkeypatch.setattr(profile_source, "draw_over_stations", boom)
    logged = []
    monkeypatch.setattr(profile_source, "_log_failure", lambda what, exc: logged.append(what))
    img = _img(_results(ContextItems(band=[BandSegment(50.0, 70.0, "Sand")]), stations=(60.0,)))
    half = max(3, round(_mm(img, 1.0)))
    assert _is_dark(img.pixel(x_(60.0), y_(0.0) - half))
    assert logged == ["drawing (geology band)", "drawing (context)"]
