"""Per-layer display settings: mode, contours and coverage, edited in one Display dialog."""
from dataclasses import replace

import numpy as np
import pytest


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


# -- reflection sections ---------------------------------------------------------------------
def test_a_trace_layer_shows_only_what_applies(qgis_app, trace_layer):
    from qgis.PyQt.QtWidgets import QGroupBox

    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    dlg = DisplayDialog(None, trace_layer)
    for name in ("display_group", "contours_group", "coverage_group"):
        assert not dlg.findChild(QGroupBox, name).isVisibleTo(dlg), name
    for widget in (dlg.mode_combo, dlg.method_combo, dlg.cell_spin, dlg.fade_check,
                   dlg.log_check, dlg.auto_button):
        assert not widget.isVisibleTo(dlg)
    assert dlg.amplitudes_group.isVisibleTo(dlg) and dlg.ramp_button.isVisibleTo(dlg)
    assert dlg.clip_check.isChecked() and dlg.clip_spin.value() == 98.0
    assert (dlg.clip_spin.minimum(), dlg.clip_spin.maximum(), dlg.clip_spin.decimals()) == (
        0.1, 100.0, 1)
    assert dlg.clip_spin.suffix() == " %"
    assert dlg.max_spin.suffix() == ""          # the file's unit (none), not Ω·m


def test_a_model_has_no_amplitudes_group(qgis_app, store_with_model):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    _prov, layer = _layer(store_with_model)
    dlg = DisplayDialog(None, layer)
    assert dlg.amplitudes_group is None and dlg.clip_check is None
    from qgis.PyQt.QtWidgets import QGroupBox
    assert dlg.findChild(QGroupBox, "contours_group").isVisibleTo(dlg)


def test_the_clip_percent_sets_the_limits(qgis_app, trace_layer):
    from groundwork_geophysics.core.trace_section import color_limits
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    dlg = DisplayDialog(None, trace_layer)
    dlg.clip_spin.setValue(90.0)
    lo, hi = color_limits(trace_layer.traces.section, 90.0)
    assert (dlg.min_spin.value(), dlg.max_spin.value()) == (round(lo, 3), round(hi, 3))
    s = dlg.style()
    assert s.clip_percent == 90.0
    assert (s.scale.vmin, s.scale.vmax) == pytest.approx((lo, hi), abs=1e-3)


def test_a_typed_limit_is_mirrored_and_ends_the_clip(qgis_app, trace_layer):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    dlg = DisplayDialog(None, trace_layer)
    dlg.max_spin.setValue(5.0)
    s = dlg.style()
    assert (s.scale.vmin, s.scale.vmax) == (-5.0, 5.0) and s.clip_percent is None
    assert not dlg.clip_check.isChecked()
    dlg.min_spin.setValue(-2.0)
    assert dlg.max_spin.value() == 2.0
    dlg.clip_check.setChecked(True)                     # clipping again gives the clip's limits
    assert dlg.style().clip_percent == 98.0 and dlg.max_spin.value() != 2.0


def test_positive_data_keep_their_zero(qgis_app, make_trace_layer):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    layer = make_trace_layer(np.abs(np.sin(np.arange(550, dtype=np.float32))).reshape(11, 50))
    dlg = DisplayDialog(None, layer)
    assert dlg.min_spin.value() == 0.0
    dlg.max_spin.setValue(0.5)
    assert dlg.min_spin.value() == 0.0 and dlg.style().clip_percent is None
    assert not dlg.polarity_check.isEnabled()
    assert dlg.polarity_check.toolTip() == "The data are never negative"


def test_the_amplitude_options_round_trip(qgis_app, trace_layer):
    from groundwork_geophysics.core.trace_section import DisplayGain, color_limits, display_values
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    dlg = DisplayDialog(None, trace_layer)
    # a quarter of the 49 ms record (at most 200 ms)
    assert not dlg.agc_spin.isEnabled() and dlg.agc_spin.value() == 12.0
    assert dlg.agc_spin.suffix() == " ms" and dlg.time_power_check.text() == "Gain with time"
    assert dlg.time_power_spin.value() == 2.0
    dlg.agc_check.setChecked(True)
    dlg.agc_spin.setValue(10.0)
    dlg.balance_check.setChecked(True)
    dlg.polarity_check.setChecked(True)
    s = dlg.style()
    assert s.gain == DisplayGain(agc_window=0.01, balance_traces=True, reverse_polarity=True)
    # the limits follow what is shown
    lo, hi = color_limits(display_values(trace_layer.traces.section, s.gain), 98.0)
    assert (s.scale.vmin, s.scale.vmax) == pytest.approx((lo, hi), abs=1e-3)
    again = DisplayDialog(None, replace(trace_layer, style=s))
    assert again.agc_check.isChecked() and again.agc_spin.value() == 10.0
    assert again.style().gain == s.gain


