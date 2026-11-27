"""Radargrams as section layers: hung with their time zero on the ground and a radar velocity,
the leading samples that are not radar data kept out of what is drawn, the readout in
nanoseconds; changing the hanging never reads the file again."""
from dataclasses import replace

import numpy as np
import pytest

from groundwork_geophysics.core.model import Dataset, file_fingerprint, profile_from_stations
from groundwork_geophysics.core.trace_section import DisplayGain
from groundwork_geophysics.section import display_render
from groundwork_geophysics.section.data import SectionDataProvider, trace_limits
from groundwork_geophysics.section.readout import format_readout
from groundwork_geophysics.store.gpkg_store import ProjectStore
from gpr_files import write_dzt, write_pulseekko

NS = 1e-9
N_TRACES, N_SAMPLES = 11, 64              # 64 ns at 1 ns per sample, 50 scans per metre


def _radar_samples(n=N_TRACES, ns=N_SAMPLES):
    """Quiet traces with a direct wave at 4 ns and a reflector at 20 ns, GSSI's scan counter
    and marks in the first two samples."""
    a = np.zeros((n, ns), np.int16)
    a += np.random.default_rng(3).integers(-3, 4, a.shape).astype(np.int16)
    a[:, 4:7] = [400, -600, 300]
    a[:, 20:22] = [150, -150]
    a[:, 0] = np.arange(n) - 32768
    a[:, 1] = -7168
    return a


@pytest.fixture
def make(tmp_path):
    """``make(options, fmt="dzt") -> (provider, store, profile id)``: a profile of 0.2 m
    (stations at 0, 0.1 and 0.2 m, heights 500, 500.5, 501) holding a radargram of 11 traces
    50 scans per metre apart with ``options`` (velocity 1.0e8 m/s and time zero 4 ns unless
    given; None leaves one out)."""
    def factory(options, fmt="dzt", amplitudes=None, stations=None):
        folder = tmp_path / f"store{len(list(tmp_path.iterdir()))}"
        folder.mkdir()
        store = ProjectStore.create(folder / "p.gpkg", "EPSG:25832")
        if stations is None:
            stations = np.array([[0, 0, 500.0], [0.1, 0, 500.5], [0.2, 0, 501.0]])
        p, s = profile_from_stations("P1", "EPSG:25832", stations)
        store.save_profile(p)
        store.save_station_set(s)
        a = _radar_samples() if amplitudes is None else amplitudes
        if fmt == "dzt":
            path, reader = write_dzt(folder / "AAA_____023.DZT", a, float(N_SAMPLES)), "gssi_dzt"
        else:
            path = write_pulseekko(folder / "LINE00.DT1", a, float(N_SAMPLES), step_m=0.02,
                                   timezero_point=7)       # 6 ns
            reader = "pulseekko"
        from groundwork_geophysics import readers
        prov = readers.read(path, reader=reader).provenance
        opts = {"velocity": 1.0e8, "time_zero": 4 * NS, **options}
        opts = {k: v for k, v in opts.items() if v is not None}
        mt, sha = file_fingerprint(path)
        store.save_dataset(Dataset("g1", p.id, s.id, "gpr_section", str(path), mt, sha, reader,
                                   opts, prov, name="Radar"))
        return SectionDataProvider(store), store, p.id
    return factory


@pytest.fixture
def file_reads(monkeypatch):
    """How often a file is read by its reader (not from memory or the remembered read)."""
    from groundwork_geophysics import readers
    count = {"n": 0}
    real = readers.read

    def counted(*args, **kwargs):
        count["n"] += 1
        return real(*args, **kwargs)
    monkeypatch.setattr(readers, "read", counted)
    return count


def _change(provider, store, pid, **options):
    d = store.datasets(pid)[0]
    store.save_dataset(replace(d, reader_options={**d.reader_options, **options}))
    provider.notify_changed()


def test_a_radargram_hangs_with_its_time_zero_on_the_ground(make):
    provider, _store, pid = make({})
    (layer,) = provider.layers(pid)
    assert layer.error is None and layer.mesh is None
    placed = layer.traces
    s, z = provider.topography(pid)
    assert np.allclose(placed.z_top, np.interp(placed.section.x, s, z))
    assert placed.z_top[-1] == pytest.approx(501.0)
    assert placed.depths[4] == pytest.approx(0.0)              # the sample at time zero
    assert placed.depths[6] == pytest.approx(0.1)              # 2 ns at 0.1 m/ns, two-way
    assert list(placed.live_from) == [4] * N_TRACES
    assert placed.time_zero == pytest.approx(4 * NS) and placed.data_start == 2


def test_without_a_stored_zero_a_radargram_hangs_on_the_ground_or_at_a_datum(make):
    provider, _store, pid = make({"zero": None})
    s, z = provider.topography(pid)
    placed = provider.layers(pid)[0].traces
    assert np.allclose(placed.z_top, np.interp(placed.section.x, s, z))
    provider, _store, pid = make({"zero": "datum", "datum": 300.0})
    assert np.allclose(provider.layers(pid)[0].traces.z_top, 300.0)


