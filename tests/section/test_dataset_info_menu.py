"""The layer row menu offers Dataset info…."""


def test_layer_menu_has_dataset_info(qgis_app, store_with_model, make_dock):
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    ds_id = st.datasets(p.id)[0].id
    texts = [a.text() for a in dock.layer_list.row_menu(ds_id).actions()]
    assert "Dataset info…" in texts


# -- a reflection section: its vertical settings are edited here --------------------------------
def _trace_store(tmp_path, velocity=1500.0):
    """(store, profile, provider): a 100 m profile with heights and an 11 x 50 section (1 ms,
    traces 10 m apart) hung on the ground with ``velocity``."""
    import numpy as np

    from groundwork_geophysics.core.model import Dataset, file_fingerprint, profile_from_stations
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    from segy_files import write_segy
    a = np.sin(np.arange(11 * 50, dtype=np.float32) / 3.0).reshape(11, 50)
    path = write_segy(tmp_path / "line.sgy", a, dt_us=1000, fmt=5, text="C 1 CLIENT TEST")
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p, s = profile_from_stations("P1", "EPSG:25832",
                                 np.array([[0, 0, 500.0], [50, 0, 505.0], [100, 0, 510.0]]))
    st.save_profile(p)
    st.save_station_set(s)
    from groundwork_geophysics.readers.segy import SegyReader
    result = SegyReader().read(path, position="spacing", spacing=10.0)
    mt, sha = file_fingerprint(path)
    st.save_dataset(Dataset("s1", p.id, s.id, "refl_section", str(path), mt, sha, "segy",
                            {"position": "spacing", "spacing": 10.0, "velocity": velocity,
                             "zero": "ground"}, result.provenance, name="Line 1"))
    return st, p, SectionDataProvider(st)


def _bottom(provider, pid) -> float:
    from groundwork_geophysics.section.data import layer_bounds
    return layer_bounds(provider.layers(pid)[0])[2]


def _draw_line(st, pid):
    from groundwork_geophysics.core.interpretation import InterpFeature, InterpPiece, new_id
    st.ensure_interpretation()
    version = st.current_version().id
    feature = InterpFeature(new_id(), version, name="K1")
    st.save_feature(feature)
    st.save_piece(InterpPiece(new_id(), version, feature.id, pid, "line",
                              [(10.0, 480.0), (60.0, 470.0)]))


def test_a_section_row_opens_dataset_info(qgis_app, tmp_path, make_dock):
    import pytest
    pytest.importorskip("segyio")
    st, p, _provider = _trace_store(tmp_path)
    dock = make_dock(st)
    dock.open_profile(p.id)
    texts = [a.text() for a in dock.layer_list.row_menu("s1").actions()]
    assert "Dataset info…" in texts


def test_dataset_info_of_a_section_moves_it_with_a_new_velocity(qgis_app, tmp_path):
    import pytest
    pytest.importorskip("segyio")
    from groundwork_geophysics.ui.dataset_info_dialog import DatasetInfoDialog
    st, p, provider = _trace_store(tmp_path)
    before = _bottom(provider, p.id)
    dlg = DatasetInfoDialog(st, "s1", provider=provider)
    assert dlg.segy_box is not None and dlg.segy_box.vertical_only
    assert "11 traces × 50 samples, 1 ms" in dlg.traces_label.text()
    dlg.segy_box.velocity_edit.setText("1600")
    dlg.accept()
    got = st.datasets(p.id)[0]
    assert got.reader_options["velocity"] == 1600.0
    assert got.reader_options["position"] == "spacing" and got.reader_options["spacing"] == 10.0
    assert _bottom(provider, p.id) < before            # deeper with the faster velocity


def test_unchanged_vertical_settings_keep_the_stored_options(qgis_app, tmp_path):
    import pytest
    pytest.importorskip("segyio")
    from groundwork_geophysics.ui.dataset_info_dialog import DatasetInfoDialog
    st, p, provider = _trace_store(tmp_path)
    stored = dict(st.datasets(p.id)[0].reader_options)
    dlg = DatasetInfoDialog(st, "s1", provider=provider)
    dlg.fields["note"].setPlainText("stack")
    dlg.accept()
    got = st.datasets(p.id)[0]
    assert got.reader_options == stored and got.provenance["info"] == {"note": "stack"}


def test_moving_a_section_under_drawings_asks_first(qgis_app, tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("segyio")
    from qgis.PyQt.QtWidgets import QMessageBox

    from groundwork_geophysics.ui.dataset_info_dialog import MOVE_TEXT, DatasetInfoDialog
    st, p, provider = _trace_store(tmp_path)
    _draw_line(st, p.id)
    asked = []

    def answer(parent, title, text, buttons, default):
        asked.append((text, default))
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", staticmethod(answer))
    dlg = DatasetInfoDialog(st, "s1", provider=provider)
    dlg.segy_box.velocity_edit.setText("1600")
    dlg.accept()
    assert asked == [(MOVE_TEXT, QMessageBox.StandardButton.No)]
    assert MOVE_TEXT == ("The section will move. Drawings on this profile stay at their "
                         "heights. Change it?")
    assert st.datasets(p.id)[0].reader_options["velocity"] == 1500.0     # No: unchanged
    asked.clear()
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a: QMessageBox.StandardButton.Yes))
    dlg.accept()
    assert st.datasets(p.id)[0].reader_options["velocity"] == 1600.0


