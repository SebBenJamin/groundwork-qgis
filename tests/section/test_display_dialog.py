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
