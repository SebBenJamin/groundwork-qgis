"""Plot tools for drawing interpretation on the section canvas (see spikes/interp_tool).

Coordinates are the canvas's plot coordinates: distance = forward chainage (the dock sets the
profile curve forward), elevation in metres. The readout signal does not fire while a custom
tool is active, so the tools pass hovered plot points to ``on_hover``.
"""
from __future__ import annotations

from typing import Callable

from qgis.core import QgsProfilePoint
from qgis.gui import QgsPlotTool
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QPointF, Qt
from qgis.PyQt.QtGui import QColor, QPainterPath, QPen
from qgis.PyQt.QtWidgets import QGraphicsPathItem

SKETCH_RGB = (170, 0, 140)
MIN_POINTS = {"point": 1, "line": 2, "polygon": 3}


class SketchItem:
    """A path over the plot, in canvas coordinates rebuilt from plot points."""

    def __init__(self, canvas):
        self.canvas = canvas
        self.item = QGraphicsPathItem()
        pen = QPen(QColor(*SKETCH_RGB), 1.5, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.item.setPen(pen)
        self.item.setZValue(1001)
        canvas.scene().addItem(self.item)

    def show(self, points, closed: bool = False, extra=None) -> None:
        pts = list(points) + ([extra] if extra is not None else [])
        path = QPainterPath()
        for k, (s, z) in enumerate(pts):
            q = self.canvas.plotPointToCanvasPoint(QgsProfilePoint(s, z))
            pt = QPointF(q.x(), q.y())
            if k == 0:
                path.moveTo(pt)
                path.addEllipse(pt, 2, 2)
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        if closed and len(pts) > 2:
            path.closeSubpath()
        self.item.setPath(path)

    def clear(self) -> None:
        self.item.setPath(QPainterPath())

    def remove(self) -> None:
        if self.item.scene() is not None:
            self.item.scene().removeItem(self.item)


class DrawTool(QgsPlotTool):
    """Click adds a vertex, double-click or Enter finishes, Backspace removes the last vertex,
    Esc clears the sketch (on an empty sketch: ``on_cancel``). A point finishes on its click."""

    def __init__(self, canvas, kind: str, on_finished: Callable[[list], None],
                 on_cancel: Callable[[], None] | None = None,
                 on_hover: Callable[[object], None] | None = None):
        super().__init__(canvas, f"interp-{kind}")
        # the canvas owns its tools: without this a late Python garbage collection deletes a
        # tool the canvas already deleted with itself (hard crash at teardown)
        sip.transferto(self, canvas)
        self.kind = kind
        self.on_finished, self.on_cancel, self.on_hover = on_finished, on_cancel, on_hover
        self.points: list[tuple[float, float]] = []
        self.sketch = SketchItem(canvas)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _plot(self, event):
        pp = self.canvas().canvasPointToPlotPoint(QPointF(event.pos()))
        return None if pp.isEmpty() else (float(pp.distance()), float(pp.elevation())), pp

    def plotPressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        xy, _ = self._plot(event)
        if xy is None:
            return
        self.points.append(xy)
        event.accept()
        if self.kind == "point":
            self._finish()
        else:
            self.sketch.show(self.points, self.kind == "polygon")

    def plotMoveEvent(self, event):
        xy, pp = self._plot(event)
        if self.on_hover is not None and xy is not None:
            self.on_hover(pp)
        if self.points and xy is not None:
            self.sketch.show(self.points, self.kind == "polygon", extra=xy)

    def plotDoubleClickEvent(self, event):
        event.accept()
        self._finish()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finish()
        elif key == Qt.Key.Key_Backspace and self.points:
            self.points.pop()
            self.sketch.show(self.points, self.kind == "polygon")
        elif key == Qt.Key.Key_Escape:
            if self.points:
                self.reset()
            elif self.on_cancel is not None:
                self.on_cancel()
        else:
            return
        event.accept()

    def _finish(self) -> None:
        pts = _dedup(self.points)
        self.reset()
        if len(pts) >= MIN_POINTS[self.kind]:
            self.on_finished(pts)

    def reset(self) -> None:
        self.points = []
        self.sketch.clear()

    def deactivate(self):
        self.reset()
        super().deactivate()


def _dedup(points):
    out = []
    for p in points:
        if not out or out[-1] != p:
            out.append(p)
    return out
