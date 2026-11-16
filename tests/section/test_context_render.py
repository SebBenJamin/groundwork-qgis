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


def _band_offsets(img, level=0):
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtGui import QPainter

    from groundwork_geophysics.section.context_render import band_offsets

    painter = QPainter(img)
    try:
        return band_offsets(QgsRenderContext.fromQPainter(painter), level)
    finally:
        painter.end()


def _results(context, stations=(), z_range=Z_RANGE, topo_z=0.0, layers=(), topo=None):
    """``layers`` are the viewed profile's snapshot layers (not drawn here: the results
    get no cell paths), which the tie strips take their colour scale from."""
    from groundwork_geophysics.section.data import SectionSnapshot
    from groundwork_geophysics.section.profile_source import WorkbenchProfileResults

    topo = topo or (np.array([40.0, 80.0]), np.array([topo_z, topo_z]))
    snap = SectionSnapshot("p1", list(layers), topo, [(float(s), "") for s in stations], None,
                           context)
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
    from groundwork_geophysics.core.context import BandSegment, ContextItems
    from groundwork_geophysics.core.lithology import label_colour

    img = _img(_results(ContextItems(band=[BandSegment(50.0, 70.0, "Sand")])))
    near, far = _band_offsets(img)
    x, y = _x(55.0), _y(0.0) - round(0.5 * (near + far))
    assert _close(img.pixel(x, y), _blend(label_colour("Sand"), 0.85))
    assert img.pixel(_x(45.0), y) == 0xFFFFFFFF            # outside the segment


def test_crossing_label_lies_above_the_band(qgis_app):
    from groundwork_geophysics.core.context import BandSegment, ContextItems, Crossing

    items = ContextItems(band=[BandSegment(50.0, 70.0, "Sand")],
                         crossings=[Crossing(60.0, "HS 110 kV", "line", 90.0, rgb=(255, 120, 0))])
    img = _img(_results(items, topo_z=-1.0))
    near, far = _band_offsets(img)
    band_top = _y(-1.0) - far
    hits = [y for x in range(_x(60.0) - 60, _x(60.0) + 60) for y in range(img.height())
            if (lambda c: c.red() > c.green() + 60 and c.red() > c.blue() + 60)(
                __import__("qgis.PyQt.QtGui", fromlist=["QColor"]).QColor(img.pixel(x, y)))
            and abs(x - _x(60.0)) > 3]                      # leave the dashed line out
    assert hits, "no label pixels"
    assert max(hits) < band_top - 1, (max(hits), band_top)


def _has_colour(img, s, rgb, tol=30):
    from qgis.PyQt.QtGui import QColor

    for x in range(_x(s) - 3, _x(s) + 4):
        for y in range(img.height()):
            c = QColor(img.pixel(x, y))
            if all(abs(a - b) < tol for a, b in zip((c.red(), c.green(), c.blue()), rgb)):
                return True
    return False


def test_crossing_drawn_in_its_colour(qgis_app):
    from groundwork_geophysics.core.context import ContextItems, Crossing

    img = _img(_results(ContextItems(
        crossings=[Crossing(60.0, "HS 110 kV", "line", 90.0, rgb=(0, 0, 255))])))
    assert _has_colour(img, 60.0, (0, 0, 255))
    assert not _has_colour(img, 60.0, (255, 120, 0))
    assert not _has_colour(img, 45.0, (0, 0, 255))