def test_no_question_without_drawings_or_without_a_move(qgis_app, tmp_path):
    import pytest
    pytest.importorskip("segyio")
    from groundwork_geophysics.ui.dataset_info_dialog import DatasetInfoDialog
    st, p, provider = _trace_store(tmp_path)
    dlg = DatasetInfoDialog(st, "s1", provider=provider)       # no drawings: no question
    dlg.segy_box.velocity_edit.setText("1600")
    dlg.accept()                                               # a box would fail the test
    _draw_line(st, p.id)
    dlg = DatasetInfoDialog(st, "s1", provider=provider)       # drawings, nothing moves
    dlg.fields["note"].setPlainText("x")
    dlg.accept()
    assert st.datasets(p.id)[0].reader_options["velocity"] == 1600.0


def test_without_the_file_the_stored_values_are_shown_and_edited(qgis_app, tmp_path):
    import pytest
    pytest.importorskip("segyio")
    from groundwork_geophysics.ui.dataset_info_dialog import DatasetInfoDialog
    st, p, provider = _trace_store(tmp_path)
    (tmp_path / "line.sgy").unlink()
    dlg = DatasetInfoDialog(st, "s1", provider=provider)
    assert dlg.segy_box.velocity_edit.text() == "1500"
    assert dlg.text_button.isEnabled()                 # the text kept with the dataset
    dlg.segy_box.velocity_edit.setText("1700")
    dlg.accept()
    assert st.datasets(p.id)[0].reader_options["velocity"] == 1700.0


def test_the_text_header_button_says_why_it_is_off(qgis_app, tmp_path):
    import pytest
    pytest.importorskip("segyio")
    from groundwork_geophysics.ui.dataset_info_dialog import DatasetInfoDialog
    st, p, provider = _trace_store(tmp_path)
    d = st.datasets(p.id)[0]
    d.provenance.pop("text")
    st.save_dataset(d)
    (tmp_path / "line.sgy").unlink()
    dlg = DatasetInfoDialog(st, "s1", provider=provider)
    assert not dlg.text_button.isEnabled() and "line.sgy" in dlg.text_button.toolTip()


def test_a_model_has_no_section_group(qgis_app, store_with_model):
    from groundwork_geophysics.ui.dataset_info_dialog import DatasetInfoDialog
    st, p, _ = store_with_model
    dlg = DatasetInfoDialog(st, st.datasets(p.id)[0].id)
    assert dlg.segy_box is None


def test_a_section_speaks_of_processing_and_trace_spacing(qgis_app, tmp_path):
    import pytest
    pytest.importorskip("segyio")
    from qgis.PyQt.QtWidgets import QFormLayout, QLabel

    from groundwork_geophysics.ui.dataset_info_dialog import DatasetInfoDialog
    st, p, provider = _trace_store(tmp_path)
    dlg = DatasetInfoDialog(st, "s1", provider=provider)
    dlg.show()
    form = dlg.findChild(QFormLayout)

    def label(key):
        return form.labelForField(dlg.fields[key])
    assert label("software").text() == "Processing software and settings"
    assert dlg.fields["software"].placeholderText() == "e.g. migrated stack, contractor, year"
    assert label("spacing").text() == "Trace spacing"
    assert dlg.fields["spacing"].placeholderText() == "e.g. 2 m"
    assert dlg.fields["array"].isHidden() and label("array").isHidden()
    shown = [w.text() for w in dlg.findChildren(QLabel) if not w.isHidden()]
    assert "Inversion software and settings" not in shown and "Array" not in shown
    dlg.fields["software"].setText("migrated stack")
    dlg.fields["spacing"].setText("2 m")
    dlg.accept()
    from groundwork_geophysics.core.dataset_info import dataset_info
    assert dataset_info(st.datasets(p.id)[0]) == {"software": "migrated stack", "spacing": "2 m"}
    dlg.close()


def test_a_model_keeps_its_inversion_wording(qgis_app, store_with_model):
    from qgis.PyQt.QtWidgets import QFormLayout

    from groundwork_geophysics.ui.dataset_info_dialog import DatasetInfoDialog
    st, p, _ = store_with_model
    dlg = DatasetInfoDialog(st, st.datasets(p.id)[0].id)
    form = dlg.findChild(QFormLayout)
    assert form.labelForField(dlg.fields["software"]).text() == "Inversion software and settings"
    assert form.labelForField(dlg.fields["spacing"]).text() == "Electrode / geophone spacing"
    assert not dlg.fields["array"].isHidden()
