"""Final review of usability round 1: Auto keeps the user's zoom on resize, notes changed in
the Field Notes list are never brought back by undo/redo, a dragged vertex stays selected,
scale cells refuse decimals, and the remaining numbers follow the locale."""
import time

import pytest

from tests.section.test_interp_edit import ctl  # noqa: F401  (fixture)


def _pump(app, n=40):
    for _ in range(n):
        app.processEvents()
        time.sleep(0.02)


@pytest.mark.parametrize("typed", [False, True])
def test_resize_keeps_the_user_zoom(qgis_app, store_with_model, make_dock, typed):
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.resize(1366, 300)
    dock.show()
    dock.open_profile(p.id)
    if typed:
        dock.ve_spin.setValue(2.0)
    _pump(qgis_app)
    d = dock.canvas.visibleDistanceRange()
    full = d.upper() - d.lower()
    dock.fit.user_navigated()                         # the user zooms in (as the wheel does)
    e = dock.canvas.visibleElevationRange()
    dock.canvas.setVisiblePlotRange(d.lower(), d.lower() + full / 4, e.lower(), e.upper())
    _pump(qgis_app, 10)
    dock.resize(1366, 340)                            # then drags the dock's edge
    _pump(qgis_app)
    after = dock.canvas.visibleDistanceRange()
    assert after.upper() - after.lower() < full * 0.6


def test_notes_changed_in_the_list_are_not_brought_back(ctl, monkeypatch):
    from geophysics_workbench.ui.field_notes_dialog import FieldNotesDialog
    c, store, _p = ctl
    pid = c.dock.current_profile_id()
    c.note_form_factory = lambda note, cats: note.__class__(**{**note.__dict__,
                                                               "text": "fence"})
    c._note_finished(3.0, None)
    monkeypatch.setattr(FieldNotesDialog, "exec", lambda self: (self.delete_row(0), 0)[1])
    c.show_field_notes()                              # the user deletes it in the list
    assert store.field_notes(pid) == []
    c.undo.stack.undo()
    c.undo.stack.redo()
    assert store.field_notes(pid) == []


class _Release:
    def button(self):
        from qgis.PyQt.QtCore import Qt
        return Qt.MouseButton.LeftButton


def test_dragged_vertex_stays_selected(ctl):
    from geophysics_workbench.section.interp_edit import move_vertex
    c, store, p = ctl
    c.start("edit")
    tool = c.tool
    tool.select(p, 1)
    tool._drag = ("vertex", 1)
    tool._preview = move_vertex(p, 1, 6.0, -3.0)
    tool.plotReleaseEvent(_Release())
    assert tool.vertex == 1


def test_scale_cell_refuses_decimals():
    from geophysics_workbench.ui.plates_dialog import parse_cell
    assert parse_cell("scale", "2.500") == 2500 and parse_cell("scale", "1 000 000") == 1000000
    for text in ("2500.0", "2500,0", "25.00"):
        with pytest.raises(ValueError):
            parse_cell("scale", text)


def test_remaining_numbers_follow_the_locale(qgis_app):
    from qgis.PyQt.QtCore import QLocale

    from geophysics_workbench.section.borehole_viewer import tick_text
    from geophysics_workbench.ui.plates_dialog import cell_text
    old = QLocale()
    QLocale.setDefault(QLocale(QLocale.Language.German, QLocale.Country.Germany))
    try:
        assert tick_text(0.5) == "0,5" and tick_text(180.0) == "180"
        assert cell_text("ve", 1.5) == "1,5" and cell_text("scale", 1000000) == "1000000"
        assert cell_text("s_from", None) == ""
    finally:
        QLocale.setDefault(old)
