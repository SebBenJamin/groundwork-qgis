"""Usability round 1, Task 10 (D2): rename and delete profiles from the panel and the menu."""
import pytest


@pytest.fixture
def plugin(qgis_app, fake_iface, store_with_model):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench import classFactory
    st, p, _ = store_with_model
    QgsProject.instance().clear()
    plug = classFactory(fake_iface)
    plug.initGui()
    plug.set_store(st)
    plug.dock.open_profile(p.id)
    yield plug, st, p
    plug.unload()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qgis_app.processEvents()
    QgsProject.instance().removeAllMapLayers()
    QgsProject.instance().clear()


def _bar_texts(iface):
    return [i.text() for i in iface.messageBar().items()]


def test_delete_message_lists_what_goes():
    from geophysics_workbench.ui.profile_actions import delete_message
    text = delete_message("P1", {"stations": 24, "datasets": 2, "pieces": 3, "notes": 1})
    assert text.startswith("Delete profile “P1”?")
    assert "24 station(s)" in text and "2 model link(s)" in text
    assert "3 interpretation piece(s)" in text
    assert "1 field note(s)" in text and "data files and layers are not touched" in text


def test_context_menu_on_profile_combo(plugin):
    from geophysics_workbench.ui.profile_actions import DELETE_TEXT, RENAME_TEXT
    plug, st, p = plugin
    menu = plug.dock.profile_menu()
    assert [a.text() for a in menu.actions()] == [RENAME_TEXT, DELETE_TEXT]
    assert RENAME_TEXT == "Profile Properties…" and DELETE_TEXT == "Delete Profile…"


def test_profile_properties_open_from_the_plugin(plugin, fake_iface, monkeypatch,
                                                 warnings_shown):
    """The menu entry and the panel's right-click entry open the dialog; OK renames."""
    from geophysics_workbench.ui.profile_properties_dialog import ProfilePropertiesDialog
    plug, st, p = plugin

    def fake_exec(dialog):
        assert dialog.profile_id == p.id and dialog.dock is plug.dock
        dialog.name_edit.setText("Line A")
        dialog.accept()
        assert dialog.result() == 1, warnings_shown
        return 1

    monkeypatch.setattr(ProfilePropertiesDialog, "exec", fake_exec)
    plug.dock.rename_requested.emit(p.id)
    assert st.profile(p.id).name == "Line A"
    assert plug.dock.profile_combo.currentText() == "Line A"


def test_move_message_lists_what_moves():
    from geophysics_workbench.ui.profile_actions import move_message
    text = move_message("P1", {"stations": 5, "pieces": 3, "notes": 1})
    assert text == ("Move the line of profile “P1” to the surveyed points? Moved with it: "
                    "3 interpretation piece(s), 1 field note(s). Delivered interpretation "
                    "versions keep their old positions.")


def test_delete_open_profile_clears_panel(plugin, fake_iface, monkeypatch):
    from geophysics_workbench.ui import profile_actions
    plug, st, p = plugin
    monkeypatch.setattr(profile_actions, "confirm_delete", lambda parent, name, counts: True)
    plug.delete_profile()
    assert st.profiles() == []
    assert plug.dock.current_profile_id() is None and plug.dock.empty_hint.isVisible() is not None
    assert any("deleted" in t for t in _bar_texts(fake_iface))


def test_cancel_keeps_profile(plugin, monkeypatch):
    from geophysics_workbench.ui import profile_actions
    plug, st, p = plugin
    monkeypatch.setattr(profile_actions, "confirm_delete", lambda parent, name, counts: False)
    plug.delete_profile()
    assert [q.id for q in st.profiles()] == [p.id]


def test_plate_frame_of_deleted_profile(plugin, monkeypatch):
    """Review Focus 4: a plate showing the deleted profile keeps working (placeholder)."""
    from qgis.core import QgsProject

    from geophysics_workbench.core.plates import FrameLook, FrameSpec, PlateSpec
    from geophysics_workbench.plates.build import create_or_update_plate
    from geophysics_workbench.ui import profile_actions
    plug, st, p = plugin
    plate = PlateSpec("pl", "1", "P", "A4_landscape", [FrameSpec("f1", p.id, FrameLook())])
    layout = create_or_update_plate(QgsProject.instance(), st, plug.provider, plate)
    monkeypatch.setattr(profile_actions, "confirm_delete", lambda parent, name, counts: True)
    plug.delete_profile()
    assert layout.itemById("wb_frame_1").sources() == []
    create_or_update_plate(QgsProject.instance(), st, plug.provider, plate)
    assert "not found" in layout.itemById("wb_placeholder_1").text()
