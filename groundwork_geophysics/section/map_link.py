"""Map side of the section panel: a marker following the section cursor, and a map tool
that opens profiles by clicking them and moves the section guide line on hover."""
from __future__ import annotations

import math

import numpy as np
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY, QgsProject
from qgis.gui import QgsMapTool, QgsVertexMarker
from qgis.PyQt import sip
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

PICK_PX = 10        # click distance (pixels) that selects a profile line
HOVER_PX = 30       # mouse distance (pixels) from the open profile that moves the guide
BOREHOLE_PICK_PX = 6  # click distance (pixels) that opens a borehole of the open profile


def _store_crs(dock) -> QgsCoordinateReferenceSystem | None:
    if dock.provider is None:
        return None
    return QgsCoordinateReferenceSystem(dock.provider.store.crs_authid)


def _transform(src, dst) -> QgsCoordinateTransform | None:
    """Transform between two CRSs, or ``None`` when no transform is needed."""
    if src is None or dst is None or not src.isValid() or not dst.isValid() or src == dst:
        return None
    return QgsCoordinateTransform(src, dst, QgsProject.instance())


class ProfilePickTool(QgsMapTool):
    """Click a profile line to open it; hover near the open profile to move the guide."""

    def __init__(self, map_canvas, dock):
        super().__init__(map_canvas)
        self.dock = dock
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _to_store(self, map_point, px: float):
        """(x, y) of ``map_point`` in the store CRS and ``px`` pixels as store distance."""
        canvas = self.canvas()
        mupp = canvas.mapUnitsPerPixel()
        p0 = QgsPointXY(map_point)
        p1 = QgsPointXY(p0.x() + px * mupp, p0.y())
        tr = _transform(canvas.mapSettings().destinationCrs(), _store_crs(self.dock))
        if tr is not None:
            try:
                p0, p1 = tr.transform(p0), tr.transform(p1)
            except Exception:                       # outside the CRS' valid area
                return None, 0.0
        return np.array([p0.x(), p0.y()]), math.hypot(p1.x() - p0.x(), p1.y() - p0.y())

    def profile_at(self, map_point):
        """Nearest profile within ``PICK_PX`` of ``map_point``, or ``None``."""
        if self.dock.provider is None:
            return None
        xy, tol = self._to_store(map_point, PICK_PX)
        if xy is None:
            return None
        best = None
        for profile in self.dock.provider.store.profiles():
            try:
                _, offset = profile.chainage.project(xy)
            except ValueError:                      # degenerate geometry
                continue
            dist = abs(float(offset[0]))
            if dist <= tol and (best is None or dist < best[0]):
                best = (dist, profile)
        return None if best is None else best[1]

    def borehole_at(self, map_point) -> tuple[int, str] | None:
        """(entry, label) of a borehole of the open profile within ``BOREHOLE_PICK_PX`` of
        ``map_point`` (compared as chainage and offset), or ``None``."""
        profile = self.dock.current_profile()
        if profile is None or self.dock.provider is None:
            return None
        xy, tol = self._to_store(map_point, BOREHOLE_PICK_PX)
        if xy is None:
            return None
        try:
            s, offset = profile.chainage.project(xy)
            items = self.dock.provider.drawn_context(profile.id)
        except Exception:                           # degenerate geometry or no context
            return None
        best = None
        for p in (items.points if items is not None else []):
            if p.kind != "borehole":
                continue
            dist = math.hypot(float(s[0]) - p.s, float(offset[0]) - p.offset)
            if dist <= tol and (best is None or dist < best[0]):
                best = (dist, p)
        return None if best is None else (best[1].entry, best[1].label)

    def chainage_at(self, map_point) -> float | None:
        """Chainage on the open profile within ``HOVER_PX`` of ``map_point``, or ``None``."""
        profile = self.dock.current_profile()
        if profile is None:
            return None
        xy, tol = self._to_store(map_point, HOVER_PX)
        if xy is None:
            return None
        s, offset = profile.chainage.project(xy)
        return float(s[0]) if abs(float(offset[0])) <= tol else None

    def canvasReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        hit = self.borehole_at(event.mapPoint())
        if hit is not None:
            self.dock.borehole_clicked.emit(*hit)
            return
        profile = self.profile_at(event.mapPoint())
        if profile is not None:
            self.dock.open_profile(profile.id)
            self.dock.show()
            self.dock.raise_()

    def canvasMoveEvent(self, event):
        self.dock.show_cursor(self.chainage_at(event.mapPoint()))

    def deactivate(self):
        if not sip.isdeleted(self.dock):
            self.dock.show_cursor(None)
        super().deactivate()


