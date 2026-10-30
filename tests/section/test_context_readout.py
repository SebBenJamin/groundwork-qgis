"""The readout lines for third-party context under the cursor, and the second readout line."""
import numpy as np

from geophysics_workbench.core.context import (BandSegment, ContextItems, Crossing, LogInterval,
                                               ProjectedPoint)
from geophysics_workbench.core.ties import Tie, TieColumn
from geophysics_workbench.section.context_readout import context_hits
from geophysics_workbench.section.readout import format_readout

S = np.array([0.0, 100.0])


def _items():
    col = TieColumn("P3 model", np.array([100.0, 95.0]), np.array([95.0, 90.0]),
                    np.array([95.3, np.nan]), None, "resistivity", "ohm.m")
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


def test_borehole_without_top_hangs_from_the_surface():
    items = _items()
    items.points[0].z_top = None
    surface = (S, np.array([100.0, 100.0]))
    assert context_hits(items, 20.0, 95.0, 1.0, 0.5, surface=surface)[1].startswith("Borehole")
    assert not any(h.startswith("Borehole") for h in context_hits(items, 20.0, 95.0, 1.0, 0.5))


def test_readout_second_line():
    assert format_readout(5.0, 1.0, extra=[]) == "s = 5.0 m · z = 1.0 m"
    assert format_readout(5.0, 1.0, extra=["A", "B"]) == "s = 5.0 m · z = 1.0 m\nA · B"
