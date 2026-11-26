"""Reflection sections on plates: drawn in their frame, with an amplitude key instead of a
numbered colour bar, and their depth conversion in the provenance line."""
import numpy as np
import pytest

pytest.importorskip("segyio")

from segy_files import write_segy  # noqa: E402

#: 11 traces x 50 samples at 1 ms, signed
AMPLITUDES = np.sin(np.arange(11 * 50, dtype=np.float32) / 3.0).reshape(11, 50)


def _add_section(st, p, tmp_path, amplitudes=AMPLITUDES, did="s1", **options):
    from groundwork_geophysics.core.model import Dataset, file_fingerprint
    path = write_segy(tmp_path / f"{did}.sgy", amplitudes, dt_us=1000, fmt=5)
    mt, sha = file_fingerprint(path)
    opts = {"position": "spacing", "spacing": 5.0, "velocity": 1500.0, "zero": "datum",
            "datum": 101.0, **options}
    st.save_dataset(Dataset(did, p.id, "", "refl_section", str(path), mt, sha, "segy", opts,
                            {"n_traces": 11, "n_samples": 50, "step": 0.001},
                            name="Line 1"))


@pytest.fixture
def env(qgis_app, store_with_model):
    from qgis.core import QgsProject

    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.plates.items import register_items, set_context_provider
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.ui.project_actions import use_store
    st, p, _ = store_with_model
    prj = QgsProject.instance()
    prj.clear()
    use_store(st, prj)
    prov = SectionDataProvider(st)
    prov.context_source = lambda profile: ContextItems()
    register_items()
    set_context_provider(prov)
    yield st, p, prov, prj
    from groundwork_geophysics.plates.sources import detach_frame_items, unregister_frame_sources
    detach_frame_items(prj)
    unregister_frame_sources()
    set_context_provider(None)
    prj.removeAllMapLayers()
    prj.clear()


def _plate(st, p, ids, gain=None):
    from groundwork_geophysics.core.plates import FrameLook, FrameSpec, ModelLook, PlateSpec
    models = [ModelLook(i, gain=gain if i.startswith("s") else None) for i in ids]
    return PlateSpec("pl1", "1", "Line", "A3_landscape",
                     [FrameSpec("f0", p.id, FrameLook(models))])


def _bars(layout):
    from groundwork_geophysics.plates.items import ColourBarItem
    bars = [i for i in layout.items() if isinstance(i, ColourBarItem)]
    return [b for b in bars if not b.amplitude], [b for b in bars if b.amplitude]


def test_a_model_and_a_section_get_one_colour_bar_and_one_amplitude_key(env, tmp_path):
    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    _add_section(st, p, tmp_path)
    layout = create_or_update_plate(prj, st, prov, _plate(st, p, ["d1", "s1"]))
    numbered, keys = _bars(layout)
    assert [b.dataset_id for b in numbered] == ["d1"]
    assert [b.dataset_id for b in keys] == ["s1"]
    key = keys[0]
    assert key.title == "Amplitude" and key.end_labels() == ("−", "+")
    text = layout.itemById("wb_provenance_1").text()
    assert "depth from v = 1500 m/s" in text and "Seismic reflection · section" in text


def test_a_plate_of_only_a_section_draws_it_and_has_only_the_key(env, tmp_path):
    from qgis.core import QgsLayoutExporter, QgsLayoutItemElevationProfile

    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    _add_section(st, p, tmp_path)
    layout = create_or_update_plate(prj, st, prov, _plate(st, p, ["s1"]))
    numbered, keys = _bars(layout)
    assert numbered == [] and len(keys) == 1
    frame = layout.itemById("wb_frame_1")
    assert isinstance(frame, QgsLayoutItemElevationProfile)
    assert frame.plot().yMinimum() < 101.0 - 30.0 < frame.plot().yMaximum()   # the section
    image = QgsLayoutExporter(layout).renderPageToImage(0)
    assert not image.isNull()


def test_all_positive_data_read_from_zero(env, tmp_path):
    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    _add_section(st, p, tmp_path, amplitudes=np.abs(AMPLITUDES) + 1.0)
    layout = create_or_update_plate(prj, st, prov, _plate(st, p, ["s1"]))
    assert _bars(layout)[1][0].end_labels() == ("0", "+")


def test_the_key_says_when_a_display_gain_is_on(env, tmp_path):
    from groundwork_geophysics.core.trace_section import DisplayGain
    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    _add_section(st, p, tmp_path)
    flip = DisplayGain(reverse_polarity=True, show_muted=True).to_dict()
    layout = create_or_update_plate(prj, st, prov, _plate(st, p, ["s1"], gain=flip))
    key = _bars(layout)[1][0]
    assert key.shown_title() == "Amplitude" and key.reversed_ramp()
    agc = DisplayGain(agc_window=0.01).to_dict()
    layout = create_or_update_plate(prj, st, prov, _plate(st, p, ["s1"], gain=agc))
    key = _bars(layout)[1][0]
    assert key.shown_title() == "Amplitude (display gain)" and not key.reversed_ramp()


def test_an_amplitude_key_survives_saving_the_project(env, tmp_path):
    import gc

    from groundwork_geophysics.plates.build import create_or_update_plate, find_plate_layout
    from groundwork_geophysics.plates.sources import detach_frame_items
    st, p, prov, prj = env
    _add_section(st, p, tmp_path)
    plate = _plate(st, p, ["d1", "s1"])
    create_or_update_plate(prj, st, prov, plate)
    path = tmp_path / "plates.qgz"
    assert prj.write(str(path))
    detach_frame_items(prj)
    prj.clear()
    assert prj.read(str(path))
    gc.collect()
    numbered, keys = _bars(find_plate_layout(prj, plate))
    assert [b.dataset_id for b in numbered] == ["d1"] and [b.dataset_id for b in keys] == ["s1"]


def test_the_stamp_says_processing_for_a_section_and_inversion_for_a_model():
    from groundwork_geophysics.core.dataset_info import with_info
    from groundwork_geophysics.core.model import Dataset
    from groundwork_geophysics.core.plates import PlateSpec
    from groundwork_geophysics.plates.stamp import stamp_texts
    plate = PlateSpec("pl1", "1", "Line", "A3_landscape", [])
    section = with_info(Dataset("s1", "p1", "", "refl_section", "a.sgy", 0.0, "", "segy",
                                {"velocity": 1500.0}, {}), {"software": "migrated stack"})
    model = with_info(Dataset("d1", "p1", "", "ert_model", "a.dat", 0.0, "", "r2", {}, {}),
                      {"software": "BERT"})
    assert "Processing: migrated stack" in stamp_texts(plate, ["P1"], [section], [], "", "")["survey"]
    assert "Inversion: BERT" in stamp_texts(plate, ["P1"], [model], [], "", "")["survey"]


def test_traces_text_counts_like_the_add_data_summary(tmp_path):
    from groundwork_geophysics.core.dataset_info import traces_text
    from groundwork_geophysics.core.model import Dataset
    from groundwork_geophysics.readers.segy import SegyReader
    from groundwork_geophysics.ui.add_data_dialog import describe_traces
    a = np.zeros((1970, 3), np.float32)
    a[:, 1] = 1.0
    path = write_segy(tmp_path / "big.sgy", a, dt_us=4000, fmt=5)
    result = SegyReader().read(path, position="spacing", spacing=1.0)
    d = Dataset("s1", "p1", "", "refl_section", str(path), 0.0, "", "segy", {}, result.provenance)
    counts = describe_traces(result.traces).split(" · ")[0]
    assert traces_text(d).startswith(counts) and "1" in counts and "970" in counts