def test_without_a_time_zero_the_files_or_zero_and_never_the_counter(make):
    provider, _store, pid = make({"time_zero": None})               # GSSI states none
    placed = provider.layers(pid)[0].traces
    assert placed.time_zero == 0.0 and list(placed.live_from) == [2] * N_TRACES
    provider, _store, pid = make({"time_zero": None}, fmt="pulseekko")   # TIMEZERO AT POINT 7
    placed = provider.layers(pid)[0].traces
    assert placed.time_zero == pytest.approx(6 * NS) and placed.data_start == 0
    assert list(placed.live_from) == [6] * N_TRACES


def test_missing_velocity_is_the_layers_error(make):
    provider, _store, pid = make({"velocity": None})
    (layer,) = provider.layers(pid)
    assert layer.traces is None
    assert "The velocity must be greater than 0 m/s. Set it in Dataset Info." in layer.error


@pytest.mark.parametrize("options, text", [
    ({"time_zero": 80 * NS}, "Time zero lies beyond the end of the record. Set it in Dataset Info."),
    ({"time_zero": "x"}, "Time zero must be a number. Set it in Dataset Info."),
    ({"velocity": 4.0e8}, "The velocity must be greater than 0 and not above the speed of light "
                          "(0.2998 m/ns). Set it in Dataset Info.")])
def test_a_time_zero_or_velocity_that_cannot_be_is_the_layers_error(make, options, text):
    provider, _store, pid = make(options)
    (layer,) = provider.layers(pid)
    assert layer.traces is None and text in layer.error


@pytest.mark.parametrize("change", [{"time_zero": 6 * NS}, {"velocity": 0.5e8}])
def test_hanging_a_radargram_again_does_not_read_the_file(make, file_reads, change):
    provider, store, pid = make({})
    made = file_reads["n"]                                         # the fixture's own read
    before = provider.layers(pid)[0].traces
    assert file_reads["n"] == made + 1
    _change(provider, store, pid, **change)
    after = provider.layers(pid)[0].traces
    assert file_reads["n"] == made + 1 and after.section.amplitudes is before.section.amplitudes
    if "time_zero" in change:
        assert after.depths[6] == pytest.approx(0.0) and list(after.live_from) == [6] * N_TRACES
    else:
        assert after.depths[6] == pytest.approx(0.05)


def test_the_colour_limits_leave_the_counter_samples_out(make):
    provider, _store, pid = make({})
    layer = provider.layers(pid)[0]
    assert layer.style.scale.vmax < 1000 and layer.style.scale.vmin == -layer.style.scale.vmax
    lo, hi = trace_limits(layer, layer.style)
    assert hi < 1000
    gained = replace(layer.style, gain=DisplayGain(dewow_window=3 * NS))
    assert trace_limits(layer, gained)[1] < 1000


def test_the_counter_samples_are_never_painted(make, monkeypatch):
    provider, _store, pid = make({})
    layer = provider.layers(pid)[0]
    seen = []
    real = display_render.reduce_image

    def spy(placed, *args, mute=None, **kwargs):
        seen.append(mute)
        return real(placed, *args, mute=mute, **kwargs)
    monkeypatch.setattr(display_render, "reduce_image", spy)
    display_render.clear_cache()
    shown = replace(layer, style=replace(layer.style, gain=DisplayGain(show_muted=True)))
    display_render._entry(shown)
    assert seen and all(m is not None and m[:, :2].all() and not m[:, 2:].any() for m in seen)


def test_gain_with_time_counts_from_time_zero_in_the_drawing(make):
    provider, store, pid = make({})
    layer = provider.layers(pid)[0]
    display_render.clear_cache()
    gained = replace(layer, style=replace(layer.style, gain=DisplayGain(time_power=1.0)))
    entry = display_render._entry(gained)
    a = layer.traces.section.amplitudes
    assert entry.shown[0, 4] == 0.0                              # at time zero
    assert entry.shown[0, 6] == pytest.approx(a[0, 6] * 2 * NS, rel=1e-5)
    assert np.isnan(entry.shown[:, :2]).all()
    path = display_render._level_path(replace(gained, level_cache=("folder", "read")))
    _change(provider, store, pid, time_zero=5 * NS)
    moved = provider.layers(pid)[0]
    moved = replace(moved, style=gained.style, level_cache=("folder", "read"))
    assert display_render._values_key(moved) != display_render._values_key(gained)
    assert display_render._level_path(moved) != path


def test_readout_in_nanoseconds_below_the_ground(make, qgis_app):
    provider, _store, pid = make({})
    x = provider.layers(pid)[0].traces.section.x[2]
    ground = provider.layers(pid)[0].traces.z_top[2]
    hits = provider.identify(pid, x, ground - 0.1)
    text = format_readout(x, ground - 0.1, hits=hits)
    amp = format_readout(0.0, hits=[{**hits[0], "trace": None}]).split("Radar: ")[1]
    assert text.endswith(f"Radar: {amp} · trace 3 · 2.0 ns · 0.10 m below the ground")
    assert provider.identify(pid, x, ground + 0.01) == []           # before time zero


