"""Round 2, B6: Create / Update keeps the user's edits of every plugin-written plate label
(stamp texts, field notes), also labels edited in
0.7; untouched labels follow the data."""
from dataclasses import replace

from tests.plates.test_build import _plate, env  # noqa: F401
from tests.ui.test_plates_dialog import _dialog


def _build(prj, st, prov, plate):
    from groundwork_geophysics.plates.build import create_or_update_plate
    return create_or_update_plate(prj, st, prov, plate)


def test_edited_title_kept(env):
    st, p, prov, prj = env
    plate = _plate(st, p)
    layout = _build(prj, st, prov, plate)
    layout.itemById("wb_stamp_title").setText("My title")
    layout = _build(prj, st, prov, replace(plate, title="Renamed"))
    assert layout.itemById("wb_stamp_title").text() == "My title"


def test_unedited_title_follows(env):
    st, p, prov, prj = env
    plate = _plate(st, p)
    _build(prj, st, prov, plate)
    layout = _build(prj, st, prov, replace(plate, title="Renamed"))
    assert layout.itemById("wb_stamp_title").text() == "Renamed"


def test_survey_and_caption_kept(env):
    st, p, prov, prj = env
    plate = _plate(st, p)
    layout = _build(prj, st, prov, plate)
    layout.itemById("wb_stamp_survey").setText("CRS: ETRS89 / UTM 32N")
    layout.itemById("wb_stamp_client_caption").setText("AUFTRAGGEBER")
    layout = _build(prj, st, prov, plate)
    assert layout.itemById("wb_stamp_survey").text() == "CRS: ETRS89 / UTM 32N"
    assert layout.itemById("wb_stamp_client_caption").text() == "AUFTRAGGEBER"


def test_legacy_label_edit_survives(env):
    """Review Focus 4: a 0.7 plate has no record of what the plugin wrote."""
    from groundwork_geophysics.plates.build import WRITTEN
    st, p, prov, prj = env
    plate = _plate(st, p)
    layout = _build(prj, st, prov, plate)
    title = layout.itemById("wb_stamp_title")
    title.removeCustomProperty(WRITTEN)
    title.setText("Edited in 0.7")
    layout = _build(prj, st, prov, plate)
    assert layout.itemById("wb_stamp_title").text() == "Edited in 0.7"


def test_new_plate_labels_written(env):
    """Review Focus 4: a fresh plate from each template gets its texts."""
    st, p, prov, prj = env
    for i, template in enumerate(("A4_landscape", "A4_portrait", "A3_landscape",
                                  "A3_portrait")):
        plate = replace(_plate(st, p, template=template), plate_id=f"pl{i}", number=str(i))
        layout = _build(prj, st, prov, plate)
        assert layout.itemById("wb_stamp_title").text() == plate.title, template
        assert layout.itemById("wb_stamp_plate").text() == f"Plate {i}", template
        assert "Scale 1:" in layout.itemById("wb_stamp_survey").text(), template


def test_edited_notes_kept_and_stale_flagged(env):
    from groundwork_geophysics.core.field_notes import FieldNote
    from groundwork_geophysics.plates.build import STALE_PROPERTY
    st, p, prov, prj = env
    st.save_field_note(FieldNote("a", p.id, 30.0, None, "fence"))
    plate = _plate(st, p)
    layout = _build(prj, st, prov, plate)
    layout.itemById("wb_field_notes").setText("My notes")
    layout = _build(prj, st, prov, plate)
    assert layout.customProperty(STALE_PROPERTY) in (None, [], "")      # notes unchanged
    st.save_field_note(FieldNote("b", p.id, 10.0, None, "gate"))
    layout = _build(prj, st, prov, plate)
    assert layout.itemById("wb_field_notes").text() == "My notes"
    assert "field notes" in (layout.customProperty(STALE_PROPERTY) or [])


def test_dialog_says_notes_changed(env):
    from groundwork_geophysics.core.field_notes import FieldNote
    st, p, prov, prj = env
    st.save_field_note(FieldNote("a", p.id, 30.0, None, "fence"))
    dlg = _dialog(st, prov, prj, panel_profile=p.id)
    dlg.add_plate()
    dlg.add_frame()
    dlg.take_from_panel(0)
    [layout] = dlg.create_plates()
    layout.itemById("wb_field_notes").setText("My notes")
    st.save_field_note(FieldNote("b", p.id, 10.0, None, "gate"))
    dlg.create_plates()
    assert "notes have changed" in dlg.message.text()
    assert "delete the label's text and press Update" in dlg.message.text()
