"""The 3D view's mouse in the section: what the mouse points at in a QGIS 3D map view (a
curtain, a borehole column, a cloud point) becomes chainage and elevation on the section
panel's open profile; the panel shows its cursor there and, as for its own mouse, the 2D map
its marker. A left click (no drag) on another profile's curtain opens that profile in the
panel; hovering never switches. One way only: the section's own mouse does not move
anything in 3D."""
from __future__ import annotations

import numpy as np
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY,
                       QgsProject)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QObject, QPoint, Qt, QTimer

#: a hit counts when it is this close to the profile's line: max(1 m, 1 % of its length)
TOLERANCE_M, TOLERANCE_SHARE = 1.0, 0.01
CAST_MS = 40                         # at most about 25 rays a second
#: a miss keeps the cursor this long before it hides (a ray slipping between a cloud's points
#: must not blink it off)
HOLD_MS = 300
#: degrees around the ray a point of a point cloud may lie (QGIS's identify tool uses 0.5;
#: the default 0 misses every point)
ANGLE_DEGREES = 0.5
POLL_MS = 1000                       # how often newly opened 3D views are looked for
#: a press and release of the left button at most this far apart (px) is a click, not a turn
CLICK_PX = 4


def _offset(xyz, chainage) -> tuple[float, float] | None:
    """(chainage, distance from the line) of the map point ``xyz`` on ``chainage``'s line, or
    ``None`` when it is off the line (see TOLERANCE_M) or beyond its ends."""
    try:
        s, offset = chainage.project(np.array([[float(xyz[0]), float(xyz[1])]]))
    except ValueError:                           # degenerate geometry
        return None
    s, offset = float(s[0]), abs(float(offset[0]))
    tolerance = max(TOLERANCE_M, TOLERANCE_SHARE * chainage.length)
    if offset > tolerance or not -1e-9 <= s <= chainage.length + 1e-9:
        return None
    return s, offset


def section_point(xyz, chainage) -> tuple[float, float] | None:
    """(chainage, elevation) of the map point ``xyz`` on ``chainage``'s line, or ``None``
    when it is off the line (see TOLERANCE_M) or beyond its ends."""
    at = _offset(xyz, chainage)
    return None if at is None else (at[0], float(xyz[2]))


def profile_at(xyz, profiles):
    """The profile of ``profiles`` whose line the map point ``xyz`` is on (the same rule as
    ``section_point``), the nearest line when several are close; ``None`` off every line."""
    best = None
    for profile in profiles:
        try:
            at = _offset(xyz, profile.chainage)
        except Exception:                        # a profile without a usable line
            continue
        if at is not None and (best is None or at[1] < best[0]):
            best = (at[1], profile)
    return None if best is None else best[1]


