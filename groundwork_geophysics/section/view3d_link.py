"""The 3D view's mouse in the section: what the mouse points at in a QGIS 3D map view (a
curtain, a borehole column, a cloud point) becomes chainage and elevation on the section
panel's open profile, and the panel shows its cursor there. One way only: the section's own
mouse does not move anything in 3D."""
from __future__ import annotations

import numpy as np
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY,
                       QgsProject)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QObject, QPoint, QTimer

#: a hit counts when it is this close to the profile's line: max(1 m, 1 % of its length)
TOLERANCE_M, TOLERANCE_SHARE = 1.0, 0.01
CAST_MS = 66                         # at most about 15 rays a second
POLL_MS = 1000                       # how often newly opened 3D views are looked for


def section_point(xyz, chainage) -> tuple[float, float] | None:
    """(chainage, elevation) of the map point ``xyz`` on ``chainage``'s line, or ``None``
    when it is off the line (see TOLERANCE_M) or beyond its ends."""
    try:
        s, offset = chainage.project(np.array([[float(xyz[0]), float(xyz[1])]]))
    except ValueError:                           # degenerate geometry
        return None
    s, offset = float(s[0]), float(offset[0])
    tolerance = max(TOLERANCE_M, TOLERANCE_SHARE * chainage.length)
    if abs(offset) > tolerance or not -1e-9 <= s <= chainage.length + 1e-9:
        return None
    return s, float(xyz[2])


class View3dLink(QObject):
    """Follows the mouse in every open 3D map view of ``iface`` and moves ``dock``'s cursor."""

    def __init__(self, iface, dock):
        super().__init__()
        self.iface, self.dock = iface, dock
        self._canvases: list = []
        self._pending: tuple | None = None       # (canvas, QPoint) waiting for a ray
        self._cast = QTimer(self)
        self._cast.setSingleShot(True)
        self._cast.setInterval(CAST_MS)
        self._cast.timeout.connect(self.cast_now)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self.poll)
        self._poll.start()

    def poll(self) -> None:
        """Follow 3D views opened since the last look; let go of closed ones."""
        self._canvases = [c for c in self._canvases if not sip.isdeleted(c)]
        try:
            canvases = list(self.iface.mapCanvases3D())
        except (AttributeError, RuntimeError, TypeError):   # no 3D in this QGIS
            return
        for canvas in canvases:
            if canvas is not None and all(c is not canvas for c in self._canvases):
                canvas.installEventFilter(self)
                self._canvases.append(canvas)

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QEvent.Type.MouseMove:
            pos = event.position()
            self._pending = (obj, QPoint(int(pos.x()), int(pos.y())))
            if not self._cast.isActive():
                self._cast.start()
        elif etype == QEvent.Type.Leave:
            self._pending = None
            self._cast.stop()
            self._show(None)
        return False                             # the 3D view handles its mouse as usual

    def cast_now(self) -> None:
        """Ask the 3D scene what is under the mouse; show the nearest hit in the section."""
        pending, self._pending = self._pending, None
        if pending is None:
            return
        canvas, point = pending
        if sip.isdeleted(canvas):
            return
        try:
            from qgis._3d import QgsRayCastContext
            context = QgsRayCastContext()
            hits = list(canvas.castRay(point, context).allHits())
        except Exception:                        # no 3D, or the scene is not ready
            return
        self._show(min(hits, key=lambda h: h.distance()) if hits else None)

    def _show(self, hit) -> None:
        if sip.isdeleted(self.dock):
            return
        profile = self.dock.current_profile()
        if hit is None or profile is None:
            self.dock.show_cursor(None)
            return
        p = hit.mapCoordinates()
        x, y = self._to_store(p.x(), p.y())
        at = None if x is None else section_point((x, y, p.z()), profile.chainage)
        self.dock.show_cursor(*(at if at is not None else (None,)))

    def _to_store(self, x: float, y: float):
        """Map coordinates of the 3D view (the project CRS) in the store's CRS."""
        provider = self.dock.provider
        project = QgsProject.instance()
        if provider is None:
            return None, None
        src, dst = project.crs(), QgsCoordinateReferenceSystem(provider.store.crs_authid)
        if not src.isValid() or not dst.isValid() or src == dst:
            return x, y
        try:
            q = QgsCoordinateTransform(src, dst, project).transform(QgsPointXY(x, y))
        except Exception:                        # outside the CRS' valid area
            return None, None
        return q.x(), q.y()

    def unload(self) -> None:
        self._poll.stop()
        self._cast.stop()
        for canvas in self._canvases:
            if not sip.isdeleted(canvas):
                canvas.removeEventFilter(self)
        self._canvases = []
