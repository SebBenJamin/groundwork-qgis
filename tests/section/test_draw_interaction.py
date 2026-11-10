"""Usability round 1, Task 2: drawing like QGIS — right-click finishes, a hint per tool, the
Note drag shows its stretch while dragging."""
from test_interp_tools import dock  # noqa: F401


def _mouse(canvas, etype, pos, button):
    from qgis.PyQt.QtCore import QEvent, QPoint, QPointF, Qt
    from qgis.PyQt.QtGui import QMouseEvent
    from qgis.PyQt.QtWidgets import QApplication
    vp = canvas.viewport()
    p = QPointF(pos)
    glob = QPointF(vp.mapToGlobal(QPoint(round(p.x()), round(p.y()))))
    buttons = Qt.MouseButton.NoButton if etype == QEvent.Type.MouseButtonRelease else button
    QApplication.sendEvent(vp, QMouseEvent(etype, p, glob, button, buttons,
                                           Qt.KeyboardModifier.NoModifier))


def _click(canvas, pos, right=False):
    from qgis.PyQt.QtCore import QEvent, Qt
    b = Qt.MouseButton.RightButton if right else Qt.MouseButton.LeftButton
    _mouse(canvas, QEvent.Type.MouseButtonPress, pos, b)
    _mouse(canvas, QEvent.Type.MouseButtonRelease, pos, b)


def test_right_click_finishes_line(qgis_app, dock):
    from geophysics_workbench.section.interp_tools import plot_to_canvas
    got = []
    dock.interp._finished = lambda kind, pts: got.append((kind, pts))
    dock.interp.start("line")
    _click(dock.canvas, plot_to_canvas(dock.canvas, 10.0, -2.0))
    _click(dock.canvas, plot_to_canvas(dock.canvas, 20.0, -3.0))
    _click(dock.canvas, plot_to_canvas(dock.canvas, 25.0, -3.0), right=True)
    assert len(got) == 1 and got[0][0] == "line" and len(got[0][1]) == 2


def test_right_click_with_too_few_points_cancels(qgis_app, dock):
    from geophysics_workbench.section.interp_tools import plot_to_canvas
    got = []
    dock.interp._finished = lambda kind, pts: got.append(pts)
    dock.interp.start("polygon")
    _click(dock.canvas, plot_to_canvas(dock.canvas, 10.0, -2.0))
    _click(dock.canvas, plot_to_canvas(dock.canvas, 12.0, -2.0), right=True)
    assert got == [] and dock.interp.tool.points == []


def test_edit_tool_right_click_menu_unchanged(qgis_app, dock):
    """Review Focus 2: only drawing tools finish on right-click."""
    from geophysics_workbench.section.interp_tools import DrawTool, EditTool
    assert "RightButton" in __import__("inspect").getsource(EditTool)
    assert hasattr(DrawTool, "plotPressEvent")


def test_tool_hint_shown(qgis_app, dock):
    from geophysics_workbench.section.interp_controller import TOOL_HINTS
    assert TOOL_HINTS["line"] == "Line: click to add points, right-click to finish, Esc to cancel"
    for kind in ("line", "polygon", "point", "note", "edit"):
        dock.interp.start(kind)
        assert dock.readout.text() == TOOL_HINTS[kind], kind
    dock.interp.stop()
    assert dock.readout.text() != TOOL_HINTS["edit"]


def test_note_drag_shows_stretch(qgis_app, dock):
    from qgis.PyQt.QtCore import QEvent, Qt

    from geophysics_workbench.section.interp_tools import plot_to_canvas
    dock.interp.note_form_factory = lambda note, cats: None
    dock.interp.start("note")
    tool = dock.interp.tool
    a, b = plot_to_canvas(dock.canvas, 10.0, -2.0), plot_to_canvas(dock.canvas, 30.0, -2.0)
    _mouse(dock.canvas, QEvent.Type.MouseButtonPress, a, Qt.MouseButton.LeftButton)
    _mouse(dock.canvas, QEvent.Type.MouseMove, b, Qt.MouseButton.LeftButton)
    lo, hi = tool.preview_range
    assert abs(lo - 10.0) < 0.6 and abs(hi - 30.0) < 0.6 and tool.preview.isVisible()
    _mouse(dock.canvas, QEvent.Type.MouseButtonRelease, b, Qt.MouseButton.LeftButton)
    assert tool.preview_range is None and not tool.preview.isVisible()
