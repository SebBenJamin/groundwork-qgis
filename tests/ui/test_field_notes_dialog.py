"""Field Notes… list for the current profile: add (also by electrodes), edit, switch, delete."""
import numpy as np
import pytest


@pytest.fixture
def setup(qgis_app, store_with_model):
    from geophysics_workbench.core.field_notes import FieldNote
    from geophysics_workbench.ui.field_notes_dialog import FieldNotesDialog
    st, p, _ = store_with_model
    st.ensure_field_notes()
    st.save_field_note(FieldNote("n1", p.id, 30.0, None, "fence", "obstacle"))
    changed = []
    dlg = FieldNotesDialog(st, p.id, lambda: changed.append(1))
    return st, p, dlg, changed


def test_list_shows_the_profiles_notes(setup):
    st, p, dlg, _ = setup
    assert dlg.table.rowCount() == 1
    assert dlg.table.item(0, 4).text() == "fence"


def test_dialog_adds_by_electrodes(setup):
    st, p, dlg, changed = setup
    names, chain = dlg.station_names()
    assert len(names) == 2                     # the test store: two stations
    first, last = names[0], names[1]
    dlg.add_by_stations(first, last, "electrodes disabled, farmer", "data quality")
    notes = {n.text: n for n in st.field_notes(p.id)}
    n = notes["electrodes disabled, farmer"]
    assert n.s_from == pytest.approx(chain[0]) and n.s_to == pytest.approx(chain[1])
    assert n.stations == f"{first}–{last}" and changed


def test_unknown_electrode_is_reported_not_saved(setup):
    st, p, dlg, _ = setup
    assert dlg.add_by_stations("9999", None, "x", "") is False
    assert "9999" in dlg.message.text() and len(st.field_notes(p.id)) == 1


def test_switching_shown_off_and_deleting(setup):
    st, p, dlg, changed = setup
    dlg.set_shown(0, False)
    assert st.field_notes(p.id)[0].shown is False
    dlg.delete_row(0)
    assert st.field_notes(p.id) == [] and dlg.table.rowCount() == 0 and len(changed) >= 2


def test_note_form_returns_the_edited_note(qgis_app):
    from geophysics_workbench.core.field_notes import FieldNote
    from geophysics_workbench.ui.field_notes_dialog import NoteForm
    form = NoteForm(FieldNote("x", "p", 5.0, None, ""), ["obstacle", "access"])
    form.text_edit.setPlainText("fence\nbroken")
    form.category_combo.setEditText("obstacle")
    form.shown_check.setChecked(False)
    n = form.note()
    assert (n.text, n.category, n.shown) == ("fence\nbroken", "obstacle", False)
