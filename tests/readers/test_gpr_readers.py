"""GSSI (.dzt) and pulseEKKO (.dt1 + .hd) radar files: samples as stored, times in seconds."""
import numpy as np
import pytest

from groundwork_geophysics import readers
from groundwork_geophysics.readers import gssi_dzt, pulseekko
from gpr_files import write_dzt, write_pulseekko

NS = 1e-9


def _ramp(n, ns, dtype=np.int16):
    return (np.arange(n * ns).reshape(n, ns) % 200 - 100).astype(dtype)


# --- GSSI ---------------------------------------------------------------------------------

def test_dzt_round_trip(tmp_path):
    a = _ramp(5, 16)
    r = readers.read(write_dzt(tmp_path / "a.DZT", a, range_ns=64.0))
    t = r.traces
    assert r.mesh is None and r.z_kind == "depth"
    assert t.amplitudes.dtype == np.int16 and (t.amplitudes == a).all()
    assert t.domain == "time" and t.first == 0.0
    assert t.step == pytest.approx(4 * NS)                  # range / samples
    assert np.allclose(t.x, [0.0, 0.02, 0.04, 0.06, 0.08])  # 50 scans per metre
    assert list(t.numbers) == [1, 2, 3, 4, 5]
    p = r.provenance
    assert p["reader"] == "gssi_dzt" and p["bits"] == 16 and p["window"] == pytest.approx(64 * NS)
    assert p["time_zero_file"] is None and p["antenna"] == "270MHz"


def test_dzt_inspect(tmp_path):
    info = gssi_dzt.inspect(write_dzt(tmp_path / "a.dzt", _ramp(11, 8), range_ns=40.0,
                                      scans_per_metre=20.0, antenna="400MHz"))
    assert (info.n_traces, info.n_samples) == (11, 8)
    assert info.step == pytest.approx(5 * NS) and info.window == pytest.approx(40 * NS)
    assert info.first == 0.0 and info.time_zero is None
    assert info.antenna == "400MHz" and info.frequency_mhz == 400.0
    assert info.trace_step == pytest.approx(0.05) and info.length == pytest.approx(0.5)
    assert info.start == 0.0 and info.positions == {}
    assert any("Samples 1 and 2" in s for s in info.notes)


def test_dzt_dielectric_gives_velocity_only_when_stated(tmp_path):
    info = gssi_dzt.inspect(write_dzt(tmp_path / "e.dzt", _ramp(3, 4), 10.0, dielectric=9.0))
    assert info.dielectric == 9.0
    assert info.velocity == pytest.approx(0.299792458e9 / 3)
    info = gssi_dzt.inspect(write_dzt(tmp_path / "n.dzt", _ramp(3, 4), 10.0))
    assert info.dielectric is None and info.velocity is None


def test_dzt_zero_level_file_is_zero(tmp_path):
    t = readers.read(write_dzt(tmp_path / "z.dzt", np.zeros((4, 8), np.int16), 10.0)).traces
    assert t.amplitudes.dtype == np.int16 and t.amplitudes.mean() == 0


def test_dzt_8_and_32_bit(tmp_path):
    a8 = (np.arange(24).reshape(3, 8) * 10 - 120).astype(np.int8)
    t = readers.read(write_dzt(tmp_path / "b8.dzt", a8, 10.0, bits=8)).traces
    assert t.amplitudes.dtype == np.int8 and (t.amplitudes == a8).all()
    a32 = (np.arange(24).reshape(3, 8) * 100_000 - 1_000_000).astype(np.int32)
    t = readers.read(write_dzt(tmp_path / "b32.dzt", a32, 10.0, bits=32)).traces
    assert t.amplitudes.dtype == np.int32 and (t.amplitudes == a32).all()


def test_dzt_other_bits_are_refused(tmp_path):
    p = write_dzt(tmp_path / "b24.dzt", _ramp(3, 8), 10.0, bits=24)
    with pytest.raises(ValueError, match=r"b24\.dzt: 24-bit GSSI files are not supported yet\."):
        readers.read(p)


def test_dzt_several_channels_are_refused(tmp_path):
    p = write_dzt(tmp_path / "c.dzt", _ramp(3, 8), 10.0, channels=2)
    with pytest.raises(ValueError, match=r"c\.dzt: this file holds 2 channels; Groundwork reads "
                                         r"single-channel files\."):
        gssi_dzt.inspect(p)


def test_dzt_without_distance_wheel(tmp_path):
    p = write_dzt(tmp_path / "t.dzt", _ramp(4, 8), 10.0, scans_per_metre=0.0)
    info = gssi_dzt.inspect(p)
    assert info.trace_step is None and info.length is None
    with pytest.raises(ValueError, match=r"t\.dzt: this file was recorded without a distance "
                                         r"wheel; enter the trace spacing\."):
        readers.read(p)
    t = readers.read(p, position="spacing", spacing=0.25).traces
    assert np.allclose(t.x, [0, 0.25, 0.5, 0.75])


