"""Per-layer display settings: mode, contours and coverage, edited in one Display dialog."""
from dataclasses import replace

import numpy as np


def _layer(store_with_model, coverage=None):
    from groundwork_geophysics.section.data import SectionDataProvider
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    layer = prov.layers(p.id)[0]
    if coverage is not None:
        layer.mesh.coverage = coverage(layer.mesh)
    return prov, layer


def test_style_defaults_and_copy():
    from groundwork_geophysics.section.data import DISPLAY_MODES, LayerStyle, _copy_style
    s = LayerStyle()
    assert (s.mode, s.contour_step, s.grid_cell, s.fade_coverage, s.coverage_threshold,
            s.fade_mode) == ("cells", None, None, False, None, "fade")
    assert DISPLAY_MODES == ("cells", "smooth", "contours", "smooth+contours")
    c = _copy_style(replace(s, mode="smooth", contour_step=0.5))
    assert (c.mode, c.contour_step) == ("smooth", 0.5)


def test_dialog_round_trip(qgis_app, store_with_model):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    _prov, layer = _layer(store_with_model)
    dlg = DisplayDialog(None, layer)
    dlg.mode_combo.setCurrentIndex(dlg.mode_combo.findData("smooth+contours"))
    dlg.auto_step.setChecked(False)
    dlg.step_spin.setValue(0.5)
    got = []
    dlg.applied_style.connect(got.append)
    assert dlg.apply()
    s = got[0]
    assert (s.mode, s.contour_step) == ("smooth+contours", 0.5)
    assert s.scale is not None


def test_coverage_group_disabled_without_coverage(qgis_app, store_with_model):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    _prov, layer = _layer(store_with_model)
    assert not DisplayDialog(None, layer).coverage_group.isEnabled()
    _prov, layer = _layer(store_with_model, coverage=lambda m: np.linspace(-3, 0, len(m.values)))
    dlg = DisplayDialog(None, layer)
    assert dlg.coverage_group.isEnabled()
    dlg.fade_check.setChecked(True)
    dlg.blank_radio.setChecked(True)
    s = dlg.style()
    assert s.fade_coverage and s.fade_mode == "blank" and s.coverage_threshold is not None


def test_row_menu_has_display(qgis_app, store_with_model):
    from groundwork_geophysics.section.layer_list import LayerList
    prov, layer = _layer(store_with_model)
    ll = LayerList()
    try:
        ll.set_layers(prov, [layer])
        texts = [a.text() for a in ll.row_menu(layer.dataset.id).actions()]
        assert texts[0] == "Display…" and "Remove from profile…" in texts
        ll.set_display(layer.dataset.id, mode="contours")
        assert prov.style(layer.dataset.id).mode == "contours"
    finally:
        ll.deleteLater()


# -- interpolation of the smooth field ---------------------------------------------------------
def _with(layer, **style):
    return replace(layer, style=replace(layer.style, **style))


def test_interpolation_round_trips_through_the_dialog(qgis_app, store_with_model):
    from groundwork_geophysics.core.interpolators import Interpolation
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    _prov, layer = _layer(store_with_model)
    chosen = Interpolation(method="kriging", variogram="exponential", range_m=8.0, sill=0.5,
                           nugget=0.01, neighbours=20, anisotropy=4.0)
    dlg = DisplayDialog(None, _with(layer, mode="smooth", interpolation=chosen))
    assert dlg.method_combo.currentData() == "kriging"
    assert dlg.style().interpolation == chosen
    idw = Interpolation(method="idw", power=3.0, neighbours=8)
    dlg = DisplayDialog(None, _with(layer, mode="smooth", interpolation=idw))
    assert dlg.style().interpolation == idw
    spline = Interpolation(method="spline", kernel="cubic", smoothing=0.5)
    dlg = DisplayDialog(None, _with(layer, mode="smooth", interpolation=spline))
    assert dlg.style().interpolation == spline


def test_auto_fields_read_as_none(qgis_app, store_with_model):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    _prov, layer = _layer(store_with_model)
    dlg = DisplayDialog(None, _with(layer, mode="smooth"))
    dlg.method_combo.setCurrentIndex(dlg.method_combo.findData("kriging"))
    got = dlg.style().interpolation
    assert got.method == "kriging"
    assert (got.range_m, got.sill, got.nugget, got.anisotropy, got.neighbours) == (
        None, None, None, None, None)


def test_fit_now_shows_the_fitted_variogram(qgis_app, store_with_model):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    _prov, layer = _layer(store_with_model)
    dlg = DisplayDialog(None, _with(layer, mode="smooth"))
    dlg.method_combo.setCurrentIndex(dlg.method_combo.findData("kriging"))
    dlg.fit_button.click()
    text = dlg.fit_label.text().lower()
    assert "range" in text and "sill" in text and any(c.isdigit() for c in text)


def test_interpolation_is_off_where_no_smooth_field_is_drawn(qgis_app, store_with_model):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    _prov, layer = _layer(store_with_model)
    dlg = DisplayDialog(None, _with(layer, mode="cells"))
    assert not dlg.method_combo.isEnabled() and "smooth" in dlg.method_combo.toolTip().lower()
    dlg.mode_combo.setCurrentIndex(dlg.mode_combo.findData("contours"))
    assert dlg.method_combo.isEnabled()


def test_the_dialog_fits_a_laptop_screen_with_kriging(qgis_app, store_with_model):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    _prov, layer = _layer(store_with_model, coverage=lambda m: np.linspace(-3, 0, len(m.values)))
    dlg = DisplayDialog(None, _with(layer, mode="smooth"))
    dlg.method_combo.setCurrentIndex(dlg.method_combo.findData("kriging"))
    dlg.show()
    qgis_app.processEvents()
    try:
        assert dlg.sizeHint().height() <= 580 and dlg.height() <= 580
        assert dlg.fit_button.isVisibleTo(dlg)              # reachable: the groups scroll
    finally:
        dlg.close()
