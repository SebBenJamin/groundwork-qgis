import json

import pytest

from geophysics_workbench.core.plates import (FrameLook, FrameSpec, ModelLook, PlateSpec,
                                              nice_scale, nice_ve, plates_from_json,
                                              plates_to_json, stack_fit)


def test_nice_scale_picks_the_largest_standard_scale_that_fits():
    assert nice_scale(200, 380) == (750, True)             # 267 mm of 380
    assert nice_scale(150, 380) == (400, True)             # 375 mm of 380


def test_nice_scale_too_long_and_degenerate():
    """Review Focus 3."""
    assert nice_scale(40000, 380) == (50000, False)
    assert nice_scale(0, 380) == (100, True)
    assert nice_scale(100, 0) == (50000, False)


def test_nice_ve():
    assert nice_ve(10, 100, 1000) == 10.0           # 10 m over 100 mm at 1:1000
    assert nice_ve(10, 37, 1000) == 3.0             # max 3.7 -> 3
    assert nice_ve(10, 5, 1000) == 1.0              # does not fit even at 1x: 1x
    assert nice_ve(0, 100, 1000) == 20.0            # nothing to show: the largest


def _frame(fid, pid, **kw):
    return FrameSpec(fid, pid, FrameLook([], None, True, True, False), **kw)


def test_stack_fit_frames_of_one_profile_share_scale_ve_and_range():
    frames = [_frame("a", "P1"), _frame("b", "P1"), _frame("c", "P2")]
    extents = {"a": (0, 200, 15, 25), "b": (10, 180, 10, 25), "c": (0, 80, 20, 30)}
    out = stack_fit(frames, extents, [(380, 80), (380, 80), (380, 80)])
    assert out[0] == out[1]
    scale, ve, s0, s1 = out[0]
    assert (scale, s0, s1) == (750, 0, 200)            # union of a and b
    assert ve == nice_ve(15, 80, 750)
    assert out[2][0] == 250


def test_stack_fit_keeps_user_scale_ve_and_range():
    frames = [_frame("a", "P1", s_from=20, s_to=60, scale=500, ve=2.0)]
    assert stack_fit(frames, {"a": (0, 200, 15, 25)}, [(380, 80)]) == [(500, 2.0, 20, 60)]


def test_plate_round_trip_and_bad_json():
    look = FrameLook([ModelLook("d1", True, 0.8, {"cmap": "viridis", "vmin": 1.0,
                                                  "vmax": 1000.0, "log": True}, "smooth")],
                     "v1", True, False, True)
    plates = [PlateSpec("pl1", "3", "Transect 3", "A3_landscape",
                        [FrameSpec("f1", "P3", look, 0.0, 100.0, None, 2.5)])]
    assert plates_from_json(plates_to_json(plates)) == plates
    assert plates_from_json("nonsense") == [] and plates_from_json(json.dumps({"x": 1})) == []
    assert plates_from_json(json.dumps([{"plate_id": "x"}])) == []


def test_stack_fit_coarsens_the_scale_until_the_depth_fits():
    """Review I2: three stacked frames on A4 (interior ~230 x 25 mm), a 50 m profile 10 m
    deep: 1:250 would need 40 mm at VE 1, so the depth was cut off silently."""
    from geophysics_workbench.core.plates import frame_fits
    [(scale, ve, s0, s1)] = stack_fit([_frame("a", "P1")], {"a": (0, 50, 0, 10)}, [(230, 25)])
    assert scale == 400 and ve == 1.0                   # 10 m -> 25 mm at 1:400
    assert frame_fits(50, 10, (230, 25), scale, ve)
    assert not frame_fits(40000, 10, (230, 25), 50000, 1.0)     # even 1:50000 too small


def test_provenance_says_when_a_frame_does_not_fit():
    import numpy as np

    from geophysics_workbench.core.model import Chainage
    from geophysics_workbench.plates.build import provenance_text

    class P:
        name = "Long line"
        chainage = Chainage(np.array([[0.0, 0.0], [40000.0, 0.0]]))
    assert "does not fit" in provenance_text(P(), [], 50000, 1.0, fits=False)
    assert "does not fit" not in provenance_text(P(), [], 50000, 1.0)