def test_dzt_truncated_file_reads_whole_scans(tmp_path):
    p = write_dzt(tmp_path / "cut.dzt", _ramp(4, 8), 10.0)
    p.write_bytes(p.read_bytes()[:-5])
    info = gssi_dzt.inspect(p)
    assert info.n_traces == 3 and any("ends inside a scan" in s for s in info.notes)
    assert readers.read(p).traces.amplitudes.shape == (3, 8)
    p.write_bytes(p.read_bytes()[:1024 + 16 + 3])           # one scan and a bit
    with pytest.raises(ValueError, match="fewer than 2 whole scans"):
        readers.read(p)


def test_dzt_position_note_and_unknown_position(tmp_path):
    p = write_dzt(tmp_path / "pos.dzt", _ramp(3, 4), 10.0, position_ns=12.0)
    assert any("12 ns" in s for s in gssi_dzt.inspect(p).notes)
    with pytest.raises(ValueError, match="unknown trace position"):
        readers.read(p, position="map")


def test_dzt_positions_from_a_coordinate_table(tmp_path):
    p = write_dzt(tmp_path / "tab.dzt", _ramp(3, 4), 10.0)
    (tmp_path / "xy.csv").write_text("n,e,n2\n1,100,0\n3,104,0\n", encoding="ascii")
    seen = {}

    def to_line(e, n):
        seen["e"] = np.asarray(e)
        return np.asarray(e) - 100.0, np.zeros(len(e))

    t = readers.read(p, position="table", positions_file="xy.csv",
                     positions_columns={"number": 0, "easting": 1, "northing": 2},
                     xy_to_distance=to_line).traces
    assert np.allclose(seen["e"], [100, 102, 104]) and np.allclose(t.x, [0, 2, 4])


# --- pulseEKKO ----------------------------------------------------------------------------

def test_pulseekko_round_trip_and_time_zero(tmp_path):
    a = _ramp(6, 30)
    p = write_pulseekko(tmp_path / "LINE00.DT1", a, window_ns=6.0, step_m=0.1,
                        timezero_point=11.0, start=2.0)
    r = readers.read(p)
    t = r.traces
    assert t.amplitudes.dtype == np.int16 and (t.amplitudes == a).all()
    assert t.step == pytest.approx(0.2 * NS) and t.first == 0.0 and t.domain == "time"
    assert np.allclose(t.x, 2.0 + 0.1 * np.arange(6))
    assert r.provenance["time_zero_file"] == pytest.approx(10 * 0.2 * NS)   # (11 - 1) x step
    assert r.provenance["reader"] == "pulseekko"


def test_pulseekko_inspect(tmp_path):
    p = write_pulseekko(tmp_path / "L.dt1", _ramp(5, 10), window_ns=20.0, frequency=100.0)
    info = pulseekko.inspect(p)
    assert (info.n_traces, info.n_samples) == (5, 10)
    assert info.window == pytest.approx(20 * NS) and info.step == pytest.approx(2 * NS)
    assert info.time_zero is None and info.velocity is None and info.dielectric is None
    assert info.frequency_mhz == 100.0 and info.antenna == "100MHz"
    assert info.trace_step == pytest.approx(0.1) and info.length == pytest.approx(0.4)
    assert info.positions == {} and info.notes == []


def test_pulseekko_hd_path_reads_the_same(tmp_path):
    a = _ramp(4, 10)
    p = write_pulseekko(tmp_path / "LINE01.DT1", a, window_ns=10.0)
    one = readers.read(p).traces
    two = readers.read(tmp_path / "LINE01.HD").traces
    assert (one.amplitudes == two.amplitudes).all() and np.allclose(one.x, two.x)


def test_pulseekko_missing_partner(tmp_path):
    p = write_pulseekko(tmp_path / "LINE02.DT1", _ramp(3, 4), window_ns=4.0)
    hd = tmp_path / "LINE02.HD"
    hd_text = hd.read_bytes()
    hd.unlink()
    with pytest.raises(ValueError, match=r"LINE02\.DT1: the header file LINE02\.HD is missing "
                                         r"beside it\."):
        readers.read(p)
    hd.write_bytes(hd_text)
    p.unlink()
    with pytest.raises(ValueError, match=r"LINE02\.HD: the trace file LINE02\.DT1 is missing "
                                         r"beside it\."):
        pulseekko.inspect(hd)