def test_readout_of_a_radargram_at_a_datum_is_below_time_zero(make, qgis_app):
    provider, _store, pid = make({"zero": "datum", "datum": 300.0})
    x = provider.layers(pid)[0].traces.section.x[2]
    text = format_readout(x, 299.9, hits=provider.identify(pid, x, 299.9))
    assert text.endswith(" · trace 3 · 2.0 ns · 0.10 m below time zero")


def test_a_profile_with_only_radargrams_has_no_station_note_and_the_gpr_method(make):
    provider, store, pid = make({})
    from groundwork_geophysics.core.dataset_types import method_of
    assert method_of([d.kind for d in store.datasets(pid)]) == "gpr"
    assert provider.placement_note(pid) == ""


def test_a_radar_file_added_is_a_radargram_named_with_its_antenna(tmp_path, qgis_app):
    from groundwork_geophysics.ui.project_actions import add_model
    store = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p, s = profile_from_stations("P1", "EPSG:25832",
                                 np.array([[0, 0, 500.0], [0.1, 0, 500.5], [0.2, 0, 501.0]]))
    store.save_profile(p)
    store.save_station_set(s)
    path = write_dzt(tmp_path / "AAA_____023.DZT", _radar_samples(), float(N_SAMPLES))
    d = add_model(store, p.id, s.id, path, "gssi_dzt", {"velocity": 1.0e8}, "")
    assert d.kind == "gpr_section" and d.name == "AAA_____023 (270MHz)"
    assert d.provenance["reserved_samples"] == 2
    named = add_model(store, p.id, s.id, path, "gssi_dzt", {"velocity": 1.0e8}, "Mine")
    assert named.name == "Mine"


def test_a_new_radargram_starts_with_a_band_pass_around_its_antenna(make):
    # chosen by looking at real 100 / 270 / 400 MHz GSSI lines and a 250 MHz pulseEKKO line:
    # the band-pass takes out the noise far below the antenna's band that dewow left and AGC
    # lifted; the whole line's background keeps the long flat reflectors
    from groundwork_geophysics.section.data import radar_gain
    provider, _store, pid = make({})                    # 270MHz, 50 traces a metre
    layer = provider.layers(pid)[0]
    period = 1 / 270e6
    assert layer.style.gain == DisplayGain(band_low=pytest.approx(135e6),
                                           band_high=pytest.approx(540e6),
                                           agc_window=pytest.approx(5 * period),
                                           background="all")
    assert layer.style.clip_percent == 98.0
    assert radar_gain(None, 64 * NS) == DisplayGain(dewow_window=pytest.approx(3.2 * NS),
                                                    agc_window=pytest.approx(8 * NS),
                                                    background="all")
    assert radar_gain(100.0, 64 * NS).dewow_window is None


def test_a_radargram_keeps_the_look_it_was_given(make):
    provider, _store, pid = make({})
    layer = provider.layers(pid)[0]
    plain = replace(layer.style, gain=DisplayGain())
    provider.set_style("g1", plain)
    assert provider.layers(pid)[0].style.gain == DisplayGain()


def _saw_tooth(make, **options):
    """A 4 m radargram (201 traces) on ground that rises 0.5 m and falls back every metre."""
    xs = np.arange(0.0, 4.01, 0.5)
    stations = np.column_stack([xs, np.zeros(xs.size), 500.0 + 0.5 * (np.arange(xs.size) % 2)])
    return make(options, amplitudes=_radar_samples(n=201), stations=stations)


def test_the_ground_under_a_radargram_can_be_smoothed(make):
    provider, _store, pid = _saw_tooth(make, ground_smoothing=2.0)
    placed = provider.layers(pid)[0].traces
    x = placed.section.x
    assert x[-1] == pytest.approx(4.0)
    middle = (x >= 1.0) & (x <= 3.0)
    assert np.ptp(placed.z_top[middle]) < 0.02                  # the teeth are gone
    s, z = provider.topography(pid)
    assert np.ptp(np.interp(x[middle], s, z)) == pytest.approx(0.5)     # the drawn ground keeps them


@pytest.mark.parametrize("smoothing", [0.0, None])
def test_no_smoothing_hangs_on_the_ground_as_sampled(make, smoothing):
    provider, _store, pid = _saw_tooth(make, ground_smoothing=smoothing)
    placed = provider.layers(pid)[0].traces
    s, z = provider.topography(pid)
    assert np.allclose(placed.z_top, np.interp(placed.section.x, s, z))


def test_smoothing_the_ground_does_not_read_the_file_again(make, file_reads):
    from groundwork_geophysics.section.data import HANG_KEYS
    assert "ground_smoothing" in HANG_KEYS
    provider, store, pid = _saw_tooth(make)
    before = provider.layers(pid)[0].traces.z_top.copy()
    reads = file_reads["n"]
    _change(provider, store, pid, ground_smoothing=2.0)
    after = provider.layers(pid)[0].traces.z_top
    assert file_reads["n"] == reads and not np.allclose(before, after)
