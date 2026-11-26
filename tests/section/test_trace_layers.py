"""Reflection sections as section layers: placed along the profile, hung from the ground or a
datum, with their colour scale, readout and extent; beside a cell model nothing changes."""
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("segyio")

from groundwork_geophysics.core.model import (Dataset, file_fingerprint,  # noqa: E402
                                              profile_from_polyline, profile_from_stations)
from groundwork_geophysics.section.data import (LayerStyle, SectionDataProvider,  # noqa: E402
                                                is_map_dataset, layer_bounds, read_options,
                                                trace_limits)
from groundwork_geophysics.section.readout import format_readout  # noqa: E402
from groundwork_geophysics.store.gpkg_store import ProjectStore  # noqa: E402
from segy_files import write_segy  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
#: 11 traces x 50 samples at 1 ms, signed
AMPLITUDES = np.sin(np.arange(11 * 50, dtype=np.float32) / 3.0).reshape(11, 50)


def _segy(tmp_path, amplitudes=AMPLITUDES):
    return write_segy(tmp_path / "line.sgy", amplitudes, dt_us=1000, fmt=5)


def _add(store, pid, set_id, path, options, did="s1", kind="refl_section", reader="segy"):
    mt, sha = file_fingerprint(path)
    d = Dataset(did, pid, set_id, kind, str(path), mt, sha, reader, options, {}, name="Line 1")
    store.save_dataset(d)
    return d


@pytest.fixture
def make(tmp_path):
    """``make(options, heights=True) -> (provider, store, profile id)``: a profile 100 m long
    (stations at 0, 50 and 100 m, heights 500, 505, 510 when ``heights``, else a bare line)
    holding the test section with ``options`` (spacing 10 m and velocity 2000 m/s unless
    given). ``heights`` may also be the three station heights."""
    def factory(options, heights=True, amplitudes=AMPLITUDES):
        folder = tmp_path / f"store{len(list(tmp_path.iterdir()))}"
        folder.mkdir()
        store = ProjectStore.create(folder / "p.gpkg", "EPSG:25832")
        if heights:
            z = (500.0, 505.0, 510.0) if heights is True else heights
            p, s = profile_from_stations("P1", "EPSG:25832",
                                         np.array([[0, 0, z[0]], [50, 0, z[1]], [100, 0, z[2]]]))
            store.save_profile(p)
            store.save_station_set(s)
            set_id = s.id
        else:
            p = profile_from_polyline("P1", "EPSG:25832", np.array([[0.0, 0.0], [100.0, 0.0]]))
            store.save_profile(p)
            set_id = ""
        opts = {"position": "spacing", "spacing": 10.0, "velocity": 2000.0, **options}
        opts = {k: v for k, v in opts.items() if v is not None}
        _add(store, p.id, set_id, _segy(folder, amplitudes), opts)
        return SectionDataProvider(store), store, p.id
    return factory


def test_a_section_at_a_datum_is_a_trace_layer(make):
    provider, _store, pid = make({"zero": "datum", "datum": 500.0})
    (layer,) = provider.layers(pid)
    assert layer.error is None and layer.mesh is None
    assert layer_bounds(layer) == pytest.approx((0.0, 100.0, 500.0 - 49.0, 500.0))
    assert layer.style.scale.log is False and layer.style.scale.cmap == "gray"
    lo, hi = trace_limits(layer, layer.style)
    assert (layer.style.scale.vmin, layer.style.scale.vmax) == pytest.approx((lo, hi))
    assert lo == pytest.approx(-hi)


def test_all_positive_data_get_the_reversed_grey(make):
    provider, _store, pid = make({"zero": "datum", "datum": 500.0},
                                 amplitudes=np.abs(AMPLITUDES) + 1.0)
    scale = provider.layers(pid)[0].style.scale
    assert scale.cmap == "gray_r" and scale.vmin == 0.0


def test_the_samples_are_shared_not_copied(make):
    provider, _store, pid = make({"zero": "datum", "datum": 500.0})
    layer = provider.layers(pid)[0]
    read = provider._cache[layer.dataset.id][1].traces
    assert np.shares_memory(layer.traces.section.amplitudes, read.amplitudes)


def test_a_section_on_the_ground_follows_the_surface(make):
    provider, _store, pid = make({"zero": "ground"})
    (layer,) = provider.layers(pid)
    s, z = provider.topography(pid)
    assert np.allclose(layer.traces.z_top, np.interp(layer.traces.section.x, s, z))
    assert layer.traces.z_top[-1] == pytest.approx(510.0)