class View3dLink(QObject):
    """Follows the mouse in every open 3D map view of ``iface`` and moves ``dock``'s cursor;
    a click on a curtain opens its profile. ``on_opened`` (if set) is called when a 3D view
    is seen for the first time."""

    def __init__(self, iface, dock):
        super().__init__()
        self.iface, self.dock = iface, dock
        self.on_opened = None
        self._canvases: list = []
        self._pending: tuple | None = None       # (canvas, QPoint) waiting for a ray
        self._press: tuple | None = None         # (canvas, QPointF) of a left press
        self._cast = QTimer(self)
        self._cast.setSingleShot(True)
        self._cast.setInterval(CAST_MS)
        self._cast.timeout.connect(self.cast_now)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.setInterval(HOLD_MS)
        self._hold.timeout.connect(self.hide_now)
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
        opened = False
        for canvas in canvases:
            if canvas is not None and all(c is not canvas for c in self._canvases):
                canvas.installEventFilter(self)
                self._canvases.append(canvas)
                opened = True
        if opened and self.on_opened is not None:
            self.on_opened()

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QEvent.Type.MouseButtonPress:
            left = event.button() == Qt.MouseButton.LeftButton
            self._press = (obj, event.position()) if left else None
        elif etype == QEvent.Type.MouseButtonRelease:
            press, self._press = self._press, None
            if (event.button() == Qt.MouseButton.LeftButton and press is not None
                    and press[0] is obj and not self._moved(press[1], event.position())):
                pos = event.position()
                self.click_at(obj, QPoint(int(pos.x()), int(pos.y())))
        elif etype == QEvent.Type.MouseMove:
            if self._press is not None and self._moved(self._press[1], event.position()):
                self._press = None               # a drag: turning or panning the view
            if event.buttons() != Qt.MouseButton.NoButton or not self._can_show():
                return False                     # turning the view, or nowhere to show it
            pos = event.position()
            self._pending = (obj, QPoint(int(pos.x()), int(pos.y())))
            if not self._cast.isActive():
                self._cast.start()
        elif etype == QEvent.Type.Leave:
            self._pending = None
            self._cast.stop()
            self.hide_now()
        return False                             # the 3D view handles its mouse as usual

    def cast_now(self) -> None:
        """Ask the 3D scene what is under the mouse; show the nearest hit in the section."""
        pending, self._pending = self._pending, None
        if pending is None:
            return
        canvas, point = pending
        if sip.isdeleted(canvas) or not self._can_show():
            return
        hits = self._ray(canvas, point)
        if hits is not None:
            self._show(min(hits, key=lambda h: h.distance()) if hits else None)

    @staticmethod
    def _ray(canvas, point) -> list | None:
        """Everything the ray under ``point`` hits; ``None`` when no ray could be cast."""
        try:
            from qgis._3d import QgsRayCastContext
            context = QgsRayCastContext()
            context.setAngleThreshold(ANGLE_DEGREES)
            return list(canvas.castRay(point, context).allHits())
        except Exception:                        # no 3D, or the scene is not ready
            return None

    @staticmethod
    def _moved(a, b) -> bool:
        return abs(a.x() - b.x()) > CLICK_PX or abs(a.y() - b.y()) > CLICK_PX

    def click_at(self, canvas, point) -> None:
        """A click at ``point`` in ``canvas``: open (and show) the profile of the nearest
        thing hit, when it is not the one open; the panel's cursor goes to the hit."""
        dock = self.dock
        if sip.isdeleted(dock) or sip.isdeleted(canvas) or dock.provider is None:
            return
        hits = self._ray(canvas, point)
        if not hits:
            return
        hit = min(hits, key=lambda h: h.distance())
        p = hit.mapCoordinates()
        x, y = self._to_store(p.x(), p.y())
        if x is None:
            return
        try:
            profile = profile_at((x, y, p.z()), dock.provider.store.profiles())
            if profile is None:
                return
            def show() -> None:
                dock.show()
                dock.raise_()
                self._show(hit)
            if profile.id != dock.current_profile_id():
                dock.open_profile(profile.id, after=show)   # once its models are read
                return
        except Exception:                        # the store cannot be read just now
            return
        show()

    def _can_show(self) -> bool:
        """A ray is worth casting: the panel is shown with a profile open."""
        dock = self.dock
        return (not sip.isdeleted(dock) and dock.isVisible() and dock.provider is not None
                and dock.current_profile() is not None)

    def _show(self, hit) -> None:
        if sip.isdeleted(self.dock):
            return
        profile = self.dock.current_profile()
        at = None
        if hit is not None and profile is not None:
            p = hit.mapCoordinates()
            x, y = self._to_store(p.x(), p.y())
            at = None if x is None else section_point((x, y, p.z()), profile.chainage)
        if at is None:
            if not self._hold.isActive():
                self._hold.start()               # hide only if nothing is hit for a moment
            return
        self._hold.stop()
        self.dock.show_cursor(*at)
        self.dock.cursor_moved.emit(*at)         # the map's marker follows, as for the panel

    def holding(self) -> bool:
        """A miss is waiting to hide the cursor."""
        return self._hold.isActive()

    def hide_now(self) -> None:
        """Hide the section's cursor and the map's marker."""
        self._hold.stop()
        if sip.isdeleted(self.dock):
            return
        self.dock.show_cursor(None)
        self.dock.cursor_left.emit()

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
        self.on_opened = None
        self._poll.stop()
        self._cast.stop()
        self._hold.stop()
        for canvas in self._canvases:
            if not sip.isdeleted(canvas):
                canvas.removeEventFilter(self)
        self._canvases = []