def test_a_long_record_starts_with_a_200_ms_window(qgis_app, make_trace_layer):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    a = np.sin(np.arange(11 * 2000, dtype=np.float32)).reshape(11, 2000)      # 2 s
    assert DisplayDialog(None, make_trace_layer(a)).agc_spin.value() == 200.0


def test_with_a_gain_the_limits_say_they_are_as_shown(qgis_app, trace_layer):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    dlg = DisplayDialog(None, trace_layer)
    form = dlg._scale_form
    label = {s: form.labelForField(s) for s in (dlg.min_spin, dlg.max_spin)}
    assert (label[dlg.min_spin].text(), label[dlg.max_spin].text()) == ("Minimum", "Maximum")
    dlg.time_power_check.setChecked(True)
    assert (label[dlg.min_spin].text(), label[dlg.max_spin].text()) == (
        "Minimum (as shown)", "Maximum (as shown)")
    dlg.time_power_check.setChecked(False)
    assert label[dlg.min_spin].text() == "Minimum"


def test_large_amplitudes_show_no_decimals(qgis_app, make_trace_layer):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    a = (np.sin(np.arange(550, dtype=np.float32)) * 5000.0).reshape(11, 50)
    dlg = DisplayDialog(None, make_trace_layer(a))
    assert dlg.max_spin.decimals() == 0 and dlg.min_spin.decimals() == 0
    assert DisplayDialog(None, make_trace_layer()).max_spin.decimals() >= 1


def test_paint_muted_zones_is_a_tick_of_its_own(qgis_app, trace_layer, store_with_model):
    from qgis.PyQt.QtWidgets import QCheckBox

    from groundwork_geophysics.core.trace_section import DisplayGain
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    dlg = DisplayDialog(None, trace_layer)
    tick = dlg.findChild(QCheckBox, "show_muted_check")
    assert tick is dlg.show_muted_check and tick.text() == "Paint muted zones"
    assert tick.toolTip() == ("Samples that are zero at the top or bottom of a trace are left "
                              "transparent unless this is ticked.")
    assert not tick.isChecked() and dlg.style().gain == DisplayGain()
    # last of the options, just before the note
    form = dlg.amplitudes_group.layout()
    widgets = [form.itemAt(i).widget() for i in range(form.count())]
    assert widgets.index(tick) == widgets.index(dlg.amplitudes_note) - 1
    tick.setChecked(True)
    s = dlg.style()
    assert s.gain == DisplayGain(show_muted=True) and not s.gain.active()
    again = DisplayDialog(None, replace(trace_layer, style=s))
    assert again.show_muted_check.isChecked() and again.style().gain == s.gain
    _prov, model = _layer(store_with_model)
    assert DisplayDialog(None, model).show_muted_check is None


def test_paint_muted_zones_keeps_the_limits(qgis_app, trace_layer, monkeypatch):
    from groundwork_geophysics.section import scale_dialog
    dlg = scale_dialog.DisplayDialog(None, trace_layer)
    before = (dlg.min_spin.value(), dlg.max_spin.value())
    calls = []
    monkeypatch.setattr(scale_dialog, "display_values", lambda *a: calls.append(a))
    dlg.show_muted_check.setChecked(True)
    assert (dlg.min_spin.value(), dlg.max_spin.value()) == before and calls == []


def test_a_depth_section_speaks_of_depth(qgis_app, make_trace_layer):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    dlg = DisplayDialog(None, make_trace_layer(domain="depth"))
    assert dlg.agc_spin.suffix() == " m" and dlg.agc_spin.value() == pytest.approx(4.9)
    assert dlg.time_power_check.text() == "Gain with depth"
    dlg.agc_check.setChecked(True)
    assert dlg.style().gain.agc_window == pytest.approx(4.9)


def test_the_note_says_the_readout_keeps_the_file(qgis_app, trace_layer):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    dlg = DisplayDialog(None, trace_layer)
    assert dlg.amplitudes_note.text() == ("These change the picture only. The readout shows the "
                                          "file's amplitudes.")


def test_the_dialog_reuses_the_drawings_copy(qgis_app, trace_layer, monkeypatch):
    from groundwork_geophysics.core.trace_section import DisplayGain
    from groundwork_geophysics.section import display_render, scale_dialog
    from groundwork_geophysics.section.display_render import build_drawing
    gained = replace(trace_layer, style=replace(trace_layer.style,
                                                gain=DisplayGain(balance_traces=True)))
    display_render.clear_cache()
    build_drawing(gained, None)
    calls = []
    monkeypatch.setattr(scale_dialog, "display_values", lambda *a: calls.append(a))
    dlg = scale_dialog.DisplayDialog(None, gained)
    dlg.clip_spin.setValue(80.0)
    assert calls == []
    display_render.clear_cache()


