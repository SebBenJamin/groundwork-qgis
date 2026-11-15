"""The readout lines for third-party context under the cursor, and the second readout line."""
import numpy as np

from geophysics_workbench.core.colors import ColorScale
from geophysics_workbench.core.context import (BandSegment, ContextItems, Crossing, LogInterval,
                                               ProjectedPoint)
from geophysics_workbench.core.ties import Tie, TieColumn
from geophysics_workbench.section.context_readout import context_hits
from geophysics_workbench.section.readout import format_readout

S = np.array([0.0, 100.0])


def _items():
    col = TieColumn("P3 model", np.array([100.0, 95.0]), np.array([95.0, 90.0]),
                    np.array([95.3, np.nan]), ColorScale(), "resistivity", "ohm.m")
    return ContextItems(
        crossings=[Crossing(10.0, "380 kV", "line", 75.0, (220, 0, 0), "Powerline (OSM)")],
        points=[ProjectedPoint(20.0, 4.0, "B1", "borehole", 100.0,
                               [LogInterval(0.0, 2.0, "Sand"), LogInterval(2.0, 6.5, "Ton")])],
        band=[BandSegment(0.0, 30.0, "Talsand")],
        ties=[Tie(40.0, "p3", "P3", 5.0, 0.0, [col])],
        dem=(S, np.array([61.2, 61.2])))


def test_context_hits_band_crossing_borehole_tie_dem():
    items, stations = _items(), (S, np.array([59.4, 59.4]))
    kw = dict(tol_s=1.0, column_half_width_s=0.5, strip_width_s=1.5, stations=stations)
    assert context_hits(items, 10.5, 99.0, **kw) == [
        "Surface geology: Talsand", "Crossing: 380 kV · Powerline (OSM), 75°",
        "DEM 61.2 m (stations −1.8 m)"]
    assert context_hits(items, 20.2, 95.0, **kw) == [
        "Surface geology: Talsand", "Borehole B1 (+4 m): 2.0–6.5 m Ton",
        "DEM 61.2 m (stations −1.8 m)"]
    assert context_hits(items, 40.7, 97.0, **kw) == [
        "Tie P3: 95.3 Ω·m", "DEM 61.2 m (stations −1.8 m)"]
    # beyond every tolerance: only the DEM; between intervals/values: nothing extra
    assert context_hits(items, 35.0, 97.0, **kw) == ["DEM 61.2 m (stations −1.8 m)"]
    assert context_hits(items, 20.2, 80.0, **kw)[-1].startswith("DEM")
    assert not any(h.startswith("Borehole") for h in context_hits(items, 20.2, 80.0, **kw))
    assert not any(h.startswith("Tie") for h in context_hits(items, 40.7, 92.0, **kw))
    assert not any(h.startswith("Tie") for h in context_hits(items, 39.9, 97.0, **kw))
    assert context_hits(items, 20.7, 95.0, **kw)[-1].startswith("DEM")
    assert not any(h.startswith("Borehole") for h in context_hits(items, 20.7, 95.0, **kw))
    # defaults: no stations -> bare DEM; strip width defaults to the column width
    assert context_hits(items, 35.0, 97.0, 1.0, 0.5) == ["DEM 61.2 m"]
    assert context_hits(items, 41.2, 97.0, 1.0, 0.5) == ["DEM 61.2 m"]
    # a positive gap and a missing DEM
    up = context_hits(items, 35.0, 97.0, 1.0, 0.5, stations=(S, np.array([63.0, 63.0])))
    assert up == ["DEM 61.2 m (stations +1.8 m)"]
    items.dem = (S, np.array([np.nan, np.nan]))
    assert context_hits(items, 35.0, 97.0, 1.0, 0.5) == []


def test_no_tie_readout_where_no_strip_is_drawn():
    """A column without a colour scale draws no strip, so the readout shows no value."""
    items = _items()
    kw = dict(tol_s=1.0, column_half_width_s=0.5, strip_width_s=1.5)
    assert context_hits(items, 40.7, 97.0, **kw)[0] == "Tie P3: 95.3 Ω·m"
    items.ties[0].columns[0].scale = None
    assert not any(h.startswith("Tie") for h in context_hits(items, 40.7, 97.0, **kw))


