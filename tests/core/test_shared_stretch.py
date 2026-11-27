"""Profiles that run along each other: their many crossings are one shared stretch with one
tie at its middle; ordinary crossings stay as they are."""
import numpy as np
import pytest

A = np.array([[0.0, 0.0], [300.0, 0.0]])


def _interleaved():
    """A line coming from the south, zigzagging across A from x = 97.5 to 202.5 (crossing
    it every 5 m, at x = 100, 105, ..., 200) and leaving to the north."""
    x = 97.5 + 5.0 * np.arange(22)
    y = np.where(np.arange(22) % 2 == 0, -1.0, 1.0)
    zig = np.column_stack([x, y])
    return np.vstack([[97.5, -50.0], zig, [202.5, 50.0]])


def test_interleaved_lines_give_one_shared_stretch_with_its_start_and_end():
    from groundwork_geophysics.core.chainage import Chainage
    from groundwork_geophysics.core.context import profile_ties, tie_hits
    b = _interleaved()
    [hit] = tie_hits(A, b, near_miss=10.0)
    assert hit.stretch == pytest.approx((100.0, 200.0))
    assert hit.s == pytest.approx(150.0)
    assert hit.distance == 0.0
    x, y = Chainage(b).to_xy(hit.s_other)
    assert abs(x - 150.0) < 1.5 and abs(y) < 1.5        # the other line at the middle
    assert profile_ties(A, b, near_miss=10.0) == [(hit.s, hit.s_other, 0.0)]


def test_two_real_crossings_200_m_apart_stay_two():
    from groundwork_geophysics.core.context import tie_hits
    b = np.array([[50.0, -20.0], [50.0, 20.0], [250.0, 20.0], [250.0, -20.0]])
    hits = tie_hits(A, b, near_miss=10.0)
    assert [round(h.s) for h in hits] == [50, 250]
    assert all(h.stretch is None for h in hits)


def test_a_profile_crossed_twice_8_m_apart_by_a_wiggly_line_keeps_two_crossings():
    from groundwork_geophysics.core.context import tie_hits
    b = np.array([[100.0, -20.0], [100.0, 5.0], [108.0, 5.0], [108.0, -20.0]])
    hits = tie_hits(A, b, near_miss=10.0)
    assert [round(h.s) for h in hits] == [100, 108]
    assert all(h.stretch is None for h in hits)


def test_crossings_far_apart_along_long_profiles_are_grouped_by_5_percent_of_the_shorter():
    """Two profiles of 1000 m and more: crossings up to 50 m apart belong together."""
    from groundwork_geophysics.core.context import tie_hits
    a = np.array([[0.0, 0.0], [1000.0, 0.0]])
    x = 380.0 + 40.0 * np.arange(7)                     # crossings 40 m apart: 400 .. 600
    y = np.where(np.arange(7) % 2 == 0, -1.0, 1.0)
    b = np.vstack([[380.0, -500.0], np.column_stack([x, y]), [620.0, -500.0]])
    [hit] = tie_hits(a, b, near_miss=10.0)
    assert hit.stretch == pytest.approx((400.0, 600.0))


def _long_and_short():
    """A 2 km line and a 126 m one zigzagging across it four times, 30 m apart (at x =
    1000, 1030, 1060, 1090)."""
    long_ = np.array([[0.0, 0.0], [2000.0, 0.0]])
    short = np.array([[985.0, -5.0], [1015.0, 5.0], [1045.0, -5.0], [1075.0, 5.0],
                      [1105.0, -5.0]])
    return long_, short


def test_a_long_and_a_short_profile_show_the_same_ties_on_both():
    from groundwork_geophysics.core.context import tie_hits
    long_, short = _long_and_short()
    from_long = tie_hits(long_, short, near_miss=10.0)
    from_short = tie_hits(short, long_, near_miss=10.0)
    assert len(from_long) == len(from_short) == 4
    assert all(h.stretch is None for h in from_long + from_short)
    assert sorted(h.s for h in from_long) == pytest.approx(sorted(h.s_other for h in from_short))


@pytest.mark.parametrize("swap", [False, True])
def test_a_shared_stretch_is_the_same_from_both_profiles(swap):
    from groundwork_geophysics.core.chainage import Chainage
    from groundwork_geophysics.core.context import tie_hits
    a, b = (A, _interleaved()) if not swap else (_interleaved(), A)
    [ab] = tie_hits(a, b, near_miss=10.0)
    [ba] = tie_hits(b, a, near_miss=10.0)
    assert (ab.s, ab.s_other) == pytest.approx((ba.s_other, ba.s))      # one tie point
    gap = np.hypot(*(Chainage(a).to_xy(ab.s) - Chainage(b).to_xy(ab.s_other)))
    assert gap < 1.5                                     # the two ends of the tie meet
    assert ab.stretch is not None and ba.stretch is not None


def test_a_mirrored_section_mirrors_the_stretch():
    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.core.ties import Tie
    items = ContextItems(ties=[Tie(150.0, "b", "R2", 40.0, 0.0, [], stretch=(100.0, 200.0))])
    [back] = items.mirrored(300.0).ties
    assert back.s == 150.0 and back.stretch == (100.0, 200.0)
    items = ContextItems(ties=[Tie(130.0, "b", "R2", 40.0, 0.0, [], stretch=(100.0, 160.0))])
    [back] = items.mirrored(300.0).ties
    assert back.s == 170.0 and back.stretch == (140.0, 200.0)
