"""Usability round 1, Task 1: every drawing edit is one undo step; Ctrl+Z / Ctrl+Y work in
the section panel."""
import pytest

from tests.section.test_interp_edit import ctl  # noqa: F401  (fixture)


def _pieces(store, pid):
    return store.pieces(store.current_version().id, pid)


def test_new_piece_is_undoable(ctl):
    from geophysics_workbench.core.interpretation import InterpFeature
    c, store, _p = ctl
    pid = c.dock.current_profile_id()
    c.form_factory = lambda feature, s, letters, existing=(): InterpFeature(
        feature.id, feature.version_id, type="fault", letter="B")
    before = len(_pieces(store, pid))
    c._finished("line", [(1.0, -1.0), (4.0, -2.0)])
    added = [p for p in _pieces(store, pid) if p.kind == "line"]
    assert len(_pieces(store, pid)) == before + 1 and c.undo.stack.canUndo()
    new_id = next(p.id for p in added if p.vertices[0][0] == pytest.approx(1.0))
    c.undo.stack.undo()
    assert len(_pieces(store, pid)) == before
    c.undo.stack.redo()
    assert new_id in {p.id for p in _pieces(store, pid)}


def test_new_note_is_undoable(ctl):
    c, store, _p = ctl
    pid = c.dock.current_profile_id()
    c.note_form_factory = lambda note, cats: note.__class__(**{**note.__dict__,
                                                               "text": "fence"})
    c._note_finished(3.0, None)
    assert [n.text for n in store.field_notes(pid)] == ["fence"]
    c.undo.stack.undo()
    assert store.field_notes(pid) == []
    c.undo.stack.redo()
    assert [n.text for n in store.field_notes(pid)] == ["fence"]


def test_ctrl_z_and_ctrl_y_in_panel(ctl, qgis_app):
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtGui import QShortcut

    from geophysics_workbench.core.interpretation import InterpFeature
    c, store, _p = ctl
    pid = c.dock.current_profile_id()
    c.form_factory = lambda feature, s, letters, existing=(): InterpFeature(
        feature.id, feature.version_id, type="fault", letter="C")
    before = len(_pieces(store, pid))
    c._finished("line", [(1.0, -1.0), (4.0, -2.0)])
    shortcuts = {s.key().toString() for s in c.dock.findChildren(QShortcut)}
    assert {"Ctrl+Z", "Ctrl+Y", "Ctrl+Shift+Z"} <= shortcuts
    assert c.dock.undo_shortcut.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut
    c.dock.undo_shortcut.activated.emit()
    assert len(_pieces(store, pid)) == before
    c.dock.redo_shortcut.activated.emit()
    assert len(_pieces(store, pid)) == before + 1


def test_switching_profile_clears_undo(ctl):
    from geophysics_workbench.core.interpretation import InterpFeature
    c, store, _p = ctl
    c.form_factory = lambda feature, s, letters, existing=(): InterpFeature(
        feature.id, feature.version_id, type="fault", letter="D")
    c._finished("line", [(1.0, -1.0), (4.0, -2.0)])
    assert c.undo.stack.canUndo()
    c._profile_changed()
    assert not c.undo.stack.canUndo()


def test_undo_refreshes_the_edit_selection(ctl):
    """Usability review 2, R3: after Undo the Edit tool kept the undone shape selected, and
    the next edit saved it back."""
    import copy
    c, store, p = ctl
    c.start("edit")
    tool = c.tool
    tool.select(p)
    moved = copy.deepcopy(p)
    moved.vertices = [(x + 3.0, z) for x, z in p.vertices]
    tool.select(c.replace_piece(p, moved))
    c.undo.stack.undo()
    assert tool.selected.vertices[0][0] == pytest.approx(p.vertices[0][0])  # the stored shape
    c.undo.stack.redo()
    assert tool.selected.vertices[0][0] == pytest.approx(p.vertices[0][0] + 3.0)
    c.delete_piece(tool.selected)
    assert tool.selected is None                                      # gone: no selection