def test_borehole_without_top_hangs_from_the_surface():
    items = _items()
    items.points[0].z_top = None
    surface = (S, np.array([100.0, 100.0]))
    assert context_hits(items, 20.0, 95.0, 1.0, 0.5, surface=surface)[1].startswith("Borehole")
    assert not any(h.startswith("Borehole") for h in context_hits(items, 20.0, 95.0, 1.0, 0.5))


def test_readout_second_line():
    assert format_readout(5.0, 1.0, extra=[]) == "s = 5.0 m · z = 1.0 m"
    assert format_readout(5.0, 1.0, extra=["A", "B"]) == "s = 5.0 m · z = 1.0 m\nA · B"


def test_strip_start_is_the_nearest_free_slot_beside_the_tie_line():
    """R15: right of the tie line unless a borehole column stands there; then left of the
    line when that is free, else just past the columns, on the nearer side (right on a draw)."""
    from geophysics_workbench.section.context_readout import strip_start

    items = _items()                                        # B1 column at 20 +- 0.5
    pts = items.points
    assert strip_start(pts, 40.0, 1.5, 0.5) == 40.0         # nothing near: right of the line
    assert strip_start(pts, 19.0, 1.5, 0.5) == 17.5         # column right of the line: left
    assert strip_start(pts, 21.0, 1.5, 0.5) == 21.0         # column left of the line: stays
    assert strip_start(pts, 18.0, 1.5, 0.5) == 18.0         # strip ends at 19.5, column at 19.5
    assert strip_start(pts, 20.0, 1.5, 0.5) == 20.5         # column on the line: past it, right
    assert strip_start(pts, 20.2, 1.5, 0.5) == 20.5         # nearer past its right edge
    assert strip_start(pts, 19.8, 1.5, 0.5) == 18.0         # nearer past its left edge
    pts.append(type(pts[0])(21.5, 0.0, "B9", "borehole", 100.0, list(pts[0].log)))
    assert strip_start(pts, 20.0, 1.5, 0.5) == 18.0         # right blocked twice: left wins
    pts[0].log = []                                         # no log: a diamond, not a column
    assert strip_start(pts[:1], 20.0, 1.5, 0.5) == 20.0


def test_tie_readout_follows_the_strip_off_a_borehole_column():
    """R15: the readout reads the tie where the strip is drawn."""
    items = _items()
    kw = dict(tol_s=1.0, column_half_width_s=0.5, strip_width_s=1.5)
    items.points[0].s = 40.0                                # B1 on the P3 tie: strip 40.5 .. 42
    assert "Tie P3: 95.3 Ω·m" in context_hits(items, 41.8, 97.0, **kw)
    for s in (39.0, 40.2):
        assert not any(h.startswith("Tie") for h in context_hits(items, s, 97.0, **kw))
    items.points[0].s = 41.0                                # B1 right of the line: strip 38.5 .. 40
    assert "Tie P3: 95.3 Ω·m" in context_hits(items, 39.0, 97.0, **kw)
    for s in (38.4, 40.7):
        assert not any(h.startswith("Tie") for h in context_hits(items, s, 97.0, **kw))


def test_crossing_readout_omits_layer_when_same_as_label():
    items = ContextItems(crossings=[Crossing(10.0, "Road", "line", 90.0, layer="Road")])
    assert context_hits(items, 10.0, 0.0, tol_s=1.0, column_half_width_s=0.5) == [
        "Crossing: Road, 90°"]


def test_details_show_height_source_flag_interval_and_curves():
    from geophysics_workbench.core.context import Curve
    from geophysics_workbench.section.context_readout import borehole_details
    p = ProjectedPoint(20.0, 4.0, "B1", "borehole", 25.0,
                       [LogInterval(0.0, 1.0, "Topsoil"), LogInterval(1.0, 3.0, "Sand")],
                       z_source="field", z_dem=23.0, flagged=True,
                       curves=[Curve("t:gr", "gr", "API", np.array([1.0, 3.0]),
                                     np.array([40.0, 50.0]))])
    lines = borehole_details(ContextItems(points=[p]), 20.0, 23.0, 0.5)
    assert lines[1] == "Top 25.00 m (field; DEM 23.00 m, differs by 2.00 m)"
    assert "  1.00\u20133.00 m  Sand  \u2190 here" in lines
    assert "gr: 45.0 API (interpolated)" in lines


