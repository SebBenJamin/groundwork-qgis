"""The open attribute form for interpretation features."""


def test_form_accepts_free_text_type_and_warns_duplicate_letter(qgis_app):
    from geophysics_workbench.core.interpretation import InterpFeature
    from geophysics_workbench.ui.interp_form import InterpForm

    form = InterpForm(None, InterpFeature("f", "v"), ["anomaly", "fault"], {"A"})
    assert form.confidence.currentText() == "probable"
    form.type_combo.setEditText("client's suspected pipe")
    form.letter.setText("A")
    assert form.letter_warning.isVisibleTo(form)
    form.letter.setText("B")
    assert not form.letter_warning.isVisibleTo(form)
    f = form.feature()
    assert (f.type, f.letter, f.confidence) == ("client's suspected pipe", "B", "probable")