def test_a_trace_dialog_fits_a_laptop_screen(qgis_app, trace_layer):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    dlg = DisplayDialog(None, trace_layer)
    dlg.show()
    qgis_app.processEvents()
    try:
        assert dlg.height() <= 580
        assert dlg.amplitudes_note.isVisibleTo(dlg)
    finally:
        dlg.close()


def test_the_row_menu_of_a_trace_layer(qgis_app, make_trace_layer):
    from groundwork_geophysics.section.layer_list import (APPLY_ALL_TEXT, DISPLAY_TEXT,
                                                          INFO_TEXT, MISFIT_TEXT, REMOVE_TEXT,
                                                          LayerList)
    layer = make_trace_layer()
    ll = LayerList()
    try:
        ll.set_layers(None, [layer])
        texts = [a.text() for a in ll.row_menu(layer.dataset.id).actions() if a.text()]
        assert texts == [DISPLAY_TEXT, INFO_TEXT, APPLY_ALL_TEXT, REMOVE_TEXT]
        assert MISFIT_TEXT not in texts
        assert "amplitude" in ll._rows[layer.dataset.id].scale_button.toolTip().lower()
    finally:
        ll.deleteLater()


def test_a_trace_row_shows_its_clip(qgis_app, make_trace_layer):
    # a percent the user chose, never numbers from another section or a stale gain
    from groundwork_geophysics.core.colors import ColorScale
    from groundwork_geophysics.core.trace_section import DisplayGain
    from groundwork_geophysics.section.layer_list import _scale_text, clip_text
    from groundwork_geophysics.section.readout import format_value
    layer = make_trace_layer(scale=ColorScale("gray", -500.0, 500.0, False),
                             gain=DisplayGain(agc_window=0.01))
    assert _scale_text(layer) == "clip 98 % · AGC"
    assert clip_text(97.25) == "clip 97.2 %" or clip_text(97.25) == "clip 97.3 %"
    assert clip_text(0.1) == "clip 0.1 %" and clip_text(100.0) == "clip 100 %"
    typed = replace(layer, style=replace(layer.style, clip_percent=None))
    assert _scale_text(typed) == f"{format_value(-500.0)}–{format_value(500.0)} · AGC"


@pytest.mark.parametrize("gain, text", [
    ({}, "clip 98 %"), ({"agc_window": 0.2, "time_power": 2.0}, "clip 98 % · AGC"),
    ({"time_power": 2.0}, "clip 98 % · gain"), ({"balance_traces": True}, "clip 98 % · gain"),
    ({"reverse_polarity": True}, "clip 98 %")])
def test_a_trace_row_names_its_gain(qgis_app, make_trace_layer, gain, text):
    from groundwork_geophysics.core.trace_section import DisplayGain
    from groundwork_geophysics.section.layer_list import _scale_text
    assert _scale_text(make_trace_layer(gain=DisplayGain(**gain))) == text


def test_the_first_scale_never_builds_a_gained_copy(make_trace_layer, monkeypatch):
    from groundwork_geophysics.core.trace_section import DisplayGain
    from groundwork_geophysics.section import data
    calls = []
    real = data.display_values
    monkeypatch.setattr(data, "display_values", lambda *a: calls.append(a) or real(*a))
    layer = make_trace_layer(gain=DisplayGain(agc_window=0.01))
    assert layer.style.scale.cmap == "gray" and calls == []


@pytest.mark.parametrize("kind", ["model", "section"])
def test_the_help_button_opens_the_page_for_the_layer(qgis_app, store_with_model, trace_layer,
                                                      monkeypatch, kind):
    from qgis.PyQt.QtGui import QDesktopServices
    from qgis.PyQt.QtWidgets import QDialogButtonBox

    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    from groundwork_geophysics.ui.help import help_url
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: opened.append(url.toString()) or True))
    layer = trace_layer if kind == "section" else _layer(store_with_model)[1]
    dlg = DisplayDialog(None, layer)
    (box,) = dlg.findChildren(QDialogButtonBox)
    box.button(QDialogButtonBox.StandardButton.Help).click()
    assert opened == [help_url("trace_display" if kind == "section" else "display")]


# -- radar filters (dewow, background) and every trace layer ---------------------------------
def _radar_layer(make_trace_layer, **style):
    """The 11 x 50 section as a radargram: 1 ns samples, its dataset a GPR section."""
    from groundwork_geophysics.core.trace_section import place, Velocity
    layer = make_trace_layer(**style)
    sec = replace(layer.traces.section, step=1e-9)
    placed = place(sec, 500.0, Velocity(1.0e8))
    ds = replace(layer.dataset, kind="gpr_section", reader="gssi_dzt", source_path="a.dzt")
    return replace(layer, dataset=ds, traces=placed)


