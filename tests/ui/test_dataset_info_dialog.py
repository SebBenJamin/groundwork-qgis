"""Dataset info…: method, array, spacing, … entered once per dataset; used for provenance."""


def test_dialog_saves_and_shows_detected_rms(qgis_app, store_with_model):
    from groundwork_geophysics.core.dataset_info import dataset_info
    from groundwork_geophysics.ui.dataset_info_dialog import DatasetInfoDialog
    st, p, _ = store_with_model
    d = st.datasets(p.id)[0]
    d.provenance["rms_percent"] = 4.2
    st.save_dataset(d)
    dlg = DatasetInfoDialog(st, d.id)
    assert "4.2" in dlg.detected.text()
    dlg.fields["array"].setText("Wenner")
    dlg.fields["note"].setPlainText("re-inverted")
    dlg.accept()
    got = next(x for x in st.datasets(p.id) if x.id == d.id)
    assert dataset_info(got) == {"array": "Wenner", "note": "re-inverted"}
    assert got.provenance["rms_percent"] == 4.2
