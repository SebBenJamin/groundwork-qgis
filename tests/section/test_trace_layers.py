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
    given)."""
    def factory(options, heights=True, amplitudes=AMPLITUDES):
        folder = tmp_path / f"store{len(list(tmp_path.iterdir()))}"
        folder.mkdir()
        store = ProjectStore.create(folder / "p.gpkg", "EPSG:25832")
        if heights:
            p, s = profile_from_stations("P1", "EPSG:25832",
                                         np.array([[0, 0, 500], [50, 0, 505], [100, 0, 510.0]]))
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


def test_provider_keys_are_not_passed_to_the_reader():
    options = read_options({"position": "spacing", "spacing": 1.0, "velocity": 2000.0,
                            "velocity_table": [[0, 1500]], "velocity_kind": "average",
                            "zero": "datum", "datum": 3.0})
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
