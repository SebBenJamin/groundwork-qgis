"""Map tools the dialogs share."""
from __future__ import annotations

import math

from qgis.core import QgsCsException, QgsPointXY
from qgis.gui import QgsMapToolEmitPoint
from qgis.PyQt.QtCore import QObject, pyqtSignal

from .positions_source import reprojection_error, to_store


def release(canvas, state: dict) -> None:
    """Take a pick's temporary tool off ``canvas`` and give the canvas back its previous tool
    (unless the user took another one). ``state`` is the pick's ``{"tool", "prev"}``; this
    holds no reference to the pick, so it can run when the pick's owner is destroyed."""
    tool, prev = state.get("tool"), state.get("prev")
    state["tool"] = state["prev"] = None
    if tool is None:
        return
    try:
        if canvas.mapTool() is tool:
            try:
                canvas.setMapTool(prev) if prev is not None else canvas.unsetMapTool(tool)
            except RuntimeError:                    # the previous tool is gone
                canvas.unsetMapTool(tool)
        tool.deleteLater()
    except RuntimeError:                            # the canvas went first
        pass


class TwoPointPick(QObject):
    """Two clicks on the map canvas: a start and an end point, in the store's CRS.

    ``picked(p1, p2)`` (``QgsPointXY``) follows the second click; ``ended`` follows every end
    of a pick: both points picked, another map tool taken, or ``cancel()``."""

    picked = pyqtSignal(object, object)
    ended = pyqtSignal()

    def __init__(self, iface, store_crs: str, project, parent=None):
        super().__init__(parent)
        self.iface, self.store_crs, self.project = iface, store_crs, project
        self.state: dict = {"tool": None, "prev": None}
        self._points: list[QgsPointXY] = []

    @property
    def active(self) -> bool:
        return self.state["tool"] is not None

    def start(self) -> None:
        self.cancel()
        canvas = self.iface.mapCanvas()
        tool = QgsMapToolEmitPoint(canvas)
        self._points = []
        self.state.update(tool=tool, prev=canvas.mapTool())
        tool.canvasClicked.connect(self._clicked)
        tool.deactivated.connect(self._lost)
        canvas.setMapTool(tool)

    def cancel(self) -> None:
        if self.active:
            release(self.iface.mapCanvas(), self.state)
            self.ended.emit()

    def _clicked(self, point, _button=None) -> None:
        canvas = self.iface.mapCanvas()
        crs = canvas.mapSettings().destinationCrs()
        try:
            tr = to_store(crs, self.store_crs, self.project)
            if tr is not None:
                point = tr.transform(point)
            if not (math.isfinite(point.x()) and math.isfinite(point.y())):
                raise QgsCsException("not finite")
        except QgsCsException:
            bar = self.iface.messageBar() if hasattr(self.iface, "messageBar") else None
            if bar is not None:
                bar.pushWarning("Pick on Map", str(reprojection_error(crs, self.store_crs)))
            return
        self._points.append(QgsPointXY(point))
        if len(self._points) == 2:
            self.picked.emit(*self._points)
            self.cancel()

    def _lost(self) -> None:
        """The user took another map tool: the pick ends, their tool stays."""
        if self.active:                     # (the canvas is switching tools: leave it be)
            tool = self.state["tool"]
            self.state["tool"] = self.state["prev"] = None
            tool.deleteLater()
            self.ended.emit()