def test_the_ground_is_the_default_zero(make):
    provider, _store, pid = make({})
    (layer,) = provider.layers(pid)
    assert layer.error is None and layer.traces.z_top[0] == pytest.approx(500.0)


def test_without_any_surface_a_section_hangs_from_zero_like_a_depth_model(make):
    provider, _store, pid = make({"zero": "ground"}, heights=False)
    (layer,) = provider.layers(pid)
    assert layer.error is None and np.allclose(layer.traces.z_top, 0.0)
    assert provider.is_local(pid)


def test_missing_velocity_is_the_layers_error(make):
    provider, _store, pid = make({"velocity": None})
    (layer,) = provider.layers(pid)
    assert layer.traces is None and layer.mesh is None
    assert "velocity" in layer.error and "Dataset Info" in layer.error
    assert "The velocity must be greater than 0 m/s. Set it in Dataset Info." in layer.error


def test_a_depth_section_needs_no_velocity(make):
    provider, _store, pid = make({"velocity": None, "domain": "depth", "sample_step": 2.0,
                                  "zero": "datum", "datum": 300.0})
    (layer,) = provider.layers(pid)
    assert layer.error is None
    assert layer_bounds(layer) == pytest.approx((0.0, 100.0, 300.0 - 98.0, 300.0))


def test_datum_missing_is_the_layers_error(make):
    provider, _store, pid = make({"zero": "datum"})
    layer = provider.layers(pid)[0]
    assert layer.traces is None and "height of time zero" in layer.error
    provider, _store, pid = make({"zero": "datum", "datum": "nan"})
    assert "height of time zero" in provider.layers(pid)[0].error


def test_identify_gives_amplitude_trace_time_and_depth(make):
    provider, _store, pid = make({"zero": "datum", "datum": 500.0})
    (hit,) = provider.identify(pid, 20.0, 500.0 - 10.0)
    assert hit["quantity"] == "amplitude" and hit["trace"]["number"] == 3
    assert hit["trace"]["time"] == pytest.approx(0.010) and hit["trace"]["depth"] == pytest.approx(10.0)
    assert hit["value"] == pytest.approx(float(AMPLITUDES[2, 10])) and hit["unit"] == ""
    assert {"name", "version", "dataset_id", "s", "z"} <= set(hit)
    assert provider.identify(pid, 20.0, 500.0 + 5.0) == []           # above time zero


def test_readout_line(make, qgis_app):
    provider, _store, pid = make({"zero": "datum", "datum": 500.0})
    text = format_readout(20.0, 490.0, hits=provider.identify(pid, 20.0, 490.0))
    assert "trace 3" in text and "10.0 ms" in text and "10.0 m" in text
    assert "Line 1: " in text


def test_readout_of_a_depth_section_has_no_time(qgis_app):
    hit = {"name": "D", "value": 1.5, "unit": "", "trace": {"number": 7, "time": None,
                                                            "depth": 12.25}}
    text = format_readout(1.0, hits=[hit])
    assert text.endswith("D: 1.5 · trace 7 · 12.3 m")
    assert "ms" not in text


def test_a_section_running_against_the_profile_is_not_mirrored(make):
    # placement zero at the end, direction -1: trace 1 lands at chainage 100
    provider, _store, pid = make({"zero": "datum", "datum": 500.0,
                                  "placement": {"zero": 100.0, "direction": -1}})
    layer = provider.layers(pid)[0]
    assert np.all(np.diff(layer.traces.section.x) > 0)
    assert provider.identify(pid, 100.0, 495.0)[0]["trace"]["number"] == 1
    assert provider.identify(pid, 0.0, 495.0)[0]["trace"]["number"] == 11


def test_a_reversed_snapshot_mirrors_the_traces(make):
    provider, _store, pid = make({"zero": "ground"})
    forward = provider.snapshot(pid).layers[0].traces
    back = provider.snapshot(pid, reverse=True).layers[0].traces
    assert np.all(np.diff(back.section.x) > 0)
    assert np.allclose(back.section.x, 100.0 - forward.section.x[::-1])
    assert np.allclose(back.z_top, forward.z_top[::-1])
    assert back.section.numbers[0] == 11
    assert provider.layers(pid)[0].traces.section.numbers[0] == 1      # the provider's stays


