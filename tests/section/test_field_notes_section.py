"""Field notes along the top of the section: markers, stretch bars, labels, hover text."""
import numpy as np

from test_context_render import _close, _img, _results, _x, _y


def _note(nid, s_from, s_to, text, shown=True, stations=""):
    from geophysics_workbench.core.field_notes import FieldNote
    return FieldNote(nid, "p1", s_from, s_to, text, shown=shown, stations=stations)


def _items(notes, crossings=()):
    from geophysics_workbench.core.context import ContextItems
    return ContextItems(crossings=list(crossings), field_notes=list(notes))


def _note_pixels(img, x0, x1, y0, y1):
    from geophysics_workbench.section.field_notes_render import NOTE_RGB
    return sum(1 for x in range(x0, x1) for y in range(y0, y1)
               if _close(img.pixel(x, y), NOTE_RGB, tol=50))


def test_point_note_marker_and_stretch_bar_drawn_above_ground(qgis_app):
    img = _img(_results(_items([_note("a", 50.0, None, "fence"),
                                _note("b", 60.0, 70.0, "wet ground")])))
    above = (0, _y(0.0) - 1)                         # ground at z = 0
    assert _note_pixels(img, _x(50.0) - 3, _x(50.0) + 4, *above) > 0
    bar = _note_pixels(img, _x(61.0), _x(69.0), *above)
    assert bar > (_x(69.0) - _x(61.0))              # a bar spanning the stretch
    assert _note_pixels(img, _x(41.0), _x(48.0), *above) == 0


def test_hidden_notes_draw_nothing(qgis_app):
    img = _img(_results(_items([_note("a", 50.0, None, "fence", shown=False)])))
    assert _note_pixels(img, 0, 400, 0, _y(0.0)) == 0


def test_labels_do_not_overlap_crossing_labels(qgis_app):
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtGui import QImage, QPainter, QTransform

    from geophysics_workbench.core.context import Crossing
    from geophysics_workbench.section.context_render import plan_labels
    note = _note("a", 60.0, None, "fence")
    c = Crossing(60.0, "380 kV", "line", 90.0)
    img = QImage(400, 200, QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    try:
        rc = QgsRenderContext.fromQPainter(painter)
        plan = plan_labels(painter, rc, QTransform(), _items([note], [c]),
                           (np.array([0.0, 100.0]), np.array([0.0, 0.0])))
    finally:
        painter.end()
    assert plan[id(note)].text == "fence" and plan[id(note)].y != plan[id(c)].y


def test_multiline_long_text_one_line_on_section_full_on_hover(qgis_app):
    """Review Focus 5."""
    from geophysics_workbench.section.field_notes_render import field_note_lines, label_text
    long = "electrodes 23-28 disabled because the farmer drove over the cable twice\nsee log"
    assert label_text(long) == "electrodes 23-28 disabled because the f…"
    n = _note("a", 115.0, 140.0, long, stations="23–28")
    assert field_note_lines([n], 120.0, 0.5) == [
        f"Field note 115.0–140.0 m (electrodes 23–28): {long.replace(chr(10), ' / ')}"]
    assert field_note_lines([n], 150.0, 0.5) == []
    assert field_note_lines([_note("b", 30.0, None, "fence")], 30.3, 0.5) == [
        "Field note 30.0 m: fence"]


def test_mirrored_profile_mirrors_notes():
    items = _items([_note("a", 10.0, None, "x"), _note("b", 20.0, 30.0, "y")])
    m = items.mirrored(100.0)
    assert [(n.s_from, n.s_to) for n in m.field_notes] == [(70.0, 80.0), (90.0, None)]


def test_hover_readout_lists_the_note(qgis_app):
    from geophysics_workbench.section.context_readout import context_hits
    hits = context_hits(_items([_note("b", 60.0, 70.0, "wet ground")]), 65.0, 0.5, 0.5, 0.5)
    assert "Field note 60.0–70.0 m: wet ground" in hits


def test_provider_context_carries_shown_notes_and_the_switch(store_with_model, qgis_app):
    from geophysics_workbench.core.context import ContextItems
    from geophysics_workbench.section.data import SectionDataProvider
    st, p, _ = store_with_model
    st.save_field_note(_note("a", 5.0, None, "fence").__class__(
        "a", p.id, 5.0, None, "fence"))
    st.save_field_note(_note("b", 9.0, None, "x").__class__("b", p.id, 9.0, None, "off",
                                                          shown=False))
    prov = SectionDataProvider(st)
    prov.context_source = lambda profile: ContextItems()
    assert [n.id for n in prov.context(p.id).field_notes] == ["a"]
    assert [n.id for n in prov.snapshot(p.id).context.field_notes] == ["a"]
    prov.show_field_notes = False
    assert prov.context(p.id).field_notes == []


def test_interpretation_menu_switches_field_notes(qgis_app, store_with_model, make_dock):
    st, p, _ = store_with_model
    dock = make_dock(st)
    act = dock.interp.buttons["show_notes"]
    assert act.isCheckable() and act.isChecked()
    act.setChecked(False)
    assert dock.provider.show_field_notes is False
    act.setChecked(True)
    assert dock.provider.show_field_notes is True
