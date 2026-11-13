import numpy as np
import pytest

from geophysics_workbench.core.placement import (Placement, Positions, fit_report, pinned_map,
                                                 rigid_map)


def test_rigid_map():
    assert rigid_map(10.0, -1)([0.0, 5.0]).tolist() == [10.0, 5.0]


def test_between_pins_distances_are_stretched_evenly():
    m = pinned_map([0, 50, 75], [0.0, 50.0, 73.4])
    assert m([50, 62.5, 75]).tolist() == pytest.approx([50.0, 61.7, 73.4])


def test_outside_the_pins_one_metre_per_metre():
    m = pinned_map([0, 50, 75], [0.0, 50.0, 73.4])
    assert m([-5, 80]).tolist() == pytest.approx([-5.0, 78.4])


def test_pinned_map_against_the_line():                  # station 1 at the far end
    m = pinned_map([0, 50, 75], [100.0, 50.0, 26.6])
    assert m.direction == -1 and m([-5, 62.5, 80]).tolist() == pytest.approx([105.0, 38.3, 21.6])


def test_a_pin_out_of_order_is_named():
    with pytest.raises(ValueError, match="16"):
        pinned_map([0, 50, 75, 100], [0.0, 50.0, 40.0, 98.0], labels=["1", "11", "16", "21"])


def test_fit_report_text(qgis_app):
    r = fit_report([0, 50, 75, 100, 125], [0.0, 50.0, 73.4, 99.0, 124.5], ["1", "11", "16", "21", "26"])
    assert (r.n, r.at, r.warn) == (5, "16", False) and r.max_shift == pytest.approx(-1.6)
    assert r.text("electrode") == "5 known points, largest shift 1.6 m at electrode 16"
    assert r.text("electrode", guessed=True).endswith("(pinned with a guessed spacing)")


def test_fit_report_warns_above_half_the_median_gap():
    assert fit_report([0, 10, 20], [0.0, 10.0, 28.0], ["1", "2", "3"]).warn


# Edge cases the brief leaves to the implementer (decided by the controller).

def test_rigid_map_is_a_single_pin():
    m = rigid_map(10.0, -1)
    assert m.d.tolist() == [0.0] and m.s.tolist() == [10.0] and not m.pinned


def test_pinned_map_sorts_by_file_distance():
    m = pinned_map([75, 0, 50], [73.4, 0.0, 50.0])
    assert m.pinned and m.d.tolist() == [0.0, 50.0, 75.0] and m.s.tolist() == [0.0, 50.0, 73.4]


def test_two_pins_at_one_distance_are_named():
    with pytest.raises(ValueError, match=r"points 11 and 16 "):
        pinned_map([0, 50, 50], [0.0, 50.0, 60.0], labels=["1", "11", "16"])


def test_without_labels_a_pin_is_named_by_its_position_in_the_input():
    with pytest.raises(ValueError, match=r"point 2 is out of order"):  # 2nd given, 3rd sorted
        pinned_map([50, 75, 0], [50.0, 40.0, 0.0])
    with pytest.raises(ValueError, match=r"point 3 is out of order"):
        pinned_map([0, 50, 75, 100], [0.0, 50.0, 40.0, 98.0])


def test_placement_defaults():
    p = Placement()
    assert (p.profile_id, p.line_xy, p.positions, p.zero, p.offset, p.spacing,
            p.replace_line) == (None, None, None, "start", 0.0, None, False)
    pos = Positions(np.zeros((2, 3)))
    assert pos.numbers is None and pos.inline is None


def test_fit_report_with_fewer_than_two_pins():
    r = fit_report([10.0], [12.0], ["1"])
    assert (r.n, r.max_shift, r.at, r.warn) == (1, 0.0, "", False)


def test_positions_and_placement_compare_by_identity():
    a = Positions(np.zeros((3, 3)), numbers=np.arange(3))
    b = Positions(np.zeros((3, 3)), numbers=np.arange(3))
    assert a == a and a != b                      # no "truth value of an array" error
    p = Placement(line_xy=np.zeros((2, 2)), positions=a)
    assert p == p and p != Placement(line_xy=np.zeros((2, 2)), positions=a)
