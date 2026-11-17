"""Electrode numbers read from point names: the digit runs, each row's status, the list order
and the positions made from the rows that stay."""
import numpy as np
import pytest

from groundwork_geophysics.core.placement import Positions
from groundwork_geophysics.core.point_names import (
    CLEARED, CORRECTED, NO_NUMBER, OK, TWICE, apply_names, list_order, names_title,
    number_from_name, read_names, station_label)


@pytest.mark.parametrize("name, last, first", [
    ("ERT03_15", 15, 3), ("E15", 15, 15), ("T1_15", 15, 1), ("15_2", 2, 15), ("15a", 15, 15),
    ("007", 7, 7), ("ERT-15", 15, 15), ("15.5", 5, 15), ("15", 15, 15), ("Base", None, None),
    ("GCP3", 3, 3), ("", None, None), ("   ", None, None)])
def test_number_from_name(name, last, first):
    assert number_from_name(name, "last") == last
    assert number_from_name(name, "first") == first


def test_rows_get_statuses():
    rows = read_names(["Base", "GCP3", "E1", "E2", "E3", "E3"])
    assert [r.status for r in rows] == [NO_NUMBER, TWICE, OK, OK, TWICE, OK]
    assert [r.number for r in rows] == [None, 3, 1, 2, 3, 3]
    assert list_order(rows) == [0, 1, 4, 2, 3, 5]
    assert names_title(rows) == "Electrodes from names: 6 rows, 3 to check"


def test_corrections_and_clearing():
    rows = read_names(["E1", "E2", "E2x", "Base"], corrections={2: 3, 0: None})
    assert [r.status for r in rows] == [CLEARED, OK, CORRECTED, NO_NUMBER]
    assert [r.guess for r in rows] == [1, 2, 2, None]
    assert names_title(rows) == "Electrodes from names: 4 rows, 1 to check"


def test_correction_can_clash():
    rows = read_names(["E1", "E2", "E3"], corrections={0: 3})
    assert [r.status for r in rows] == [TWICE, OK, OK]


def test_names_title_without_problems_and_singular():
    assert names_title(read_names(["E1"])) == "Electrodes from names: 1 row"


def test_apply_names_keeps_used_rows():
    xyz = np.array([[0, 0, 1], [10, 0, 2], [20, 0, 3], [30, 0, 4]], dtype=float)
    raw = Positions(xyz, None, np.array([0.0, 10, 20, 30]), names=["Base", "E1", "E2", "E2"])
    pos, rows = apply_names(raw)
    assert pos.numbers.tolist() == [1, 2] and pos.names == ["E1", "E2"]
    np.testing.assert_allclose(pos.xyz[:, 0], [10, 30])          # the later E2 is used
    np.testing.assert_allclose(pos.inline, [10, 30])
    assert len(rows) == 4


def test_apply_names_first_number_and_corrections():
    xyz = np.array([[0, 0, 1], [10, 0, 2]], dtype=float)
    raw = Positions(xyz, names=["T1_15", "T1_16"])
    pos, _ = apply_names(raw, "first", {1: 2})
    assert pos.numbers.tolist() == [1, 2] and pos.inline is None


def test_apply_names_needs_names():
    with pytest.raises(ValueError):
        apply_names(Positions(np.zeros((2, 3))))


def test_station_label():
    assert station_label("ERT03_15", 15) == "ERT03_15"
    assert station_label("", 15) == "15" and station_label("  ", 7) == "7"
