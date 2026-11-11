"""Round 2, F3: Major levels and Minor levels in Display… (contours part)."""
from dataclasses import replace

from tests.section.test_display_dialog import _layer


def _dialog(store_with_model, **style):
    from geophysics_workbench.section.scale_dialog import DisplayDialog
    _prov, layer = _layer(store_with_model)
    layer = replace(layer, style=replace(layer.style, mode="contours", **style))
    return DisplayDialog(None, layer)


def test_fields_prefilled(qgis_app, store_with_model):
    dlg = _dialog(store_with_model, contour_major=(10.0, 100.0), contour_minor=(50.0,))
    assert dlg.major_edit.text() == "10;100" and dlg.minor_edit.text() == "50"
    label = dlg.contours_group.layout().labelForField(dlg.major_edit)
    assert label.text() == "Major levels"
    assert dlg.major_edit.placeholderText() == "e.g. 10;30;100;300"
    assert dlg.minor_edit.placeholderText() == "e.g. 20;50;200"


def test_style_carries_levels(qgis_app, store_with_model):
    dlg = _dialog(store_with_model)
    dlg.major_edit.setText("100; 300")              # inside the model's scale (81-314)
    dlg.minor_edit.setText("200")
    st = dlg.style()
    assert st.contour_major == (100.0, 300.0) and st.contour_minor == (200.0,)


def test_invalid_keeps_dialog_open(qgis_app, store_with_model):
    dlg = _dialog(store_with_model)
    dlg.major_edit.setText("10;x")
    dlg.accept()
    assert dlg.result() != dlg.DialogCode.Accepted
    assert dlg.message.isVisibleTo(dlg) and "“x” is not a number" in dlg.message.text()
    assert dlg.major_edit.text() == "10;x"


def test_spacing_disabled_while_typed(qgis_app, store_with_model):
    dlg = _dialog(store_with_model)
    dlg.auto_step.setChecked(False)
    assert dlg.step_spin.isEnabled() and dlg.auto_step.isEnabled()
    dlg.minor_edit.setText("50")
    assert not dlg.step_spin.isEnabled() and not dlg.auto_step.isEnabled()
    assert dlg.step_spin.toolTip() == "Not used while levels are typed."
    dlg.minor_edit.setText("")
    assert dlg.step_spin.isEnabled() and dlg.auto_step.isEnabled()


def test_group_only_for_contour_modes(qgis_app, store_with_model):
    dlg = _dialog(store_with_model)
    dlg.mode_combo.setCurrentIndex(dlg.mode_combo.findData("cells"))
    assert not dlg.contours_group.isEnabled()
    dlg.mode_combo.setCurrentIndex(dlg.mode_combo.findData("smooth+contours"))
    assert dlg.contours_group.isEnabled()
