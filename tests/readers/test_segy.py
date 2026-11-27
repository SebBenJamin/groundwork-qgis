"""SEG-Y sections read through segyio: samples as the file holds them, positions from the headers."""
import sys

import numpy as np
import pytest

from segy_files import require_segyio

require_segyio()

from groundwork_geophysics import readers  # noqa: E402
from groundwork_geophysics.libs import MissingLibrary  # noqa: E402
from groundwork_geophysics.readers.segy import inspect, table_positions  # noqa: E402
from segy_files import write_segy  # noqa: E402


def test_reads_ibm_floats_with_spacing(tmp_path):
    a = np.linspace(-1, 1, 12, dtype=np.float32).reshape(3, 4)
    r = readers.read(write_segy(tmp_path / "a.sgy", a, dt_us=2000), position="spacing", spacing=2.5)
    t = r.traces
    assert r.mesh is None and t.amplitudes.shape == (3, 4)
    assert np.allclose(t.amplitudes, a, atol=1e-6) and list(t.x) == [0.0, 2.5, 5.0]
    assert (t.first, t.step, t.domain) == (0.0, 0.002, "time")


def test_little_endian_int16_with_a_delay(tmp_path):        # the Eckernförde case
    a = np.arange(12, dtype=np.int16).reshape(3, 4)
    p = write_segy(tmp_path / "le.segy", a, dt_us=98, fmt=3, endian="little", delay_ms=6)
    t = readers.read(p, position="spacing", spacing=0.09).traces
    assert t.amplitudes.dtype == np.int16 and (t.amplitudes == a).all()
    assert t.first == pytest.approx(0.006) and t.step == pytest.approx(98e-6)
    assert inspect(p).endian == "little"


def test_inspect_lists_only_position_fields_that_change(tmp_path):   # the swisstopo case
    xy = np.array([[2637473, 1207148], [2637400, 1207300], [2637300, 1207500]])
    p = write_segy(tmp_path / "s.sgy", np.zeros((3, 4), np.float32), xy=xy, xy_field="source")
    info = inspect(p)
    assert list(info.positions) == ["source"]
    assert info.positions["source"] == ((2637473.0, 1207148.0), (2637300.0, 1207500.0))


def test_a_field_whose_x_or_y_never_changes_looks_like_line_metres(tmp_path):   # Carfax
    xy = np.array([[4, 0], [10, 0], [560, 0]])
    p = write_segy(tmp_path / "c.sgy", np.zeros((3, 4), np.float32), xy=xy, xy_field="source")
    info = inspect(p)
    assert list(info.positions) == ["source"] and info.flat == ("source",)
    xy = np.array([[2637473, 1207148], [2637400, 1207300], [2637300, 1207500]])
    p = write_segy(tmp_path / "s.sgy", np.zeros((3, 4), np.float32), xy=xy, xy_field="source")
    assert inspect(p).flat == ()


def test_scalar_minus_100_divides(tmp_path):
    xy = np.array([[56684695, 603940141], [56684000, 603940100]])
    p = write_segy(tmp_path / "s.sgy", np.zeros((2, 4), np.float32), xy=xy, scalar=-100)
    assert inspect(p).positions["source"][0] == (566846.95, 6039401.41)


def test_map_positions_go_through_the_distance_function(tmp_path):
    xy = np.array([[0, 0], [10, 0], [20, 0]])
    p = write_segy(tmp_path / "m.sgy", np.zeros((3, 4), np.float32), xy=xy)
    r = readers.read(p, position="map", xy_field="source", crs="EPSG:2056",
                     xy_to_distance=lambda e, n: (np.asarray(e) + 100.0, np.zeros(3), np.zeros(3, bool)))
    assert list(r.traces.x) == [100.0, 110.0, 120.0]
    assert r.provenance["max_offset"] == 0.0 and r.provenance["n_beyond"] == 0


def test_repeated_fixes_are_spread_evenly(tmp_path):         # Review Focus 3
    xy = np.array([[0, 0], [0, 0], [10, 0], [10, 0], [20, 0], [20, 0]])
    p = write_segy(tmp_path / "f.sgy", np.zeros((6, 4), np.float32), xy=xy)
    r = readers.read(p, position="map", xy_field="source", crs="EPSG:2056",
                     xy_to_distance=lambda e, n: (np.asarray(e, float), np.zeros(6), np.zeros(6, bool)))
    assert list(r.traces.x) == [0.0, 5.0, 10.0, 15.0, 20.0, 25.0]


