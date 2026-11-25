"""Well logs read from LAS 1.2 / 2.0 files: one well per file, depths in metres."""
from pathlib import Path

import numpy as np
import pytest
from pytest import approx

LAS = Path(__file__).resolve().parent.parent / "fixtures" / "las"


def test_a_las_2_file_in_feet():
    from groundwork_geophysics.core.las_log import read_las_log
    log = read_las_log(LAS / "bh1_feet.las")
    assert (log.well, log.uwi, log.version) == ("JW-11", "07D022", "2.0")
    assert log.depth == approx(np.array([10.0, 10.5, 11.0, 11.5, 12.0]) * 0.3048)
    assert [(c.mnemonic, c.unit, c.description) for c in log.curves] == [
        ("GR", "GAPI", "GAMMA RAY"), ("RES", "OHMM", "RESISTIVITY")]
    gr, res = log.curves
    assert np.isnan(gr.values[3]) and gr.values[2] == 55.5     # NULL is a gap
    assert np.isnan(res.values[1])


def test_a_wrapped_las_1_2_file_in_metres():
    from groundwork_geophysics.core.las_log import read_las_log
    log = read_las_log(LAS / "wrapped_metres.las")
    assert log.well == "Borehole 7"                    # the name after the colon (1.2)
    assert log.depth == approx([1.0, 2.0])
    sp, cali, cond = log.curves
    assert sp.values[0] == 12.5 and np.isnan(sp.values[1])
    assert cond.values == approx([30.0, 31.0]) and cond.unit == "MS/M"


def test_a_file_without_a_well_name():
    from groundwork_geophysics.core.las_log import read_las_log
    log = read_las_log(LAS / "no_name.las")
    assert log.well == "" and [c.mnemonic for c in log.curves] == ["GAMMA"]


@pytest.mark.parametrize("text, message", [
    ("hello", "not a LAS file"),
    ("~V\nVERS. 2.0 :\n~C\nTIME.S :\nX. :\n~A\n0 1\n", "depth"),
    ("~V\nVERS. 3.0 :\n~C\nDEPT.M :\n~A\n0\n", "LAS 3"),
])
def test_unusable_files_say_why(tmp_path, text, message):
    from groundwork_geophysics.core.las_log import read_las_log
    path = tmp_path / "x.las"
    path.write_text(text)
    with pytest.raises(ValueError, match=message):
        read_las_log(path)


def test_wells_are_matched_to_borehole_ids():
    from groundwork_geophysics.core.las_log import LasLog, guess_borehole
    ids = ["JW11", "JW12", "JW2-10", "07D099"]

    def log(well="", uwi=""):
        return LasLog(well=well, uwi=uwi)
    assert guess_borehole(log("JW-11"), "anything", ids) == "JW11"      # spelling eased
    assert guess_borehole(log("", "07D099"), "x", ids) == "07D099"      # by its UWI
    assert guess_borehole(log(), "jw2_10_gamma", ids) == "JW2-10"       # by the file name
    assert guess_borehole(log("Well 5"), "w5", ids) is None             # nothing fits
    assert guess_borehole(log("JW1"), "x", ["JW1A", "JW1B"]) is None    # not unique


def test_a_point_cloud_las_says_what_it_is(tmp_path):
    from groundwork_geophysics.core.las_log import read_las_log
    path = tmp_path / "cloud.las"
    path.write_bytes(b"LASF" + bytes(300))
    with pytest.raises(ValueError, match="point cloud"):
        read_las_log(path)