def test_details_say_when_the_surface_gives_the_height():
    from geophysics_workbench.section.context_readout import borehole_details
    p = ProjectedPoint(20.0, 4.0, "B1", "borehole", None, [LogInterval(0.0, 2.0, "Sand")])
    lines = borehole_details(ContextItems(points=[p]), 20.0, 99.0, 0.5,
                             (S, np.array([100.0, 100.0])))
    assert lines[1].startswith("Top 100.00 m (surface)")


def test_hover_lists_curve_values_at_the_cursor_depth():
    from geophysics_workbench.core.context import Curve
    p = ProjectedPoint(20.0, 4.0, "B1", "borehole", 100.0, [LogInterval(0.0, 4.0, "Sand")],
                       curves=[Curve("t:gr", "gr", "API", np.array([1.0, 3.0]),
                                     np.array([40.0, 50.0]))])
    hits = context_hits(ContextItems(points=[p]), 20.0, 98.0, 1.0, lambda q: 0.5)
    assert "Borehole B1 gr: 45.0 API (interpolated)" in hits


def test_per_borehole_half_widths():
    near = ProjectedPoint(20.0, 4.0, "N", "borehole", 100.0, [LogInterval(0.0, 4.0, "Sand")])
    wide = ProjectedPoint(30.0, 4.0, "W", "borehole", 100.0, [LogInterval(0.0, 4.0, "Clay")])
    half = {id(near): 0.2, id(wide): 3.0}
    hits = context_hits(ContextItems(points=[near, wide]), 27.5, 98.0, 1.0,
                        lambda q: half[id(q)])
    assert any("Borehole W" in h for h in hits) and not any("Borehole N" in h for h in hits)



def test_readout_shows_small_curve_values_and_respects_log_gaps():
    """Minor 4: 0.004 S/m is not shown as 0.0; on a log scale no value across a <= 0 gap."""
    from geophysics_workbench.core.borehole_curves import CurveStyle
    from geophysics_workbench.core.context import Curve
    from geophysics_workbench.section.context_readout import curve_lines
    p = ProjectedPoint(20.0, 0.0, "B1", "borehole", 100.0, curves=[
        Curve("t:c", "cond", "S/m", np.array([1.0, 3.0]), np.array([0.004, 0.004])),
        Curve("t:r", "res", "ohm.m", np.array([1.0, 2.0, 3.0]), np.array([10.0, 0.0, 30.0]))])
    lines = curve_lines(p, 1.5, {"t:r": CurveStyle(log=True)})
    assert "cond: 0.004 S/m (interpolated)" in lines
    assert not any(line.startswith("res") for line in lines)



def test_hover_over_a_curve_track_right_of_the_column():
    """Minor 8: the curve track drawn right of the column also answers the readout."""
    from geophysics_workbench.core.context import BoreholeView, Curve
    p = ProjectedPoint(20.0, 4.0, "B1", "borehole", 100.0, [LogInterval(0.0, 4.0, "Sand")],
                       entry=0, curves=[Curve("t:gr", "gr", "API", np.array([1.0, 3.0]),
                                              np.array([40.0, 50.0]))])
    items = ContextItems(points=[p], borehole_views={0: BoreholeView(16, 1.0, False,
                                                                     ("t:gr",))})
    half = lambda q: 0.5
    right = lambda q: 3.0                                   # track: 3 m right of the column
    hits = context_hits(items, 22.0, 98.0, 0.1, half, right_extent_s=right)
    assert "Borehole B1 gr: 45.0 API (interpolated)" in hits
    assert not any("B1" in h for h in context_hits(items, 22.0, 98.0, 0.1, half))


def test_readout_one_line_per_strip():
    items = ContextItems(band=[BandSegment(0, 30, "Talsand", strip=0, title="GÜK 300"),
                               BandSegment(0, 30, "Seesand", strip=1, title="GK 25")])
    lines = context_hits(items, 10.0, 0.0, tol_s=1.0, column_half_width_s=0.5)
    assert lines[:2] == ["GÜK 300: Talsand", "GK 25: Seesand"]
    plain = ContextItems(band=[BandSegment(0, 30, "Talsand")])
    assert context_hits(plain, 10.0, 0.0, tol_s=1.0, column_half_width_s=0.5) == [
        "Surface geology: Talsand"]