def test_a_model_and_a_section_share_a_profile(tmp_path):
    store = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p = profile_from_polyline("P1", "EPSG:25832", np.array([[0.0, 0.0], [100.0, 0.0]]))
    store.save_profile(p)
    model = tmp_path / "f001_res.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", model)
    _add(store, p.id, "", model, {"z_kind": "elevation"}, did="m1", kind="ert_model",
         reader="r2_res_dat")
    before = SectionDataProvider(store)
    (alone,) = before.layers(p.id)
    surface = before.surface(p.id)
    ties = before.ties(p.id)
    _add(store, p.id, "", _segy(tmp_path), {"position": "spacing", "spacing": 10.0,
                                            "velocity": 2000.0, "zero": "ground"})
    provider = SectionDataProvider(store)
    model_layer, section = provider.layers(p.id)
    assert model_layer.mesh.bounds() == pytest.approx(alone.mesh.bounds())
    after = provider.surface(p.id)
    assert after.kind == surface.kind == "model"
    assert np.allclose(after.line[0], surface.line[0]) and np.allclose(after.line[1], surface.line[1])
    assert provider.ties(p.id) == ties
    assert section.error is None
    assert np.allclose(section.traces.z_top, np.interp(section.traces.section.x, *after.line))
    assert provider.station_method(p.id) == "ert"
    provider.electrodes(p.id)                                          # nothing raises
    provider.placement_note(p.id)
    snap = provider.snapshot(p.id)
    assert snap.layers[1].traces is not None


def test_a_profile_with_only_a_section_has_geophone_words(make):
    provider, store, pid = make({})
    # the store's stations are ERT ones (profile_from_stations); without them the kinds decide
    from groundwork_geophysics.core.dataset_types import method_of
    assert method_of([d.kind for d in store.datasets(pid)]) == "refl"
    assert provider.electrodes(pid) is not None


def test_velocity_change_moves_the_picture_without_a_new_dataset(make):
    provider, store, pid = make({"zero": "datum", "datum": 500.0})
    assert layer_bounds(provider.layers(pid)[0])[2] == pytest.approx(500.0 - 49.0)
    d = store.datasets(pid)[0]
    store.save_dataset(replace(d, reader_options={**d.reader_options, "velocity": 4000.0}))
    provider.notify_changed()
    assert [x.id for x in store.datasets(pid)] == [d.id]
    assert layer_bounds(provider.layers(pid)[0])[2] == pytest.approx(500.0 - 98.0)


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


@pytest.mark.parametrize("change, zmin", [({"velocity": 4000.0}, 500.0 - 98.0),
                                          ({"zero": "datum", "datum": 300.0}, 300.0 - 49.0)])
def test_hanging_a_section_again_does_not_read_the_file(make, file_reads, change, zmin):
    provider, store, pid = make({"zero": "ground"} if "datum" in change
                                else {"zero": "datum", "datum": 500.0})
    before = provider.layers(pid)[0].traces.section.amplitudes
    assert file_reads["n"] == 1
    _change(provider, store, pid, **change)
    layer = provider.layers(pid)[0]
    assert layer_bounds(layer)[2] == pytest.approx(zmin)
    assert file_reads["n"] == 1 and layer.traces.section.amplitudes is before
    # a new provider (the project opened again) takes the remembered read from disk
    fresh = SectionDataProvider(store)
    assert layer_bounds(fresh.layers(pid)[0])[2] == pytest.approx(zmin)
    assert file_reads["n"] == 1


def test_a_new_trace_spacing_reads_the_file_again(make, file_reads):
    provider, store, pid = make({"zero": "datum", "datum": 500.0})
    provider.layers(pid)
    _change(provider, store, pid, spacing=5.0)
    assert layer_bounds(provider.layers(pid)[0])[1] == pytest.approx(50.0)
    assert file_reads["n"] == 2


FALLING = (700.0, 650.0, 600.0)          # station heights at 0, 50 and 100 m


def _on_ground(replacement_velocity, **options):
    return {"zero": "datum_ground", "datum": 700.0, "velocity": 2000.0,
            "replacement_velocity": replacement_velocity, **options}


def test_corrected_with_the_same_velocity_the_section_stays_at_the_datum(make):
    provider, _store, pid = make(_on_ground(2000.0), heights=FALLING)
    (layer,) = provider.layers(pid)
    assert layer.error is None
    assert np.allclose(layer.traces.z_top, 700.0, atol=1e-9)


def test_corrected_to_the_ground_the_ground_time_lies_on_the_ground(make):
    from groundwork_geophysics.core.trace_section import Velocity, depth_at, ground_time
    provider, _store, pid = make(_on_ground(4000.0), heights=FALLING)
    (layer,) = provider.layers(pid)
    assert layer.error is None
    placed = layer.traces
    ground = np.interp(placed.section.x, *provider.topography(pid))
    assert ground[0] == pytest.approx(700.0) and ground[-1] == pytest.approx(600.0)
    t = ground_time(700.0, ground, 4000.0)
    below = depth_at(placed.section, Velocity(2000.0), t)
    assert np.abs(placed.z_top - below - ground).max() < 0.01
    assert placed.z_top[-1] == pytest.approx(650.0)         # 100 m of 4000 m/s is 50 m of 2000


