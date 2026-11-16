"""Field Notes… list for the current profile: add (also by electrodes), edit, switch, delete."""
import numpy as np
import pytest


@pytest.fixture
def setup(qgis_app, store_with_model):
    from groundwork_geophysics.core.field_notes import FieldNote
    from groundwork_geophysics.ui.field_notes_dialog import FieldNotesDialog
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
    from groundwork_geophysics.core.field_notes import FieldNote
    from groundwork_geophysics.ui.field_notes_dialog import NoteForm
    form = NoteForm(FieldNote("x", "p", 5.0, None, ""), ["obstacle", "access"])
    form.text_edit.setPlainText("fence\nbroken")
    form.category_combo.setEditText("obstacle")
    form.shown_check.setChecked(False)
    n = form.note()
    assert (n.text, n.category, n.shown) == ("fence\nbroken", "obstacle", False)


def _guessed(qgis_app, tmp_path):
    import shutil

    from groundwork_geophysics.core.model import (Dataset, file_fingerprint,
                                                 profile_from_polyline)
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    from groundwork_geophysics.ui.field_notes_dialog import FieldNotesDialog
    from pathlib import Path
    FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
    st = ProjectStore.create(tmp_path / "g.gpkg", "EPSG:25832")
    p = profile_from_polyline("D", "EPSG:25832", np.array([[0.0, 0.0], [60.0, 0.0]]))
    st.save_profile(p)
    src = tmp_path / "m.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("d", p.id, "", "ert_model", str(src), mt, sha, "r2_res_dat",
                            {"z_kind": "elevation"}, {}, name="d"))
    st.ensure_field_notes()
    return st, p, FieldNotesDialog(st, p.id, lambda: None, provider=SectionDataProvider(st))


def test_note_by_guessed_electrode_is_labelled(qgis_app, tmp_path):
    st, p, dlg = _guessed(qgis_app, tmp_path)
    assert dlg.add_by_stations("3", "5", "dry", "") is True
    n = st.field_notes(p.id)[0]
    assert n.stations == "3–5 (guessed)"
    assert (n.s_from, n.s_to) == pytest.approx((4.0, 8.0))      # electrodes 2 m apart


def test_note_by_imported_electrode_is_unlabelled(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.ui.field_notes_dialog import FieldNotesDialog
    st, p, _ = store_with_model
    st.ensure_field_notes()
    dlg = FieldNotesDialog(st, p.id, lambda: None, provider=SectionDataProvider(st))
    first = dlg.station_names()[0][0]
    assert dlg.add_by_stations(first, None, "x", "") is True
    assert st.field_notes(p.id)[0].stations == first