def test_all_zero_positions_are_no_positions(tmp_path):      # Review Focus 3
    p = write_segy(tmp_path / "z.sgy", np.zeros((3, 4), np.float32))
    assert inspect(p).positions == {}
    with pytest.raises(ValueError, match="no positions"):
        readers.read(p, position="map", xy_field="cdp", crs="EPSG:2056", xy_to_distance=None)


@pytest.mark.parametrize("spacing", [None, 0.0, -1.0])
def test_spacing_must_be_positive(tmp_path, spacing):
    p = write_segy(tmp_path / "a.sgy", np.zeros((3, 4), np.float32))
    with pytest.raises(ValueError, match="trace spacing"):
        readers.read(p, position="spacing", spacing=spacing)


def test_depth_domain_and_a_corrected_step(tmp_path):
    p = write_segy(tmp_path / "d.sgy", np.zeros((3, 4), np.float32), dt_us=5000)
    t = readers.read(p, position="spacing", spacing=1.0, domain="depth", sample_step=5.0).traces
    assert (t.domain, t.step) == ("depth", 5.0)


def test_depth_without_a_step_reads_the_header_number_and_says_so(tmp_path):
    p = write_segy(tmp_path / "d.sgy", np.zeros((3, 4), np.float32), dt_us=4000)
    r = readers.read(p, position="spacing", spacing=1.0, domain="depth")
    assert r.traces.step == 4.0 and r.provenance["step_assumed"] is True


def test_a_zero_step_must_be_entered(tmp_path):
    p = write_segy(tmp_path / "z.sgy", np.zeros((3, 4), np.float32), dt_us=0)
    assert inspect(p).step == 0.0
    with pytest.raises(ValueError, match="no sample step"):
        readers.read(p, position="spacing", spacing=1.0)
    t = readers.read(p, position="spacing", spacing=1.0, sample_step=0.001).traces
    assert t.step == 0.001


def test_gathers_are_flagged_not_refused(tmp_path):
    p = write_segy(tmp_path / "g.sgy", np.zeros((4, 4), np.float32), cdp=[1, 1, 2, 2],
                   offsets=[10, 20, 10, 20])
    assert inspect(p).unstacked is True
    assert readers.read(p, position="spacing", spacing=1.0).provenance["unstacked"] is True


def test_one_offset_for_every_trace_is_not_a_gather(tmp_path):     # the Eckernförde case
    p = write_segy(tmp_path / "o.sgy", np.zeros((3, 4), np.float32), cdp=[1, 2, 3], offsets=[1, 1, 1])
    assert inspect(p).unstacked is False
    q = write_segy(tmp_path / "v.sgy", np.zeros((3, 4), np.float32), offsets=[5, 10, 15])
    assert inspect(q).unstacked is True


def test_cdp_numbers_become_the_trace_numbers(tmp_path):
    p = write_segy(tmp_path / "c.sgy", np.zeros((3, 4), np.float32), cdp=[101, 102, 103])
    info = inspect(p)
    assert info.numbers_from_cdp is True and info.unstacked is False
    t = readers.read(p, position="spacing", spacing=1.0).traces
    assert list(t.numbers) == [101, 102, 103]
    q = write_segy(tmp_path / "n.sgy", np.zeros((3, 4), np.float32))
    assert list(readers.read(q, position="spacing", spacing=1.0).traces.numbers) == [1, 2, 3]


def test_ascii_text_header_and_a_stated_velocity(tmp_path):
    p = write_segy(tmp_path / "t.sgy", np.zeros((2, 4), np.float32),
                   text="C1 Innomar\nC24 Sound Velocity: 1500 m/sec", ascii_text=True)
    info = inspect(p)
    assert "Innomar" in info.text and info.velocity == 1500.0


def test_ebcdic_text_header_is_decoded(tmp_path):
    p = write_segy(tmp_path / "e.sgy", np.zeros((2, 4), np.float32), text="C1 CLIENT SWISSTOPO")
    info = inspect(p)
    assert info.text.splitlines()[0].startswith("C1 CLIENT SWISSTOPO")
    assert len(info.text.split("\n")) == 40


def test_no_velocity_is_guessed(tmp_path):
    p = write_segy(tmp_path / "n.sgy", np.zeros((2, 4), np.float32), text="C1 VELOCITY 1500")
    assert inspect(p).velocity is None


