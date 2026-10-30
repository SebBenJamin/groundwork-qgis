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
        crossings=[Crossing(10.0, "380 kV", "powerline", 75.0)],
        points=[ProjectedPoint(20.0, 4.0, "B1", "borehole", 100.0,
                               [LogInterval(0.0, 2.0, "Sand"), LogInterval(2.0, 6.5, "Ton")])],
        band=[BandSegment(0.0, 30.0, "Talsand")],
        ties=[Tie(40.0, "p3", "P3", 5.0, 0.0, [col])],
        dem=(S, np.array([61.2, 61.2])))


def test_context_hits_band_crossing_borehole_tie_dem():
    items, stations = _items(), (S, np.array([59.4, 59.4]))
    kw = dict(tol_s=1.0, column_half_width_s=0.5, strip_width_s=1.5, stations=stations)
    assert context_hits(items, 10.5, 99.0, **kw) == [
        "Surface geology: Talsand", "Crossing: 380 kV (powerline, 75°)",
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
