import numpy as np
import pytest

from geophysics_workbench.core.chainage import Chainage
from geophysics_workbench.core.lines import line_from_cloud, line_through, order_of
from geophysics_workbench.core.model import (Profile, attach_positions, profile_from_polyline,
                                             profile_from_positions)
from geophysics_workbench.core.placement import Positions


def _xyz(xs):
    return np.column_stack([xs, np.zeros(len(xs)), np.full(len(xs), 100.0)]).astype(float)


def test_order_by_number_then_distance_then_file():
    xyz = _xyz([0, 10, 20, 30])
    numbers = np.array([3, 1, 4, 2])
    inline = np.array([5.0, 15.0, 0.0, 10.0])
    assert order_of(Positions(xyz, numbers, inline)).tolist() == [1, 3, 0, 2]
    assert order_of(Positions(xyz, None, inline)).tolist() == [2, 0, 3, 1]
    assert order_of(Positions(xyz, None, np.array([5.0, np.nan, 0.0, 10.0]))).tolist() == \
        [0, 1, 2, 3]
    assert order_of(Positions(xyz)).tolist() == [0, 1, 2, 3]


def test_line_follows_the_numbers():                     # rows 16, 1, 20, 5, 10
    numbers = np.array([16, 1, 20, 5, 10])
    profile, stations = profile_from_positions("P", "EPSG:25832",
                                               Positions(_xyz(2.0 * numbers), numbers))
    assert profile.xy[:, 0].tolist() == [2.0, 10.0, 20.0, 32.0, 40.0]
    assert stations.numbers.tolist() == [1, 5, 10, 16, 20]
    assert stations.chainage.tolist() == pytest.approx([0, 8, 18, 30, 38])
    assert stations.profile_id == profile.id


def test_positions_without_numbers_follow_the_inline_distance():
    inline = np.array([10.0, 0.0, 5.0])
    profile, stations = profile_from_positions("P", "EPSG:25832",
                                               Positions(_xyz([20, 0, 10]), None, inline))
    assert profile.xy[:, 0].tolist() == [0.0, 10.0, 20.0]
    assert stations.numbers.tolist() == [1, 2, 3]
    assert stations.inline.tolist() == [0.0, 5.0, 10.0]


def test_duplicate_positions_are_named():
    with pytest.raises(ValueError, match="rows 2 and 3"):
        line_through(np.array([[0, 0], [5, 0], [5, 0], [9, 0]]))


def test_positions_closer_than_a_micrometre_are_the_same():
    with pytest.raises(ValueError, match="rows 1 and 3"):
        line_through(np.array([[0, 0], [5, 0], [1e-7, 0]]))


def test_duplicate_rows_are_named_in_input_order():
    xyz = _xyz([10, 0, 10])
    with pytest.raises(ValueError, match="rows 1 and 3"):
        profile_from_positions("P", "EPSG:25832", Positions(xyz, np.array([3, 1, 2])))


def test_a_line_needs_two_points():
    with pytest.raises(ValueError, match="two"):
        line_through(np.array([[0.0, 0.0]]))


def test_repeated_numbers_are_named():
    xyz = _xyz([0, 5, 5])
    with pytest.raises(ValueError, match="number 5 appears twice"):
        profile_from_positions("P", "EPSG:25832", Positions(xyz, numbers=np.array([1, 5, 5])))


def _bent_cloud():
    ch = Chainage(np.array([[0.0, 0.0], [100.0, 0.0], [100.0, 50.0]]))
    xy = ch.to_xy(np.arange(0.0, 150.0 + 1e-9, 2.0))
    return np.repeat(xy, 4, axis=0)                      # four depths per position


def test_cloud_of_a_bent_line():
    line, bends = line_from_cloud(_bent_cloud())
    assert bends == 1 and Chainage(line).length == pytest.approx(150, abs=1)


def test_cloud_order_does_not_matter():
    xy = _bent_cloud()
    line, bends = line_from_cloud(xy[np.random.default_rng(1).permutation(len(xy))])
    assert bends == 1 and Chainage(line).length == pytest.approx(150, abs=1)


def test_cloud_of_an_area_is_refused():
    gx, gy = np.meshgrid(np.arange(0.0, 50.0, 2.0), np.arange(0.0, 50.0, 2.0))
    grid_xy = np.column_stack([gx.ravel(), gy.ravel()])
    with pytest.raises(ValueError, match="area or a 3D model"):
        line_from_cloud(grid_xy)


def test_profile_from_polyline_has_no_stations():
    xy = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 0.0], [10.0, 5.0]])
    profile = profile_from_polyline("P", "EPSG:25832", xy)
    assert isinstance(profile, Profile)
    assert profile.xy.tolist() == [[0, 0], [10, 0], [10, 5]]
    assert profile.chainage.length == pytest.approx(15)
    assert profile_from_polyline("P", "EPSG:25832", xy, reverse=True).xy.tolist() == \
        [[10, 5], [10, 0], [0, 0]]
    with pytest.raises(ValueError):
        profile_from_polyline("P", "EPSG:25832", np.array([[1.0, 1.0], [1.0, 1.0]]))


def test_attach_positions_keeps_inline_and_warns_off_line():
    profile = profile_from_polyline("P", "EPSG:25832", np.array([[0.0, 0.0], [20.0, 0.0]]))
    xyz = np.array([[0.0, 0.0, 100.0], [9.5, 7.0, 101.0]])
    s = attach_positions(profile, "P", "ert", Positions(xyz, np.array([1, 5]),
                                                       np.array([0.0, 9.5])))
    assert s.inline.tolist() == [0.0, 9.5] and s.warnings == ["station 5: 7.0 m off line"]
    assert s.chainage.tolist() == pytest.approx([0.0, 9.5])
    assert profile.xy.tolist() == [[0, 0], [20, 0]]


def test_attach_positions_numbers_follow_the_order():
    profile = profile_from_polyline("P", "EPSG:25832", np.array([[0.0, 0.0], [20.0, 0.0]]))
    s = attach_positions(profile, "P", "ert",
                         Positions(_xyz([15, 5]), None, np.array([10.0, 0.0])))
    assert s.numbers.tolist() == [1, 2] and s.chainage.tolist() == pytest.approx([5, 15])
    assert s.inline.tolist() == [0.0, 10.0]
