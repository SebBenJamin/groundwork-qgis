"""The open attribute form for interpretation features."""


def test_form_accepts_free_text_type_and_warns_duplicate_name(qgis_app):
    from groundwork_geophysics.core.interpretation import InterpFeature
    from groundwork_geophysics.ui.interp_form import InterpForm

    form = InterpForm(None, InterpFeature("f", "v"), ["anomaly", "fault"], {"A"})
    assert form.confidence.currentText() == "probable"
    form.type_combo.setEditText("client's suspected pipe")
    form.name_edit.setText("A")
    assert form.name_warning.isVisibleTo(form)
    form.name_edit.setText("B")
    assert not form.name_warning.isVisibleTo(form)
    f = form.feature()
    assert (f.type, f.name, f.confidence) == ("client's suspected pipe", "B", "probable")