def test_pulseekko_positions_that_do_not_increase(tmp_path):
    p = write_pulseekko(tmp_path / "s.dt1", _ramp(4, 4), window_ns=4.0, step_m=0.5, start=1.0,
                        positions=[0, 0, 0, 0])
    t = readers.read(p).traces
    assert np.allclose(t.x, [1.0, 1.5, 2.0, 2.5])
    assert any("do not increase" in s for s in pulseekko.inspect(p).notes)


def test_pulseekko_header_positions_win(tmp_path):
    p = write_pulseekko(tmp_path / "w.dt1", _ramp(3, 4), window_ns=4.0,
                        positions=[0.0, 0.3, 0.7])
    assert np.allclose(readers.read(p).traces.x, [0.0, 0.3, 0.7])
    t = readers.read(p, position="spacing", spacing=2).traces
    assert np.allclose(t.x, [0, 2, 4])


def test_pulseekko_window_conflict_is_noted(tmp_path):
    p = write_pulseekko(tmp_path / "c.dt1", _ramp(3, 10), window_ns=150.0, trace_window_ns=200.0)
    info = pulseekko.inspect(p)
    assert info.window == pytest.approx(150 * NS)
    assert any("200 ns" in s and "150 ns" in s for s in info.notes)


def test_pulseekko_truncated(tmp_path):
    p = write_pulseekko(tmp_path / "t.dt1", _ramp(4, 10), window_ns=10.0)
    p.write_bytes(p.read_bytes()[:-7])
    info = pulseekko.inspect(p)
    assert info.n_traces == 3
    assert any("ends inside a trace" in s for s in info.notes)
    assert any("lists 4 traces" in s for s in info.notes)
    assert readers.read(p).traces.amplitudes.shape == (3, 10)
    p.write_bytes(p.read_bytes()[:150])
    with pytest.raises(ValueError, match="fewer than 2 whole traces"):
        readers.read(p)


def test_pulseekko_zero_level_mean(tmp_path):
    p = write_pulseekko(tmp_path / "z.dt1", np.zeros((3, 6), np.int16), window_ns=6.0)
    assert readers.read(p).traces.amplitudes.mean() == 0


# --- detection ----------------------------------------------------------------------------

def test_detection_by_extension(tmp_path):
    dzt = write_dzt(tmp_path / "a.DZT", _ramp(3, 4), 10.0)
    dt1 = write_pulseekko(tmp_path / "L.DT1", _ramp(3, 4), window_ns=4.0)
    assert readers.detect(dzt)[0] == "gssi_dzt"
    assert readers.detect(dt1)[0] == "pulseekko"
    assert readers.detect(tmp_path / "L.HD")[0] == "pulseekko"
    lone = tmp_path / "other.hd"
    lone.write_text("not a radar header", encoding="ascii")
    assert "pulseekko" not in readers.detect(lone)
    dat = tmp_path / "x.dat"
    dat.write_text("1 2 3\n", encoding="ascii")
    assert not {"pulseekko", "gssi_dzt"} & set(readers.detect(dat))
    assert "pulseekko" not in readers.detect(tmp_path / "missing" / "nothing.hd")   # never raises
    names = readers.names()
    assert names.index("segy") < names.index("gssi_dzt") < names.index("pulseekko") \
        < names.index("refrapy_xzv")


def test_the_readers_say_how_many_leading_samples_are_not_radar_data(tmp_path):
    r = readers.read(write_dzt(tmp_path / "a.dzt", _ramp(3, 16), 64.0))
    assert r.provenance["reserved_samples"] == gssi_dzt.RESERVED == 2
    assert r.provenance["kind"] == "gpr_section" and r.provenance["method"] == "gpr"
    p = readers.read(write_pulseekko(tmp_path / "L.DT1", _ramp(3, 16), 32.0)).provenance
    assert p["reserved_samples"] == 0 and p["kind"] == "gpr_section"


def test_a_radar_file_is_named_after_its_file_and_antenna(tmp_path):
    dzt = write_dzt(tmp_path / "AAA_____023.DZT", _ramp(3, 16), 64.0, antenna="270MHz")
    assert readers.default_name(dzt) == "AAA_____023 (270MHz)"
    assert readers.default_name(dzt, "gssi_dzt") == "AAA_____023 (270MHz)"
    nameless = write_dzt(tmp_path / "b.dzt", _ramp(3, 16), 64.0, antenna="")
    assert readers.default_name(nameless) == "b"
    line = write_pulseekko(tmp_path / "LINE00.DT1", _ramp(3, 16), 32.0, frequency=250.0)
    assert readers.default_name(line) == "LINE00 (250MHz)"
    assert readers.default_name(line.with_suffix(".HD")) == "LINE00 (250MHz)"
    assert readers.default_name(tmp_path / "model.vtk") == "model"      # other kinds: the stem
    assert readers.default_name(tmp_path / "gone.dzt") == "gone"        # unreadable: the stem