def test_a_file_segyio_refuses_gets_a_plain_message(tmp_path):
    p = tmp_path / "bad.sgy"
    p.write_bytes(b"\0" * 5000)
    with pytest.raises(ValueError, match="segyio cannot read"):
        readers.read(p, position="spacing", spacing=1.0)


def test_detected_by_name_only(tmp_path):
    assert readers.detect(tmp_path / "x.SGY")[0] == "segy"
    assert readers.detect(tmp_path / "x.segy")[0] == "segy"
    assert "segy" not in readers.detect(tmp_path / "x.txt")


def test_without_segyio_the_error_names_the_library(tmp_path, monkeypatch):   # Review Focus 1
    monkeypatch.setitem(sys.modules, "segyio", None)
    with pytest.raises(MissingLibrary) as e:
        readers.read(tmp_path / "x.sgy", position="spacing", spacing=1.0)
    assert e.value.name == "segyio"


def test_arc_second_positions_become_degrees(tmp_path):
    xy = np.array([[10980000, 1800000], [10980360, 1800000]])
    p = write_segy(tmp_path / "g.sgy", np.zeros((2, 4), np.float32), xy=xy, scalar=-100, units=2)
    info = inspect(p)
    assert info.geographic is True
    (x0, y0), _ = info.positions["source"]
    assert x0 == pytest.approx(30.5) and y0 == pytest.approx(5.0)


def test_packed_dms_positions_are_refused_for_the_map(tmp_path):
    xy = np.array([[302000, 50000], [302100, 50000]])
    p = write_segy(tmp_path / "d.sgy", np.zeros((2, 4), np.float32), xy=xy, units=4)
    with pytest.raises(ValueError, match="packed degrees, minutes, seconds"):
        readers.read(p, position="map", xy_field="source", crs="EPSG:4326",
                     xy_to_distance=lambda e, n: (np.asarray(e, float), np.zeros(2), np.zeros(2, bool)))


def test_a_3d_volume_is_named(tmp_path):
    p = write_segy(tmp_path / "v.sgy", np.zeros((6, 4), np.float32),
                   inline=[1, 1, 1, 2, 2, 2], crossline=[1, 2, 3, 1, 2, 3])
    assert inspect(p).volume is True
    with pytest.raises(ValueError) as e:
        readers.read(p, position="spacing", spacing=1.0)
    assert str(e.value) == ("v.sgy: this is a 3D volume (2 inlines × 3 crosslines). "
                            "Groundwork shows 2D sections.")


def _table(tmp_path, rows):
    t = tmp_path / "pos.txt"
    t.write_text("cdp x y\n" + "\n".join(" ".join(str(v) for v in r) for r in rows) + "\n")
    return t


def test_positions_from_a_table_by_cdp_number(tmp_path):
    p = write_segy(tmp_path / "c.sgy", np.zeros((5, 4), np.float32), cdp=[101, 102, 103, 104, 105])
    _table(tmp_path, [[101, 1000, 2000], [103, 1020, 2000], [105, 1040, 2010]])
    cols = {"number": 0, "easting": 1, "northing": 2}
    r = readers.read(p, position="table", positions_file="pos.txt", positions_table={},
                     positions_columns=cols, crs="EPSG:2056",
                     xy_to_distance=lambda e, n: (np.asarray(e, float), np.zeros(5), np.zeros(5, bool)))
    assert list(r.traces.x) == [1000.0, 1010.0, 1020.0, 1030.0, 1040.0]
    xy = table_positions(tmp_path / "pos.txt", {}, cols, np.array([100, 101, 102, 103, 104, 105, 106]))
    assert xy[0].tolist() == [990.0, 2000.0] and xy[2].tolist() == [1010.0, 2000.0]
    assert xy[-1].tolist() == [1050.0, 2015.0]


def test_a_table_that_matches_nothing_says_so(tmp_path):
    p = write_segy(tmp_path / "c.sgy", np.zeros((3, 4), np.float32), cdp=[101, 102, 103])
    _table(tmp_path, [[1, 1000, 2000], [2, 1020, 2000], [103, 1040, 2000]])
    with pytest.raises(ValueError, match="fewer than two of the file's trace numbers"):
        readers.read(p, position="table", positions_file="pos.txt", positions_table={},
                     positions_columns={"number": 0, "easting": 1, "northing": 2}, crs="EPSG:2056",
                     xy_to_distance=lambda e, n: (np.asarray(e, float), np.zeros(3), np.zeros(3, bool)))
