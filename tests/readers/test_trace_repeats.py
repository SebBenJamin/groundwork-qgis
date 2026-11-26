"""Traces that share a position or run back along the line (a shot record, several passes)
are flagged, not refused; GPS-style repeated fixes along a line walked once are not."""
import numpy as np
import pytest


def _pingo():
    """The Lagoon Pingo supergather's pattern: 42 traces 4 m apart, then 70 traces repeating
    the last five positions."""
    line = np.column_stack([np.arange(42) * 4.0, np.zeros(42)])
    tail = np.tile(line[-5:], (14, 1))
    return np.vstack([line, tail])


def _gps():
    """Runs of 16 traces per GPS fix, always advancing (the Eckernförde case)."""
    fixes = np.column_stack([np.arange(20) * 10.0, np.arange(20) * 2.0])
    return np.repeat(fixes, 16, axis=0)


def test_the_helper_flags_shared_and_backward_positions():
    from groundwork_geophysics.readers.track import repeats
    assert repeats(_pingo()) is True
    assert repeats(_gps()) is False
    assert repeats(np.column_stack([np.arange(50) * 2.0, np.zeros(50)])) is False


def test_a_line_walked_back_is_flagged():
    from groundwork_geophysics.readers.track import repeats
    there = np.column_stack([np.arange(30) * 2.0, np.zeros(30)])
    assert repeats(np.vstack([there, there[::-1]])) is True


def test_one_position_coming_back_for_many_traces_is_flagged():
    """More than 10 % of the traces (and more than 5) at one position the line comes back
    to; one run of a held fix (GPS, or the padded ends of a stack) is spread out instead."""
    from groundwork_geophysics.readers.track import repeats
    line = np.column_stack([np.arange(60) * 2.0, np.zeros(60)])
    held = np.vstack([line[:30], np.repeat(line[30:31], 20, axis=0), line[31:]])
    assert repeats(held) is False
    back = np.vstack([line[:30], np.tile(np.vstack([line[30], line[31]]), (8, 1)), line[32:]])
    assert repeats(back) is True
    twice = np.vstack([line[:30], line[30:31], line[29:30], np.repeat(line[30:31], 4, axis=0),
                       line[31:]])
    assert repeats(twice) is False                 # 6 of 66 traces: under 10 %


def test_too_few_positions_say_nothing():
    from groundwork_geophysics.readers.track import repeats
    assert repeats(np.zeros((0, 2))) is False
    assert repeats(np.array([[0.0, 0.0], [1.0, 0.0]])) is False
    assert repeats(np.zeros((10, 2))) is False      # no position change: nothing to judge


segyio = pytest.importorskip("segyio")


def _write(tmp_path, name, xy):
    from segy_files import write_segy
    return write_segy(tmp_path / name, np.zeros((len(xy), 4), np.float32),
                      xy=np.round(np.asarray(xy) * 100).astype(int) + [50000000, 600000000],
                      scalar=-100, cdp=np.arange(1, len(xy) + 1))


def test_a_segy_with_the_pingo_pattern_is_flagged(tmp_path):
    from groundwork_geophysics import readers
    from groundwork_geophysics.readers.segy import inspect
    p = _write(tmp_path, "pingo.sgy", _pingo())
    info = inspect(p)
    assert info.unstacked is False and info.repeats is True
    r = readers.read(p, position="spacing", spacing=1.0)
    assert r.provenance["repeats"] is True


def test_gps_style_repeated_fixes_are_not_flagged(tmp_path):
    from groundwork_geophysics.readers.segy import inspect
    assert inspect(_write(tmp_path, "gps.sgy", _gps())).repeats is False


def test_a_straight_line_is_not_flagged(tmp_path):
    from groundwork_geophysics import readers
    from groundwork_geophysics.readers.segy import inspect
    p = _write(tmp_path, "line.sgy", np.column_stack([np.arange(60) * 2.0, np.zeros(60)]))
    assert inspect(p).repeats is False
    assert readers.read(p, position="spacing", spacing=1.0).provenance["repeats"] is False