@pytest.mark.parametrize("rv", [None, 0.0, -100.0, "x"])
def test_corrected_without_a_replacement_velocity_says_so(make, rv):
    provider, _store, pid = make(_on_ground(rv), heights=FALLING)
    (layer,) = provider.layers(pid)
    assert layer.traces is None
    assert "The replacement velocity must be greater than 0 m/s. Set it in Dataset Info." in layer.error


def test_corrected_on_a_profile_without_heights_says_so(make):
    provider, _store, pid = make(_on_ground(2000.0), heights=False)
    (layer,) = provider.layers(pid)
    assert layer.traces is None
    assert "This section is corrected to the ground, and the profile has no heights yet." in layer.error


def test_corrected_without_a_datum_says_so(make):
    provider, _store, pid = make(_on_ground(2000.0, datum=None), heights=FALLING)
    assert "height of time zero" in provider.layers(pid)[0].error


LEVEL = (600.0, 600.0, 600.0)            # the ground 100 m below the datum of 700 m


def test_corrected_to_the_ground_the_samples_above_it_are_not_earth(make):
    provider, _store, pid = make(_on_ground(6000.0), heights=LEVEL)
    placed = provider.layers(pid)[0].traces
    # ground time 2 * 100 / 6000 = 33.3 ms: from the 34th sample (index 34) on, the earth
    assert placed.live_from.tolist() == [34] * 11
    assert placed.z_top[0] - placed.depths[34] <= 600.0 < placed.z_top[0] - placed.depths[33]
    back = provider.snapshot(pid, reverse=True).layers[0].traces
    assert back.live_from.tolist() == [34] * 11


def test_a_section_at_a_datum_has_no_ground_line(make):
    provider, _store, pid = make({"zero": "datum", "datum": 700.0}, heights=LEVEL)
    assert provider.layers(pid)[0].traces.live_from is None


