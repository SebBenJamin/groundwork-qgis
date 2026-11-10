"""Usability round 1, Task 12 (D4): colour maps from QGIS colour ramps; old projects and
delivered plates keep exactly their colours."""
from dataclasses import asdict

import numpy as np
import pytest

from tests.section.test_display_dialog import _layer


def test_old_cmap_keeps_colours():
    """Review Focus 3: a scale without a QGIS ramp draws exactly as before (matplotlib)."""
    from matplotlib import colormaps

    from geophysics_workbench.core.colors import ColorScale
    from geophysics_workbench.core.plates import plates_from_json
    s = ColorScale("Spectral_r", 1.0, 1000.0, True)
    t = np.array([0.1, 0.37, 0.9])                      # (away from the colour bins' edges)
    want = np.rint(colormaps["Spectral_r"](t) * 255).astype(np.uint8)
    assert (s.rgba(10 ** (3 * t)) == want).all()
    assert ColorScale(**{"cmap": "viridis", "vmin": 1, "vmax": 2, "log": False}).ramp == ""
    old = ('[{"plate_id": "a", "number": "1", "title": "t", "template": "A4_landscape", '
           '"frames": [{"frame_id": "f", "profile_id": "p", "look": {"models": [{"dataset_id":'
           ' "d", "scale": {"cmap": "turbo", "vmin": 1.0, "vmax": 9.0, "log": false}}]}}]}]')
    [plate] = plates_from_json(old)
    assert ColorScale(**plate.frames[0].look.models[0].scale).cmap == "turbo"


def test_editing_min_max_keeps_the_old_look(qgis_app, store_with_model):
    from geophysics_workbench.section.scale_dialog import DisplayDialog
    _prov, layer = _layer(store_with_model)
    dlg = DisplayDialog(None, layer)
    dlg.max_spin.setValue(dlg.max_spin.value() * 2)
    s = dlg.style().scale
    assert s.ramp == "" and s.lut is None and s.cmap == layer.style.scale.cmap


def test_user_ramp_round_trip(qgis_app, store_with_model):
    from qgis.core import QgsStyle

    from geophysics_workbench.core.colors import ColorScale
    from geophysics_workbench.section.scale_dialog import DisplayDialog
    _prov, layer = _layer(store_with_model)
    dlg = DisplayDialog(None, layer)
    ramp = QgsStyle.defaultStyle().colorRamp("Viridis")
    dlg.ramp_button.setColorRamp(ramp)
    s = dlg.style().scale
    assert s.ramp and len(s.lut) == 256
    first, last = ramp.color(0.0), ramp.color(1.0)
    rgba = s.rgba([s.vmin, s.vmax])
    assert tuple(rgba[0][:3]) == (first.red(), first.green(), first.blue())
    assert tuple(rgba[1][:3]) == (last.red(), last.green(), last.blue())
    again = ColorScale(**asdict(s))                        # projects and plates (JSON)
    assert (again.rgba([s.vmin, s.vmax]) == rgba).all() and again.ramp == s.ramp
    reopened = DisplayDialog(None, type(layer)(layer.dataset, layer.mesh,
                                               dlg.style(), layer.error))
    assert reopened.ramp_button.colorRamp().color(1.0) == last     # edit again


def test_old_names_open_as_qgis_ramps(qgis_app):
    from geophysics_workbench.core.colors import COLORMAPS
    from geophysics_workbench.section.ramps import ramp_for_cmap
    for name in COLORMAPS:
        ramp = ramp_for_cmap(name)
        assert ramp is not None, name


def test_render_key_follows_the_ramp(store_with_model):
    from dataclasses import replace

    from geophysics_workbench.section.display_render import _key
    _prov, layer = _layer(store_with_model)
    a = _key(layer, None, (10, 10))
    layer.style.scale = replace(layer.style.scale, ramp="<x/>", lut=((0, 0, 0, 255),) * 256)
    assert _key(layer, None, (10, 10)) != a


def test_contours_group_only_for_contours(qgis_app, store_with_model):
    from geophysics_workbench.section.scale_dialog import DisplayDialog
    _prov, layer = _layer(store_with_model)
    dlg = DisplayDialog(None, layer)
    dlg.mode_combo.setCurrentIndex(dlg.mode_combo.findData("cells"))
    assert not dlg.contours_group.isEnabled()
    dlg.mode_combo.setCurrentIndex(dlg.mode_combo.findData("contours"))
    assert dlg.contours_group.isEnabled()
    dlg.log_check.setChecked(True)
    assert "decade" in dlg.step_spin.suffix()
