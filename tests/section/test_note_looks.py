"""Round 2, F5: the section (and plates) draw field notes in their layers' colours."""
import pytest
from qgis.PyQt.QtGui import QColor


@pytest.fixture
def setup(qgis_app, store_with_model):
    from qgis.core import QgsProject

    from groundwork_geophysics.core.field_notes import FieldNote
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.field_notes_render import note_looks
    from groundwork_geophysics.ui.field_note_layers import ensure_note_layers, field_note_layers
    st, p, _ = store_with_model
    prj = QgsProject.instance()
    prj.clear()
    st.save_field_note(FieldNote("b", p.id, 10.0, 20.0, "wet ground"))
    st.rebuild_field_note_geometry({q.id: q.chainage for q in st.profiles()})
    ensure_note_layers(st, prj)
    prov = SectionDataProvider(st)
    prov.note_looks = lambda: note_looks(st, prj)
    yield st, p, prov, field_note_layers(st, prj)
    prj.removeAllMapLayers()
    prj.clear()


def _blue(layer):
    from qgis.core import QgsSingleSymbolRenderer
    sym = layer.renderer().symbol().clone()
    sym.setColor(QColor(0, 0, 255))
    layer.setRenderer(QgsSingleSymbolRenderer(sym))


def test_section_uses_layer_colour(setup):
    st, p, prov, layers = setup
    _blue(layers["field_notes_lines"])
    snap = prov.snapshot(p.id)
    assert snap.context.note_looks["b"].rgb == (0, 0, 255)


def test_plate_uses_layer_colour(setup):
    from groundwork_geophysics.core.plates import FrameLook
    st, p, prov, layers = setup
    _blue(layers["field_notes_lines"])
    snap = prov.snapshot(p.id, look=FrameLook())
    assert snap.context.note_looks["b"].rgb == (0, 0, 255)


def test_stretch_drawn_in_layer_colour(setup):
    """The stretch's bar is painted in the layer's colour."""
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtGui import QImage, QPainter, QTransform

    from groundwork_geophysics.section.context_render import plan_labels
    from groundwork_geophysics.section.field_notes_render import draw_field_notes
    import numpy as np
    st, p, prov, layers = setup
    _blue(layers["field_notes_lines"])
    items = prov.snapshot(p.id).context
    img = QImage(400, 200, QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    try:
        rc = QgsRenderContext.fromQPainter(painter)
        wt = QTransform(10.0, 0.0, 0.0, -10.0, 0.0, 100.0)
        surface = (np.array([0.0, 40.0]), np.array([0.0, 0.0]))
        plan = plan_labels(painter, rc, wt, items, surface)
        draw_field_notes(painter, rc, wt, items, surface, plan)
    finally:
        painter.end()
    blue = sum(1 for x in range(0, 400, 2) for y in range(0, 200, 2)
               if QColor(img.pixel(x, y)).blue() > 200 and QColor(img.pixel(x, y)).red() < 60)
    assert blue > 0
