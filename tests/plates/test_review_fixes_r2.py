"""Final review of round 2: the plate-label rule's recovery path, 0.7 plates, note colours
on plates with the panel's notes off."""
from tests.plates.test_build import _plate, env  # noqa: F401


def _build(prj, st, prov, plate):
    from geophysics_workbench.plates.build import create_or_update_plate
    return create_or_update_plate(prj, st, prov, plate)


def test_emptied_label_is_refreshed(env):
    """The message says: delete the label's text and press Update - that must refresh it."""
    from geophysics_workbench.core.field_notes import FieldNote
    from geophysics_workbench.plates.build import STALE_PROPERTY
    st, p, prov, prj = env
    st.save_field_note(FieldNote("a", p.id, 30.0, None, "fence"))
    plate = _plate(st, p)
    layout = _build(prj, st, prov, plate)
    layout.itemById("wb_field_notes").setText("My notes")
    st.save_field_note(FieldNote("b", p.id, 10.0, None, "gate"))
    layout = _build(prj, st, prov, plate)
    layout.itemById("wb_field_notes").setText("")                    # as the message says
    layout = _build(prj, st, prov, plate)
    text = layout.itemById("wb_field_notes").text()
    assert "gate" in text and "fence" in text
    assert "field notes" not in (layout.customProperty(STALE_PROPERTY) or [])


def test_legacy_notes_text_reported_and_followed(env):
    """A 0.7 plate (no record) whose notes changed before the first 0.8 Update: the list is
    kept, but the message says the notes changed, and emptying it refreshes it."""
    from geophysics_workbench.core.field_notes import FieldNote
    from geophysics_workbench.plates.build import STALE_PROPERTY, WRITTEN
    st, p, prov, prj = env
    st.save_field_note(FieldNote("a", p.id, 30.0, None, "fence"))
    plate = _plate(st, p)
    layout = _build(prj, st, prov, plate)
    notes = layout.itemById("wb_field_notes")
    notes.removeCustomProperty(WRITTEN)                              # as 0.7 left it
    st.save_field_note(FieldNote("b", p.id, 10.0, None, "gate"))
    layout = _build(prj, st, prov, plate)
    assert "gate" not in layout.itemById("wb_field_notes").text()   # kept: maybe edited
    assert "field notes" in (layout.customProperty(STALE_PROPERTY) or [])
    layout.itemById("wb_field_notes").setText("")
    layout = _build(prj, st, prov, plate)
    assert "gate" in layout.itemById("wb_field_notes").text()


def test_plate_note_colours_with_panel_notes_off(env):
    from qgis.core import QgsSingleSymbolRenderer
    from qgis.PyQt.QtGui import QColor

    from geophysics_workbench.core.field_notes import FieldNote
    from geophysics_workbench.core.plates import FrameLook
    from geophysics_workbench.section.field_notes_render import note_looks
    from geophysics_workbench.ui.field_note_layers import ensure_note_layers
    st, p, prov, prj = env
    st.save_field_note(FieldNote("b", p.id, 10.0, 20.0, "wet ground"))
    st.rebuild_field_note_geometry({q.id: q.chainage for q in st.profiles()})
    layers = ensure_note_layers(st, prj)
    sym = layers["field_notes_lines"].renderer().symbol().clone()
    sym.setColor(QColor(0, 0, 255))
    layers["field_notes_lines"].setRenderer(QgsSingleSymbolRenderer(sym))
    prov.note_looks = lambda: note_looks(st, prj)
    prov.show_field_notes = False                                    # panel: notes off
    snap = prov.snapshot(p.id, look=FrameLook())                      # plate: notes on
    assert snap.context.note_looks["b"].rgb == (0, 0, 255)