def _picture(layer):
    """``layer`` painted through ``paint_layers`` on red: s -10 .. 110 m and z 640 .. 580 m at
    2 px per metre (240 x 120)."""
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtGui import QColor, QImage, QPainter, QTransform

    from groundwork_geophysics.section import display_render
    from groundwork_geophysics.section.profile_source import paint_layers
    display_render.clear_cache()
    img = QImage(240, 120, QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 0, 0))
    painter = QPainter(img)
    try:
        paint_layers(painter, [display_render.build_drawing(layer, None)],
                     QTransform(2.0, 0.0, 0.0, -2.0, 20.0, 1280.0),
                     QgsRenderContext.fromQPainter(painter))
    finally:
        painter.end()
    display_render.clear_cache()
    raw = np.frombuffer(img.constBits().asstring(img.sizeInBytes()), np.uint32)
    return raw.reshape(120, img.bytesPerLine() // 4)[:, :240].copy()


def test_above_the_ground_line_the_picture_is_transparent(make, qgis_app):
    from groundwork_geophysics.core.trace_section import DisplayGain
    provider, _store, pid = make(_on_ground(6000.0), heights=LEVEL)
    layer = provider.snapshot(pid).layers[0]
    px = _picture(layer)
    red = 0xFFFF0000
    # z 630 .. 605 m (rows 20 .. 70) above the ground: red shows through; z 598 .. 586 m
    # (rows 84 .. 108) just below it: the section
    assert (px[20:70, 30:210] == red).all()
    assert (px[84:108, 30:210] != red).all()
    painted = replace(layer, style=replace(layer.style, gain=DisplayGain(show_muted=True)))
    assert (_picture(painted)[20:108, 30:210] != red).all()


def test_a_new_ground_line_is_a_new_mute(make, qgis_app):
    from groundwork_geophysics.section import display_render
    provider, store, pid = make(_on_ground(6000.0), heights=LEVEL)
    display_render.clear_cache()
    first = provider.snapshot(pid).layers[0]
    display_render.build_drawing(first, None)
    _change(provider, store, pid, replacement_velocity=4000.0)    # ground time 50 ms: all of it
    second = provider.snapshot(pid).layers[0]
    display_render.build_drawing(second, None)
    entry = display_render._trace_entry(second)
    display_render.clear_cache()
    assert second.traces.live_from.tolist() == [50] * 11 and entry.mute.all()


def test_a_new_replacement_velocity_is_a_new_level_file(make, tmp_path):
    from groundwork_geophysics.section.display_render import _level_path
    provider, store, pid = make(_on_ground(6000.0), heights=LEVEL)
    before = _level_path(provider.layers(pid)[0])
    _change(provider, store, pid, replacement_velocity=5000.0)
    after = _level_path(provider.layers(pid)[0])
    assert before is not None and after is not None and before != after


def test_a_depth_section_is_not_corrected_to_the_ground(make):
    provider, _store, pid = make(_on_ground(2000.0, velocity=None, domain="depth", sample_step=2.0),
                                 heights=FALLING)
    assert "cannot be corrected to the ground" in provider.layers(pid)[0].error


def test_a_new_replacement_velocity_does_not_read_the_file_again(make, file_reads):
    provider, store, pid = make(_on_ground(2000.0), heights=FALLING)
    before = provider.layers(pid)[0].traces
    assert file_reads["n"] == 1
    _change(provider, store, pid, replacement_velocity=4000.0)
    after = provider.layers(pid)[0].traces
    assert after.z_top[-1] == pytest.approx(650.0) and before.z_top[-1] == pytest.approx(700.0)
    assert file_reads["n"] == 1 and after.section.amplitudes is before.section.amplitudes


def test_provider_keys_are_not_passed_to_the_reader():
    options = read_options({"position": "spacing", "spacing": 1.0, "velocity": 2000.0,
                            "velocity_table": [[0, 1500]], "velocity_kind": "average",
                            "zero": "datum", "datum": 3.0, "replacement_velocity": 3000.0})
    assert options == {"position": "spacing", "spacing": 1.0}


def test_map_and_table_sections_are_map_datasets():
    def d(options):
        return Dataset("x", "p", "", "refl_section", "a.sgy", 0.0, "", "segy", options, {})
    assert is_map_dataset(d({"position": "map"})) and is_map_dataset(d({"position": "table"}))
    assert not is_map_dataset(d({"position": "spacing"}))


def test_failed_and_trace_layers_have_bounds_or_none(make):
    provider, _store, pid = make({"velocity": None})
    assert layer_bounds(provider.layers(pid)[0]) is None


def test_trace_layer_style_defaults():
    style = LayerStyle()
    assert style.clip_percent == 98.0 and not style.gain.active()


def test_a_section_draws_nothing_yet_but_counts_for_the_extent(make, qgis_app):
    from groundwork_geophysics.section.display_render import build_drawing
    from groundwork_geophysics.section.profile_source import WorkbenchProfileGenerator
    provider, _store, pid = make({"zero": "datum", "datum": 500.0})
    snap = provider.snapshot(pid)
    drawing = build_drawing(snap.layers[0], snap.topo)
    assert not drawing.groups and drawing.field is None and not drawing.markers

    class Owner:
        last_results = None

    gen = WorkbenchProfileGenerator(snap, Owner())
    assert gen.generateProfile()
    results = gen.takeResults()
    assert results._s == pytest.approx((0.0, 100.0))
    assert results._z[0] == pytest.approx(451.0) and results._z[1] >= 500.0
    from groundwork_geophysics.plates.build import snapshot_extent
    assert snapshot_extent(snap, 100.0)[2] == pytest.approx(451.0)
    from groundwork_geophysics.section.picture import joint_extent
    assert joint_extent(snap.layers, snap.topo)[:3] == pytest.approx((0.0, 100.0, 451.0))


def test_zoom_full_counts_a_section(qgis_app, make, make_dock):
    from groundwork_geophysics.section.view_extent import data_extent
    _provider, store, pid = make({"zero": "datum", "datum": 500.0})
    dock = make_dock(store)
    dock.open_profile(pid)
    assert data_extent(dock)[2] == pytest.approx(451.0)


def test_drawing_on_a_profile_with_only_a_section(qgis_app, make, make_dock):
    from qgis.core import QgsProject

    from groundwork_geophysics.core.interpretation import InterpFeature
    _provider, store, pid = make({"zero": "datum", "datum": 500.0})
    dock = make_dock(store)
    dock.open_profile(pid)
    ctl = dock.interp
    ctl.form_factory = lambda feature, s, letters, existing=(): InterpFeature(
        feature.id, feature.version_id, type="anomaly", name="Reflector")
    ctl._finished("polygon", [(20.0, 490.0), (40.0, 490.0), (40.0, 480.0), (20.0, 480.0)])
    [piece] = store.pieces(store.current_version().id)
    assert piece.kind == "polygon" and piece.profile_id == pid
    assert piece.based_on_dataset == "s1"
    snap = dock.provider.snapshot(pid)
    assert [p.id for p in snap.interpretation] == [piece.id]
    QgsProject.instance().removeAllMapLayers()