def test_the_two_filters_come_first_in_processing_order(qgis_app, trace_layer):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    dlg = DisplayDialog(None, trace_layer)
    form = dlg.amplitudes_group.layout()
    widgets = [form.itemAt(i).widget() for i in range(form.count())]
    order = [dlg.dewow_check, dlg.dewow_spin, dlg.background_check, dlg.background_combo,
             dlg.background_spin, dlg.agc_check]
    assert [widgets.index(w) for w in order] == sorted(widgets.index(w) for w in order)
    assert dlg.dewow_check.text() == "Remove drift (dewow)"
    assert dlg.background_check.text() == "Remove background"
    assert [dlg.background_combo.itemText(i) for i in range(dlg.background_combo.count())] == [
        "Whole line", "Moving window"]
    assert form.labelForField(dlg.dewow_spin).text() == "Window"
    assert form.labelForField(dlg.background_spin).text() == "Traces"
    assert not dlg.dewow_check.isChecked() and not dlg.dewow_spin.isEnabled()
    assert not dlg.background_check.isChecked() and not dlg.background_combo.isEnabled()
    assert dlg.style().gain == trace_layer.style.gain


@pytest.mark.parametrize("which, unit", [("seismic", " ms"), ("depth", " m"), ("radar", " ns")])
def test_the_windows_speak_the_layers_unit(qgis_app, make_trace_layer, which, unit):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    layer = (_radar_layer(make_trace_layer) if which == "radar" else
             make_trace_layer(domain="depth" if which == "depth" else "time"))
    dlg = DisplayDialog(None, layer)
    assert dlg.dewow_spin.suffix() == unit and dlg.agc_spin.suffix() == unit


def test_the_filters_round_trip_and_keep_every_field(qgis_app, make_trace_layer):
    from groundwork_geophysics.core.trace_section import DisplayGain
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    layer = _radar_layer(make_trace_layer)
    dlg = DisplayDialog(None, layer)
    dlg.dewow_check.setChecked(True)
    dlg.dewow_spin.setValue(7.5)
    dlg.background_check.setChecked(True)
    dlg.background_combo.setCurrentIndex(1)
    dlg.background_spin.setValue(5)
    dlg.agc_check.setChecked(True)
    dlg.agc_spin.setValue(20.0)
    g = dlg.style().gain
    assert g.dewow_window == pytest.approx(7.5e-9) and g.agc_window == pytest.approx(20e-9)
    assert (g.background, g.background_traces) == ("window", 5)
    again = DisplayDialog(None, replace(layer, style=dlg.style()))
    assert again.dewow_check.isChecked() and again.dewow_spin.value() == pytest.approx(7.5)
    assert again.background_combo.currentIndex() == 1 and again.background_spin.value() == 5
    assert again.style().gain == g
    whole = DisplayGain(dewow_window=3e-9, background="all", background_traces=9,
                        time_power=1.0, show_muted=True)
    kept = DisplayDialog(None, replace(layer, style=replace(layer.style, gain=whole)))
    assert kept.style().gain == whole                   # nothing it shows is lost


def test_a_model_has_no_filters(qgis_app, store_with_model):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    dlg = DisplayDialog(None, _layer(store_with_model)[1])
    assert getattr(dlg, "dewow_check", None) is None


@pytest.mark.parametrize("gain, text", [
    ({"dewow_window": 0.002}, "clip 98 % · dewow"),
    ({"dewow_window": 0.002, "background": "all", "agc_window": 0.02},
     "clip 98 % · dewow · background · AGC"),
    ({"background": "window", "background_traces": 5, "time_power": 1.0},
     "clip 98 % · background · gain")])
def test_a_trace_row_names_its_filters(qgis_app, make_trace_layer, gain, text):
    from groundwork_geophysics.core.trace_section import DisplayGain
    from groundwork_geophysics.section.layer_list import _scale_text
    assert _scale_text(make_trace_layer(gain=DisplayGain(**gain))) == text


def test_the_filters_are_kept_in_the_project(qgis_app):
    from groundwork_geophysics.core.trace_section import DisplayGain
    from groundwork_geophysics.section.data import LayerStyle
    from groundwork_geophysics.section.style_store import styles_from_json, styles_to_json
    gain = DisplayGain(dewow_window=7e-9, background="window", background_traces=101,
                       agc_window=2e-8)
    back = styles_from_json(styles_to_json({"g1": LayerStyle(gain=gain)}))
    assert back["g1"].gain == gain