def test_crossing_label_has_no_glyph(qgis_app):
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtGui import QImage, QPainter, QTransform

    from groundwork_geophysics.core.context import ContextItems, Crossing
    from groundwork_geophysics.section.context_render import plan_labels

    c = Crossing(60.0, "380 kV", "line", 90.0, rgb=(0, 0, 255))
    img = QImage(400, 200, QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    try:
        rc = QgsRenderContext.fromQPainter(painter)
        labels = plan_labels(painter, rc, QTransform(), ContextItems(crossings=[c]),
                             (np.array([0.0, 100.0]), np.array([0.0, 0.0])))
    finally:
        painter.end()
    assert labels[id(c)].text == "380 kV"
    assert labels[id(c)].rgb == (0, 0, 255)


def test_borehole_column_colours_by_lithology(qgis_app):
    from groundwork_geophysics.core.context import ContextItems, LogInterval, ProjectedPoint
    from groundwork_geophysics.core.lithology import label_colour

    bh = ProjectedPoint(60.0, 12.0, "BK1", "borehole", 0.0,
                        [LogInterval(0.0, 1.0, "Ton"), LogInterval(1.0, 2.5, "Sand")])
    img = _img(_results(ContextItems(points=[bh])))
    # unstyled intervals: a neutral colour per text, nothing matched from the words
    assert _close(img.pixel(_x(60.0), _y(-0.5)), label_colour("Ton"))
    assert _close(img.pixel(_x(60.0), _y(-1.8)), label_colour("Sand"))
    assert img.pixel(_x(48.0), _y(-0.5)) == 0xFFFFFFFF


def _is_red(pixel):
    from qgis.PyQt.QtGui import QColor

    c = QColor(pixel)
    return c.red() > 180 and c.green() < 80 and c.blue() < 80


def test_dem_disagreement_marks_station_red(qgis_app):
    from groundwork_geophysics.core.context import ContextItems

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
    from groundwork_geophysics.core.context import ContextItems

    s = np.array([40.0, 50.0, 60.0, 70.0, 80.0])
    z = np.array([0.0, 0.0, np.nan, 0.0, 0.0])
    img = _img(_results(ContextItems(dem=(s, z)), stations=(60.0,)))
    half = max(3, round(_mm(img, 1.0)))
    assert not _is_red(img.pixel(_x(60.0), _y(0.0) - half))


def _host_layer(quantity, scale, visible=True):
    """A layer of the viewed profile with ``scale``; its one cell is never drawn here."""
    from groundwork_geophysics.core.model import Dataset
    from groundwork_geophysics.core.section_mesh import SectionMesh
    from groundwork_geophysics.section.data import LayerStyle, SectionLayer

    d = Dataset("h", "p1", "s1", "ert_model", "x", 0, "", "r2_res_dat", {}, {},
                quantity=quantity)
    mesh = SectionMesh(np.array([[0.0, 0], [4, 0], [0, -4]]), np.array([[0, 1, 2, -1]]),
                       np.array([7.0]), quantity=quantity)
    return SectionLayer(d, mesh, LayerStyle(visible=visible, scale=scale), None)


def _tie_items(scale, points=()):
    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.core.ties import Tie, TieColumn

    col = TieColumn("P3 model", np.array([0.0, -1.0]), np.array([-1.0, -2.0]),
                    np.array([10.0, 500.0]), scale, "resistivity", "ohm.m")
    return ContextItems(ties=[Tie(60.0, "p3", "P3", 30.0, 0.0, [col])], points=list(points))


def test_tie_strip_uses_host_profiles_scale(qgis_app):
    """R14: the strip is drawn in the colour scale of the profile being viewed, from its
    topmost visible layer of the same quantity (hidden and other-quantity layers skipped)."""
    from groundwork_geophysics.core.colors import ColorScale

    own = ColorScale("Spectral_r", 1.0, 1000.0, True)
    host = ColorScale("Spectral_r", 8.0, 40.0, True)
    layers = [_host_layer("resistivity", ColorScale("gray", 1.0, 1000.0, True)),
              _host_layer("resistivity", host),
              _host_layer("chargeability", ColorScale("viridis", 0.0, 50.0, False)),
              _host_layer("resistivity", ColorScale("jet", 1.0, 1000.0, True), visible=False)]
    img = _img(_results(_tie_items(own), layers=layers))
    x = _x(60.0) + round(_mm(img, 1.5))
    a, b = host.rgba(10.0)[0][:3].astype(int), own.rgba(10.0)[0][:3].astype(int)
    assert np.abs(a - b).max() > 40                         # the two scales tell apart
    assert _close(img.pixel(x, _y(-0.5)), tuple(host.rgba(10.0)[0][:3]))
    assert _close(img.pixel(x, _y(-1.5)), tuple(host.rgba(500.0)[0][:3]))
    assert img.pixel(x + round(_mm(img, 4.0)), _y(-0.5)) == 0xFFFFFFFF


def test_tie_strip_falls_back_to_its_own_scale(qgis_app):
    """Without a model of the strip's quantity on the viewed profile, the strip keeps the
    other profile's own scale (round 2: a hidden model of that quantity still lends its
    scale, so switching layers never recolours the strip - test_tie_strip_scale)."""
    from groundwork_geophysics.core.colors import ColorScale

    own = ColorScale("Spectral_r", 1.0, 1000.0, True)
    for layers in ([], [_host_layer("chargeability", ColorScale("viridis", 0.0, 50.0, False))]):
        img = _img(_results(_tie_items(own), layers=layers))
        x = _x(60.0) + round(_mm(img, 1.5))
        assert _close(img.pixel(x, _y(-0.5)), tuple(own.rgba(10.0)[0][:3]))
        assert _close(img.pixel(x, _y(-1.5)), tuple(own.rgba(500.0)[0][:3]))


def test_tie_strip_moves_off_a_borehole_column(qgis_app):
    """R15: a borehole column right of the tie line sends the strip left of the line; a
    column standing on the line (both sides blocked) sends it just past the column."""
    from groundwork_geophysics.core.colors import ColorScale
    from groundwork_geophysics.core.context import LogInterval, ProjectedPoint
    from groundwork_geophysics.core.lithology import label_colour

    scale = ColorScale("Spectral_r", 1.0, 1000.0, True)
    blue = tuple(scale.rgba(10.0)[0][:3])
    sand = label_colour("Sand")

    def render(s_borehole):
        bh = ProjectedPoint(s_borehole, 0.0, "B1", "borehole", 0.0,
                            [LogInterval(0.0, 2.0, "Sand")])
        return _img(_results(_tie_items(scale, [bh])))

    img = render(50.0)                      # clear of the strip: it stays right of the line
    mm = _mm(img, 1.0)                      # px per mm; the test maps 10 px to 1 m
    x0, y = _x(60.0), _y(-0.5)
    assert _close(img.pixel(x0 + round(1.5 * mm), y), blue)
    # column right of the line (its left edge 0.35 mm past it): strip left of the line
    img = render(60.0 + 1.6 * mm / 10.0)
    assert _close(img.pixel(x0 - round(1.5 * mm), y), blue)
    assert _close(img.pixel(x0 + round(1.6 * mm), y), sand)
    # column on the line: the strip starts at its right edge (1.25 mm), left stays empty
    img = render(60.0)
    assert _close(img.pixel(x0 + round(1.25 * mm + 1.5 * mm), y), blue)
    assert _close(img.pixel(x0 + round(0.6 * mm), y), sand)
    assert _close(img.pixel(x0 - round(0.6 * mm), y), sand)
    assert img.pixel(x0 - round(2.0 * mm), y) == 0xFFFFFFFF


def test_tie_strip_is_framed_in_the_tie_colour(qgis_app):
    """In the host's own scale the strip matches the section behind it, so a thin frame
    in the tie colour keeps it readable as a column of its own."""
    from groundwork_geophysics.core.colors import ColorScale
    from groundwork_geophysics.section.context_render import TIE_COLOUR

    img = _img(_results(_tie_items(ColorScale("Spectral_r", 1.0, 1000.0, True))))
    edge = _x(60.0) + round(_mm(img, 3.0))
    assert any(_close(img.pixel(x, _y(-0.5)), TIE_COLOUR, 40) for x in range(edge - 2, edge + 3))
    assert not _close(img.pixel(_x(60.0) + round(_mm(img, 1.5)), _y(-0.5)), TIE_COLOUR, 40)


def test_strip_readout_and_panel_show_the_same_topmost_column(qgis_app):
    """Important 2: with two models on the other profile, the strip, the hover readout
    and the ties panel all describe its topmost visible model that has cells at the tie
    (the last column), whether the bottom model is empty there or not."""
    from types import SimpleNamespace

    from groundwork_geophysics.core.colors import ColorScale
    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.core.ties import Tie, TieColumn
    from groundwork_geophysics.section.context_readout import context_hits
    from groundwork_geophysics.ui.ties_panel import build_rows

    scale = ColorScale("Spectral_r", 1.0, 1000.0, True)

    def column(name, values):
        n = len(values)
        return TieColumn(name, -np.arange(n, dtype=float), -np.arange(1, n + 1, dtype=float),
                         np.array(values, float), scale, "resistivity", "ohm.m")

    top = column("P3 top", [10.0, 10.0])
    for bottom in (column("P3 empty", []), column("P3 bottom", [500.0, 500.0])):
        tie = Tie(60.0, "p3", "P3", 30.0, 0.0, [bottom, top])
        items = ContextItems(ties=[tie])
        img = _img(_results(items))                                 # strip
        x = _x(60.0) + round(_mm(img, 1.5))
        assert _close(img.pixel(x, _y(-0.5)), tuple(scale.rgba(10.0)[0][:3])), bottom.dataset_name
        hits = context_hits(items, 60.5, -0.5, 0.1, 0.1, 1.0)       # readout
        assert [h for h in hits if h.startswith("Tie")] == ["Tie P3: 10.0 Ω·m"]
        back = Tie(30.0, "p1", "P1", 60.0, 0.0, [column("P1 model", [12.0, 12.0])])
        provider = SimpleNamespace(                                  # panel
            store=SimpleNamespace(profiles=lambda: [SimpleNamespace(id="p1", name="P1"),
                                                    SimpleNamespace(id="p3", name="P3")]),
            ties=lambda pid: {"p1": [tie], "p3": [back]}[pid])
        [row] = build_rows(provider)
        assert row.col_b is top


def test_tie_without_scale_draws_no_strip(qgis_app):
    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.core.ties import Tie, TieColumn

    col = TieColumn("P3 model", np.array([0.0]), np.array([-1.0]), np.array([np.nan]),
                    None, "resistivity", "ohm.m")
    img = _img(_results(ContextItems(ties=[Tie(60.0, "p3", "P3", 30.0, 6.0, [col])])))
    assert img.pixel(_x(60.0) + round(_mm(img, 1.5)), _y(-0.5)) == 0xFFFFFFFF


def test_zrange_includes_borehole_bottom(qgis_app):
    from groundwork_geophysics.core.colors import ColorScale
    from groundwork_geophysics.core.context import ContextItems, LogInterval, ProjectedPoint
    from groundwork_geophysics.core.ties import Tie, TieColumn
    from groundwork_geophysics.section.data import SectionSnapshot
    from groundwork_geophysics.section.profile_source import WorkbenchProfileGenerator

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


def test_point_with_depth_draws_stick(qgis_app):
    from groundwork_geophysics.core.context import ContextItems, ProjectedPoint
    from groundwork_geophysics.section.context_render_points import STICK_RGB

    deep = ProjectedPoint(50.0, 2.0, "Ig 1", "point", depth=2.5)
    flat = ProjectedPoint(70.0, 2.0, "Ig 2", "point")
    img = _img(_results(ContextItems(points=[deep, flat])))
    assert _close(img.pixel(_x(50.0), _y(-1.5)), STICK_RGB, tol=40)
    assert _close(img.pixel(_x(50.0), _y(-2.3)), STICK_RGB, tol=40)
    assert img.pixel(_x(50.0), _y(-2.8)) == 0xFFFFFFFF          # stops at the depth
    assert img.pixel(_x(70.0), _y(-1.5)) == 0xFFFFFFFF          # no depth: no stick


def test_band_draws_segment_rgb_and_distinct_label_colours(qgis_app):
    from groundwork_geophysics.core.context import BandSegment, ContextItems
    from groundwork_geophysics.core.lithology import label_colour

    assert label_colour("Sand, fein") != label_colour("Sand, grob")
    img = _img(_results(ContextItems(band=[BandSegment(50.0, 60.0, "Sand", rgb=(10, 20, 200)),
                                           BandSegment(60.0, 70.0, "Sand, grob")])))
    near, far = _band_offsets(img)
    y = _y(0.0) - round(0.5 * (near + far))
    assert _close(img.pixel(_x(51.0), y), _blend((10, 20, 200), 0.85))           # off the text
    assert _close(img.pixel(_x(69.0), y), _blend(label_colour("Sand, grob"), 0.85))


def _view_items(points, **view):
    from groundwork_geophysics.core.context import BoreholeView, ContextItems
    return ContextItems(points=points, borehole_views={0: BoreholeView(**view)})


def _bh60(**kw):
    from groundwork_geophysics.core.context import LogInterval, ProjectedPoint
    return ProjectedPoint(60.0, 1.0, "B1", "borehole", 0.0, [LogInterval(0.0, 2.5, "Sand")],
                          entry=0, **kw)


def test_section_column_uses_entry_width_px(qgis_app):
    from groundwork_geophysics.core.lithology import label_colour
    img = _img(_results(_view_items([_bh60()], column_px=40)))
    assert _close(img.pixel(_x(60.0) + 17, _y(-1.0)), label_colour("Sand"))
    assert img.pixel(_x(60.0) + 23, _y(-1.0)) == 0xFFFFFFFF


def test_flagged_borehole_has_red_marker(qgis_app):
    from groundwork_geophysics.section.borehole_draw import FLAG_RGB
    img = _img(_results(_view_items([_bh60(flagged=True, z_source="field", z_dem=-0.5)],
                                    column_px=16)))
    near = [img.pixel(_x(60.0) + dx, _y(0.0) - dy) for dx in range(-12, 13)
            for dy in range(0, 14)]
    assert any(_close(px, FLAG_RGB, tol=40) for px in near)
    plain = _img(_results(_view_items([_bh60()], column_px=16)))
    near = [plain.pixel(_x(60.0) + dx, _y(0.0) - dy) for dx in range(-12, 13)
            for dy in range(0, 14)]
    assert not any(_close(px, FLAG_RGB, tol=40) for px in near)


def _curve():
    from groundwork_geophysics.core.context import Curve
    return Curve("t:gr", "gr", "API", np.linspace(0.0, 2.5, 26), np.linspace(10, 140, 26))


def test_section_curves_off_by_default(qgis_app):
    img = _img(_results(_view_items([_bh60(curves=[_curve()])], column_px=16)))
    right = [img.pixel(_x(60.0) + dx, _y(-1.2)) for dx in range(12, 60)]
    assert all(px == 0xFFFFFFFF for px in right)


def test_section_curve_drawn_when_chosen(qgis_app):
    from groundwork_geophysics.core.borehole_curves import CurveStyle
    items = _view_items([_bh60(curves=[_curve()])], column_px=16, curve_keys=("t:gr",))
    items.curve_styles = {"t:gr": CurveStyle(colour="#00b400", width_mm=0.6)}
    img = _img(_results(items))
    right = [img.pixel(_x(60.0) + dx, _y(-1.2)) for dx in range(10, 80)]
    assert any(_close(px, (0, 180, 0), tol=50) for px in right)


def test_total_depth_counts_in_z_values(qgis_app):
    from groundwork_geophysics.core.context import ContextItems, ProjectedPoint
    from groundwork_geophysics.section.context_render import context_z_values
    p = ProjectedPoint(50.0, 0.0, "B", "borehole", 10.0, total_depth=7.0)
    assert context_z_values(ContextItems(points=[p]), None) == [3.0]


def test_section_layer_text_beside_the_column(qgis_app):
    """Layer text switched on for the entry: the interval's text is written right of the
    column on the section (dark text pixels there), nothing when switched off."""
    on = _img(_results(_view_items([_bh60()], column_px=16, layer_text=True)))
    off = _img(_results(_view_items([_bh60()], column_px=16, layer_text=False)))

    def dark(img):
        return sum(1 for dx in range(10, 70) for y in range(_y(-0.2), _y(-2.3))
                   if _close(img.pixel(_x(60.0) + dx, y), (40, 40, 40), tol=60))
    assert dark(on) > 5 and dark(off) == 0


def _mid(img, level):
    near, far = _band_offsets(img, level)
    return _y(0.0) - round(0.5 * (near + far))


def test_two_strips_stack_with_the_first_on_top(qgis_app):
    from groundwork_geophysics.core.context import BandSegment, ContextItems

    items = ContextItems(band=[BandSegment(50, 70, "Seesand", rgb=(10, 20, 200), strip=1,
                                           title="GK 25"),
                               BandSegment(50, 70, "Talsand", rgb=(200, 20, 10), strip=0,
                                           title="GÜK 300")])
    img = _img(_results(items))
    x = _x(68.0)                                            # off the label text
    assert _close(img.pixel(x, _mid(img, 1)), _blend((200, 20, 10), 0.85))    # strip 0 on top
    assert _close(img.pixel(x, _mid(img, 0)), _blend((10, 20, 200), 0.85))    # strip 1 lower
    assert _mid(img, 1) < _mid(img, 0) < _y(0.0)


def test_empty_strip_takes_no_room(qgis_app):
    from groundwork_geophysics.core.context import BandSegment, ContextItems, strips_of

    items = ContextItems(band=[BandSegment(50, 70, "A", rgb=(10, 20, 200), strip=0, title="a"),
                               BandSegment(50, 70, "B", rgb=(200, 20, 10), strip=2, title="c")])
    assert len(strips_of(items.band)) == 2
    img = _img(_results(items))
    x = _x(68.0)
    assert _close(img.pixel(x, _mid(img, 1)), _blend((10, 20, 200), 0.85))
    assert _close(img.pixel(x, _mid(img, 0)), _blend((200, 20, 10), 0.85))
    from groundwork_geophysics.section.context_render import context_headroom_px
    assert context_headroom_px(4.0, 10.0, True, strips=2) > context_headroom_px(4.0, 10.0, True)


def test_headroom_grows_with_strips():
    from groundwork_geophysics.section.context_render import context_headroom_px

    assert context_headroom_px(4.0, 10.0, True, strips=2) -         context_headroom_px(4.0, 10.0, True, strips=1) == pytest.approx(4.0 * (3.0 + 0.6))


def test_titles_dropped_on_short_strips(qgis_app):
    from qgis.PyQt.QtGui import QColor

    from groundwork_geophysics.core.context import BandSegment, ContextItems

    items = ContextItems(band=[BandSegment(50, 52, "Seesand", rgb=(240, 240, 120), title="GK 25")])
    img = _img(_results(items))
    dark = [(x, y) for x in range(_x(49.0), _x(53.0)) for y in range(max(0, _y(0.0) - 60), _y(0.0))
            if QColor(img.pixel(x, y)).lightness() < 30]
    assert not dark                                        # no title, no label text, nothing outside


def test_title_drawn_at_the_left_end_of_a_long_strip(qgis_app):
    from qgis.PyQt.QtGui import QColor

    from groundwork_geophysics.core.context import BandSegment, ContextItems

    items = ContextItems(band=[BandSegment(42, 78, "Seesand", rgb=(240, 240, 120), title="GK 25")])
    img = _img(_results(items))
    dark = [x for x in range(img.width()) for y in range(max(0, _y(0.0) - 60), _y(0.0))
            if QColor(img.pixel(x, y)).lightness() < 30]
    assert dark and min(dark) < _x(48.0)                   # title sits at the left end


def _dark(img, xs, ys):
    from qgis.PyQt.QtGui import QColor

    return [(x, y) for x in xs for y in ys if QColor(img.pixel(x, y)).lightness() < 30]


def test_title_follows_the_view_into_the_first_unit(qgis_app):
    """One unit 0..79 seen over 40..80: its title sits at the left edge of what is visible."""
    from groundwork_geophysics.core.context import BandSegment, ContextItems

    def image(title):
        return _img(_results(ContextItems(band=[BandSegment(
            0, 79, "Seesand", rgb=(240, 240, 120), title=title)])))
    with_title, without = image("GK 25"), image("")
    changed = [x for x in range(60) for y in range(with_title.height())
               if with_title.pixel(x, y) != without.pixel(x, y)]
    assert changed and min(changed) < 20


def test_title_height_follows_the_ground_under_it(qgis_app):
    """On sloping ground the title lies in its own strip, not at the unit's midpoint height."""
    from groundwork_geophysics.core.context import BandSegment, ContextItems

    topo = (np.array([40.0, 80.0]), np.array([0.0, -1.5]))
    items = ContextItems(band=[BandSegment(42, 78, "Seesand", rgb=(240, 240, 120), title="GK 25")])
    img = _img(_results(items, topo=topo))
    near, far = _band_offsets(img)

    def gy(s):
        return _y(-(s - 40.0) * 1.5 / 40.0)
    dark = [(x, y) for x, y in _dark(img, range(_x(42.0), _x(42.0) + 50), range(0, img.height()))
            if y < gy((x + 400.0) / 10.0) - 1]       # the drawn ground line is dark too
    assert dark
    for x, y in dark:
        ground = gy((x + 400.0) / 10.0)
        assert ground - far - 3 <= y <= ground - near + 3


def test_first_unit_keeps_its_label_beside_the_title(qgis_app):
    from groundwork_geophysics.core.context import BandSegment, ContextItems

    def dark_xs(label):
        items = ContextItems(band=[BandSegment(48, 78, label, rgb=(240, 240, 120),
                                               title="Geology GK 25 (LBGR, live service), geology GK 25")])
        img = _img(_results(items))
        near, far = _band_offsets(img)
        ys = range(_y(0.0) - round(far), _y(0.0) - round(near))
        return {x for x, _y_ in _dark(img, range(_x(48.0) + 2, _x(78.0) - 2), ys)}
    title_only, both = dark_xs(""), dark_xs("Seesand")
    assert max(title_only) > _x(48.0) + 120                 # the title is long: it passes the middle
    assert max(both) > max(title_only) + 20                 # and the label still fits beside it

