"""Adding measured data and inversion misfit through the Add dialog."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "readers"))


def _files(tmp_path, response=True):
    from test_bert_data import DATA
    data = tmp_path / "line.data"
    data.write_text(DATA.replace("\n0 10.0\n1 10.1\n2 10.2\n3 10.3\n4 10.4\n5 10.5",
                                 "\n0 100\n10 100.4\n20 100.8\n30 101.2\n40 101.6\n50 102"))
    if response:
        (tmp_path / "response.vector").write_text(
            "\n".join(str(v) for v in (110, 121, 108, 143, 140)))
    return data


def test_dialog_pairs_the_response_and_saves_a_misfit_dataset(qgis_app, fake_iface,
                                                               store_with_model, tmp_path,
                                                               warnings_shown):
    from geophysics_workbench.ui.add_data_dialog import AddDataDialog
    st, p, _ = store_with_model
    data = _files(tmp_path)
    dlg = AddDataDialog(fake_iface, st, p.id)
    dlg.set_file(data)
    assert dlg.format_combo.currentData() == "bert_data"
    assert dlg.response_edit.isVisibleTo(dlg)
    assert Path(dlg.response_edit.text()).name == "response.vector"
    text = dlg.summary_label.text()
    assert "5 readings" in text and "RMS" in text
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    ds = dlg.dataset
    assert ds is not None and ds.kind == "ert_misfit" and ds.quantity == "misfit"
    assert ds.reader_options["response"] == "response.vector"      # next to the data file


def test_measured_only_dataset(qgis_app, fake_iface, store_with_model, tmp_path,
                               warnings_shown):
    from geophysics_workbench.ui.add_data_dialog import AddDataDialog
    st, p, _ = store_with_model
    dlg = AddDataDialog(fake_iface, st, p.id)
    dlg.set_file(_files(tmp_path, response=False))
    assert dlg.response_edit.text() == ""
    assert "measured" in dlg.summary_label.text()
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    assert dlg.dataset.kind == "ert_measured" and dlg.dataset.quantity == "resistivity"


def test_model_files_hide_the_response_row(qgis_app, fake_iface, store_with_model):
    from geophysics_workbench.ui.add_data_dialog import AddDataDialog
    st, p, src = store_with_model
    dlg = AddDataDialog(fake_iface, st, p.id)
    dlg.set_file(src)
    assert not dlg.response_edit.isVisibleTo(dlg)


def test_response_found_when_its_name_differs_from_the_data_stem(tmp_path):
    # Gülpe demo: T3_measured.data next to T3_response.vector
    from geophysics_workbench.ui.add_data_dialog import guess_response
    data = tmp_path / "T3_measured.data"
    data.write_text("x")
    (tmp_path / "T3_response.vector").write_text("1")
    (tmp_path / "dcinv.result.vtk").write_text("x")
    assert Path(guess_response(data)).name == "T3_response.vector"


def test_two_unrelated_responses_are_not_guessed(tmp_path):
    from geophysics_workbench.ui.add_data_dialog import guess_response
    data = tmp_path / "line.data"
    data.write_text("x")
    (tmp_path / "a_response.vector").write_text("1")
    (tmp_path / "b_response.vector").write_text("1")
    assert guess_response(data) == ""
