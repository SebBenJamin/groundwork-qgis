"""Contour lines take a colour and a width the user picks in the Display dialog; without a
choice they are drawn as before (a darker shade of the scale colour, the standard widths)."""
from dataclasses import replace

import numpy as np
import pytest
from test_display_render import _layer, _results

RED = "#ff0000"


def test_by_default_the_line_takes_a_darker_shade_of_the_scale_colour(qgis_app):
    from qgis.PyQt.QtGui import QColor

    from groundwork_geophysics.section.display_render import CONTOUR_DARKER
    layer = _layer("contours", contour_step=10.0)
    [drawing] = _results(layer)._layers
    assert drawing.contour_width is None
    for colour, _path, _lines, text, _major in drawing.contours:
        r, g, b = (int(c) for c in layer.style.scale.rgba([float(text)])[0][:3])
        assert colour.name() == QColor(r, g, b).darker(CONTOUR_DARKER).name()


def test_a_picked_colour_reaches_every_contour_line(qgis_app):
    layer = _layer("contours", contour_step=10.0, contour_colour=RED, contour_width=0.5)
    [drawing] = _results(layer)._layers
    assert drawing.contours and {c[0].name() for c in drawing.contours} == {RED}
    assert drawing.contour_width == 0.5


def test_the_width_keeps_minor_levels_thinner_by_the_usual_ratio():
    from groundwork_geophysics.section.display_render import (CONTOUR_MINOR_PEN_MM,
                                                             CONTOUR_PEN_MM, contour_pen_mm)
    assert contour_pen_mm(True, None) == CONTOUR_PEN_MM
    assert contour_pen_mm(False, None) == CONTOUR_MINOR_PEN_MM
    assert contour_pen_mm(True, 1.0) == 1.0
    assert contour_pen_mm(False, 1.0) == pytest.approx(CONTOUR_MINOR_PEN_MM / CONTOUR_PEN_MM)


def _red_pixels(layer) -> int:
    """How many pixels of the painted section are (nearly) pure red."""
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtGui import QImage, QPainter, QTransform

    from groundwork_geophysics.section.display_render import build_drawing
    from groundwork_geophysics.section.profile_source import paint_layers
    drawing = build_drawing(layer, (np.array([0.0, 200.0]), np.array([0.5, 0.5])))
    img = QImage(400, 100, QImage.Format.Format_RGBA8888)
    img.fill(Qt.GlobalColor.white)
    painter = QPainter(img)
    try:
        wt = QTransform(10.0, 0.0, 0.0, -10.0, -400.0, 50.0)       # s 40..80, z 5..-5
        rc = QgsRenderContext.fromQPainter(painter)
        rc.setScaleFactor(4.0)                                      # 4 px per mm
        paint_layers(painter, [drawing], wt, rc)
    finally:
        painter.end()
    a = np.frombuffer(img.constBits().asstring(img.sizeInBytes()), np.uint8)
    a = a.reshape(100, img.bytesPerLine())[:, :400 * 4].reshape(100, 400, 4)
    return int(((a[..., 0] > 200) & (a[..., 1] < 60) & (a[..., 2] < 60)).sum())


def test_the_picked_width_reaches_the_pen(qgis_app):
    thin = _red_pixels(_layer("contours", contour_step=10.0, contour_colour=RED))
    thick = _red_pixels(_layer("contours", contour_step=10.0, contour_colour=RED,
                               contour_width=2.0))
    assert thin > 0 and thick > 4 * thin


def test_the_layer_list_applies_both():
    from groundwork_geophysics.section.layer_list import DISPLAY_FIELDS
    assert {"contour_colour", "contour_width"} <= set(DISPLAY_FIELDS)


def test_colour_and_width_survive_the_style_store_and_old_styles_load_the_defaults():
    from groundwork_geophysics.section.data import LayerStyle
    from groundwork_geophysics.section.style_store import styles_from_json, styles_to_json
    style = LayerStyle(mode="contours", contour_colour=RED, contour_width=0.5)
    back = styles_from_json(styles_to_json({"d1": style}))["d1"]
    assert (back.contour_colour, back.contour_width) == (RED, 0.5)
    old = styles_from_json('[{"dataset_id": "d1", "mode": "contours"}]')["d1"]
    assert old.contour_colour is None and old.contour_width is None


def test_a_plate_frame_keeps_the_contour_look():
    from groundwork_geophysics.section.data import LayerStyle
    from groundwork_geophysics.section.style_store import look_of, styled
    style = LayerStyle(mode="contours", contour_colour=RED, contour_width=0.5)
    back = styled(LayerStyle(), look_of("d1", style))
    assert (back.contour_colour, back.contour_width) == (RED, 0.5)


def test_the_3d_lines_take_the_picked_colour():
    from groundwork_geophysics.core.colors import ColorScale
    from groundwork_geophysics.section.data import LayerStyle
    from groundwork_geophysics.section.display_render import contour_colour
    scale = ColorScale("Spectral_r", 40.0, 80.0, False)
    assert contour_colour(LayerStyle(contour_colour=RED), scale, 50.0).name() == RED
    assert contour_colour(LayerStyle(), scale, 50.0).name() != RED


# -- the Display dialog ----------------------------------------------------------------------
@pytest.fixture
def dialog(qgis_app):
    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    made = []

    def make(**style):
        dlg = DisplayDialog(None, _layer("contours", **style))
        made.append(dlg)
        return dlg
    yield make
    for dlg in made:
        dlg.deleteLater()


def test_the_dialog_starts_from_the_colour_scale_and_the_standard_width(dialog):
    from groundwork_geophysics.section.scale_dialog import FROM_SCALE_TEXT
    dlg = dialog()
    assert dlg.line_colour_combo.currentText() == FROM_SCALE_TEXT
    assert not dlg.line_colour_button.isEnabled()
    assert dlg.line_width_spin.value() == pytest.approx(0.25)
    form = dlg.contours_group.layout()
    assert form.labelForField(dlg.line_width_spin).text() == "Line width (mm)"
    style = dlg.style()
    assert style.contour_colour is None and style.contour_width is None


def test_a_picked_colour_and_width_come_out_of_the_dialog(dialog):
    from qgis.PyQt.QtGui import QColor
    dlg = dialog()
    dlg.line_colour_combo.setCurrentIndex(1)
    assert dlg.line_colour_button.isEnabled()
    dlg.line_colour_button.setColor(QColor(RED))
    dlg.line_width_spin.setValue(0.5)
    style = dlg.style()
    assert (style.contour_colour, style.contour_width) == (RED, 0.5)


def test_the_dialog_shows_a_stored_colour_and_width(dialog):
    dlg = dialog(contour_colour=RED, contour_width=0.5)
    assert dlg.line_colour_combo.currentIndex() == 1
    assert dlg.line_colour_button.color().name() == RED
    assert dlg.line_width_spin.value() == pytest.approx(0.5)
    assert replace(dlg.style(), scale=None).contour_colour == RED
