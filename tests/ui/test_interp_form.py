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


def test_form_picks_existing_feature(qgis_app):
    from geophysics_workbench.core.interpretation import InterpFeature
    from geophysics_workbench.ui.interp_form import InterpForm

    a = InterpFeature("fa", "v", type="anomaly", letter="A", confidence="certain", note="wet")
    form = InterpForm(None, InterpFeature("new", "v"), ["anomaly"], {"A"}, existing=[a])
    assert [form.feature_combo.itemText(i) for i in range(form.feature_combo.count())] == [
        "New feature", "A · anomaly"]
    form.feature_combo.setCurrentIndex(1)
    assert form.type_combo.currentText() == "anomaly" and form.letter.text() == "A"
    assert not form.letter_warning.isVisibleTo(form)          # its own letter
    f = form.feature()
    assert (f.id, f.confidence, f.note) == ("fa", "certain", "wet")
    form.feature_combo.setCurrentIndex(0)
    assert form.feature().id == "new" and form.letter.text() == ""


def test_form_without_existing_has_no_picker(qgis_app):
    from geophysics_workbench.core.interpretation import InterpFeature
    from geophysics_workbench.ui.interp_form import InterpForm

    form = InterpForm(None, InterpFeature("f", "v"), [], set())
    assert not form.feature_combo.isVisibleTo(form)


def test_existing_features_are_identifiable(qgis_app):
    from geophysics_workbench.core.interpretation import InterpFeature
    from geophysics_workbench.ui.interp_form import InterpForm

    a = InterpFeature("fa", "v", type="sand", note="clay loam")
    form = InterpForm(None, InterpFeature("new", "v"), [], set(), existing=[a],
                      details={"fa": "Transect 3 (here), Transect 2 · 2 pieces"})
    assert form.feature_combo.itemText(1) == "sand  —  Transect 3 (here), Transect 2 · 2 pieces"
    assert not form.join_hint.isVisibleTo(form)
    form.feature_combo.setCurrentIndex(1)
    hint = form.join_hint.text()
    assert form.join_hint.isVisibleTo(form)
    assert "sand" in hint and "clay loam" in hint and "all its pieces" in hint
