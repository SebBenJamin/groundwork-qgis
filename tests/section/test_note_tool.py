"""The Note tool: a click gives a note at one chainage, a drag a stretch; the form fills it."""
from test_interp_tools import dock  # noqa: F401


def _press_release(canvas, start, end):
    """Left press at ``start``, move and release at ``end`` (canvas positions)."""
    from qgis.PyQt.QtCore import QEvent, QPoint, QPointF, Qt
    from qgis.PyQt.QtGui import QMouseEvent
    from qgis.PyQt.QtWidgets import QApplication
    vp = canvas.viewport()
    for et, pos in ((QEvent.Type.MouseButtonPress, start), (QEvent.Type.MouseMove, end),
                    (QEvent.Type.MouseButtonRelease, end)):
        p = QPointF(pos)
        glob = QPointF(vp.mapToGlobal(QPoint(round(p.x()), round(p.y()))))
        moving = et == QEvent.Type.MouseMove
        buttons = (Qt.MouseButton.NoButton if et == QEvent.Type.MouseButtonRelease
                   else Qt.MouseButton.LeftButton)
        button = Qt.MouseButton.NoButton if moving else Qt.MouseButton.LeftButton
        QApplication.sendEvent(vp, QMouseEvent(et, p, glob, button, buttons,
                                               Qt.KeyboardModifier.NoModifier))


def _answer(text="fence", category="obstacle"):
    def form(note, categories):
        note.text, note.category = text, category
        return note
    return form


def test_click_gives_point_note(qgis_app, dock):
    from geophysics_workbench.section.interp_tools import plot_to_canvas
    dock.interp.note_form_factory = _answer()
    dock.interp.start("note")
    pos = plot_to_canvas(dock.canvas, 20.0, -2.0)
    _press_release(dock.canvas, pos, pos)
    [n] = dock.provider.store.field_notes(dock.current_profile_id())
    assert n.s_to is None and abs(n.s_from - 20.0) < 0.5
    assert (n.text, n.category) == ("fence", "obstacle")


def test_drag_gives_stretch_in_order(qgis_app, dock):
    from geophysics_workbench.section.interp_tools import plot_to_canvas
    dock.interp.note_form_factory = _answer("wet ground", "")
    dock.interp.start("note")
    _press_release(dock.canvas, plot_to_canvas(dock.canvas, 30.0, -2.0),
                   plot_to_canvas(dock.canvas, 12.0, -2.0))
    [n] = dock.provider.store.field_notes(dock.current_profile_id())
    assert abs(n.s_from - 12.0) < 0.5 and abs(n.s_to - 30.0) < 0.5


def test_cancelled_form_saves_nothing(qgis_app, dock):
    from geophysics_workbench.section.interp_tools import plot_to_canvas
    dock.interp.note_form_factory = lambda note, categories: None
    dock.interp.start("note")
    pos = plot_to_canvas(dock.canvas, 20.0, -2.0)
    _press_release(dock.canvas, pos, pos)
    assert dock.provider.store.field_notes() == []
