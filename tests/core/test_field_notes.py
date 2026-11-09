import numpy as np
import pytest

from geophysics_workbench.core.field_notes import (FieldNote, clamp_to_profile, note_range,
                                                   stations_to_chainage)

NAMES = [str(i) for i in range(1, 81)]
CHAIN = np.arange(80) * 0.5


def test_note_range_point_and_stretch():
    assert note_range(FieldNote("a", "p", 12.0, None, "fence")) == (12.0, 12.0)
    assert note_range(FieldNote("b", "p", 40.0, 30.0, "wet")) == (30.0, 40.0)


def test_stations_to_chainage_by_names():
    assert stations_to_chainage(NAMES, CHAIN, "23", "28") == (11.0, 13.5)
    assert stations_to_chainage(NAMES, CHAIN, " 7 ", None) == (3.0, None)
    with pytest.raises(ValueError):
        stations_to_chainage(NAMES, CHAIN, "23", "99")


def test_clamp_stretch_outside_profile():
    """Review Focus 5: a stretch beyond the profile is clamped, and the caller is told."""
    n, clamped = clamp_to_profile(FieldNote("a", "p", -5.0, 30.0, "x"), 20.0)
    assert (n.s_from, n.s_to, clamped) == (0.0, 20.0, True)
    n, clamped = clamp_to_profile(FieldNote("a", "p", 5.0, None, "x"), 20.0)
    assert (n.s_from, n.s_to, clamped) == (5.0, None, False)
