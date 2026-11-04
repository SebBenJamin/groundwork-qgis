"""Display options of readings layers and the misfit summary window."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "section"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "readers"))
from test_readings_layer import misfit_store  # noqa: E402,F401  (fixture)


def _layer(misfit_store):
    from geophysics_workbench.section.data import SectionDataProvider
    st, p = misfit_store
    prov = SectionDataProvider(st)
    return prov, next(la for la in prov.layers(p.id) if la.dataset.id == "dm")


def test_display_dialog_offers_points_and_shown_value(qgis_app, misfit_store):
    from geophysics_workbench.section.scale_dialog import DisplayDialog
    _prov, layer = _layer(misfit_store)
    dlg = DisplayDialog(None, layer)
    modes = [dlg.mode_combo.itemData(i) for i in range(dlg.mode_combo.count())]
    assert modes[0] == "points"
    assert [dlg.shown_combo.itemData(i) for i in range(dlg.shown_combo.count())] == [
        "misfit", "measured", "calculated"]
    assert dlg.shown_combo.currentData() == "misfit"
    dlg.shown_combo.setCurrentIndex(1)
    s = dlg.style()
    assert s.shown == "measured" and s.scale is None          # a new value: automatic scale


def test_model_layers_have_no_points_or_shown(qgis_app, store_with_model):
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.section.scale_dialog import DisplayDialog
    st, p, _ = store_with_model
    layer = SectionDataProvider(st).layers(p.id)[0]
    dlg = DisplayDialog(None, layer)
    assert "points" not in [dlg.mode_combo.itemData(i) for i in range(dlg.mode_combo.count())]
    assert not dlg.shown_combo.isVisibleTo(dlg)


def test_row_menu_offers_misfit_summary_for_misfit_layers(qgis_app, misfit_store):
    from geophysics_workbench.section.layer_list import MISFIT_TEXT, LayerList
    prov, layer = _layer(misfit_store)
    model = next(la for la in prov.layers(misfit_store[1].id) if la.dataset.id != "dm")
    ll = LayerList()
    try:
        ll.set_layers(prov, [model, layer])
        assert MISFIT_TEXT in [a.text() for a in ll.row_menu("dm").actions()]
        assert MISFIT_TEXT not in [a.text() for a in ll.row_menu(model.dataset.id).actions()]
    finally:
        ll.deleteLater()


def test_misfit_summary_shows_numbers_and_histogram(qgis_app, misfit_store):
    from geophysics_workbench.ui.misfit_panel import MisfitSummary
    _prov, layer = _layer(misfit_store)
    w = MisfitSummary(None)
    w.show_layer(layer)
    rms = layer.mesh.readings.rms_percent()
    assert f"{rms:.1f} %" in w.numbers.text() and "5 readings" in w.numbers.text()
    assert "χ²" in w.numbers.text()
    assert w.plot.counts.sum() == np.isfinite(layer.mesh.readings.misfit_percent()).sum()
    w.deleteLater()
