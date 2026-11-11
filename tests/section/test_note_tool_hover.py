"""Round 2, B2: with the Note tool active, moving the mouse still shows the position on the
map (the dock's ``cursor_moved``), before a press and while a stretch is dragged."""
from test_interp_tools import dock  # noqa: F401


def _send(canvas, et, pos, buttons):
    from qgis.PyQt.QtCore import QPoint, QPointF, Qt
    from qgis.PyQt.QtGui import QMouseEvent
    from qgis.PyQt.QtWidgets import QApplication
    vp = canvas.viewport()
    p = QPointF(pos)
    glob = QPointF(vp.mapToGlobal(QPoint(round(p.x()), round(p.y()))))
    button = Qt.MouseButton.NoButton if et.name == "MouseMove" else Qt.MouseButton.LeftButton
    QApplication.sendEvent(vp, QMouseEvent(et, p, glob, button, buttons,
                                           Qt.KeyboardModifier.NoModifier))


def test_note_tool_moves_map_cursor(qgis_app, dock):
    from qgis.PyQt.QtCore import QEvent, Qt

    from geophysics_workbench.section.interp_tools import plot_to_canvas
    seen = []
    dock.cursor_moved.connect(lambda s, z: seen.append(s))
    dock.interp.note_form_factory = lambda note, categories: None
    dock.interp.start("note")
    c = dock.canvas
    none, left = Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton
    _send(c, QEvent.Type.MouseMove, plot_to_canvas(c, 15.0, -2.0), none)      # just hovering
    _send(c, QEvent.Type.MouseButtonPress, plot_to_canvas(c, 20.0, -2.0), left)
    _send(c, QEvent.Type.MouseMove, plot_to_canvas(c, 30.0, -2.0), left)      # dragging
    _send(c, QEvent.Type.MouseButtonRelease, plot_to_canvas(c, 30.0, -2.0), none)
    assert len(seen) >= 2
    assert abs(seen[0] - 15.0) < 0.5 and any(abs(s - 30.0) < 0.5 for s in seen)