class MapLink:
    """Owns the map marker and the pick tool; ``unload`` removes both from the canvas."""

    def __init__(self, iface, dock):
        self.dock = dock
        self.map_canvas = iface.mapCanvas()
        self.marker = QgsVertexMarker(self.map_canvas)
        self.marker.setIconType(QgsVertexMarker.IconType.ICON_CIRCLE)
        self.marker.setColor(QColor(200, 0, 0))
        self.marker.setFillColor(QColor(255, 255, 255, 160))
        self.marker.setIconSize(12)
        self.marker.setPenWidth(3)
        self.marker.setZValue(1000)
        self.marker.hide()
        self.tool = ProfilePickTool(self.map_canvas, dock)
        dock.cursor_moved.connect(self._cursor_moved)
        dock.cursor_left.connect(self._cursor_left)
        dock.zoom_map_requested.connect(self.zoom_to_profile)

    def zoom_to_profile(self, profile_id: str) -> None:
        """Zoom the map to the profile's line with a margin, and flash the line."""
        from qgis.core import QgsGeometry, QgsRectangle
        try:
            profile = self.dock.provider.store.profile(profile_id)
        except (AttributeError, KeyError):
            return
        xy = profile.chainage.xy
        store_crs = _store_crs(self.dock)
        box = QgsRectangle(float(xy[:, 0].min()), float(xy[:, 1].min()),
                           float(xy[:, 0].max()), float(xy[:, 1].max()))
        tr = _transform(store_crs, self.map_canvas.mapSettings().destinationCrs())
        if tr is not None:
            try:
                box = tr.transformBoundingBox(box)
            except Exception:                           # outside the CRS' valid area
                return
        # a margin of a fifth of the line's longer side on each side, at least 10 map units
        # (a short, straight N–S or E–W line has a box of zero width)
        margin = max(0.2 * max(box.width(), box.height()), 10.0)
        self.map_canvas.setExtent(box.buffered(margin))
        self.map_canvas.refresh()
        line = QgsGeometry.fromPolylineXY([QgsPointXY(float(x), float(y)) for x, y in xy])
        self.map_canvas.flashGeometries([line], store_crs)

    def _cursor_moved(self, s: float, _z: float) -> None:
        profile = self.dock.current_profile()
        if self.marker is None or profile is None or not 0.0 <= s <= profile.chainage.length:
            self._cursor_left()
            return
        x, y = (float(v) for v in profile.chainage.to_xy(s))
        point = QgsPointXY(x, y)
        tr = _transform(_store_crs(self.dock),
                        self.map_canvas.mapSettings().destinationCrs())
        if tr is not None:
            try:
                point = tr.transform(point)
            except Exception:
                self._cursor_left()
                return
        self.marker.setCenter(point)
        self.marker.show()

    def _cursor_left(self) -> None:
        if self.marker is not None:
            self.marker.hide()

    def unload(self) -> None:
        try:
            self.dock.cursor_moved.disconnect(self._cursor_moved)
            self.dock.cursor_left.disconnect(self._cursor_left)
            self.dock.zoom_map_requested.disconnect(self.zoom_to_profile)
        except (TypeError, RuntimeError):           # dock already gone
            pass
        if self.tool is not None:
            if self.map_canvas.mapTool() is self.tool:
                self.map_canvas.unsetMapTool(self.tool)
            self.tool.deleteLater()
            self.tool = None
        if self.marker is not None:
            self.map_canvas.scene().removeItem(self.marker)
            self.marker = None
