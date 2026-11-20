"""Show in 3D… opens a ready 3D map view: when none is open, a new one with the terrain off
(the curtains hang below the ground surface, an opaque terrain hides them), eye-dome
lighting on (a point cloud looks flat without it) and the camera on what is shown. A view
the user already has open is left exactly as it is. Every step may fail on a QGIS that has
no 3D or a view that is not ready yet: what could be done is done, and the result says how
far it got, so the message can tell the user what is left to do by hand."""
from __future__ import annotations

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsMessageLog,
                       QgsPointXY, Qgis)

#: the new 3D map view's title
VIEW_NAME = "Groundwork 3D"
#: how the camera looks at the curtains: degrees from straight down (90 = from the side)
PITCH = 60.0
#: the camera stands this many times the size of what is shown away, at least MIN_DISTANCE m
DISTANCE_SHARE, MIN_DISTANCE = 1.3, 20.0
#: what open_ready_view did
ALREADY_OPEN, READY, OPENED = "open", "ready", "opened"


def _log(message: str) -> None:
    QgsMessageLog.logMessage(message, "Groundwork", Qgis.MessageLevel.Warning)


def views_open(iface) -> bool:
    """A QGIS 3D map view is open."""
    try:
        return bool(list(iface.mapCanvases3D()))
    except Exception:                            # no 3D in this QGIS
        return False


def open_ready_view(iface, project, box, crs_authid: str) -> str:
    """Open a new 3D map view, ready to look at the curtains, unless one is open already.

    ``box`` is (xmin, ymin, xmax, ymax, zmin, zmax) of what is shown, in ``crs_authid``, or
    ``None`` (the view keeps QGIS's own camera). Returns ``ALREADY_OPEN`` (nothing changed),
    ``READY`` (a new view, set up), ``OPENED`` (a new view, not all of it set up) or ""
    (no view could be opened)."""
    try:
        if list(iface.mapCanvases3D()):
            return ALREADY_OPEN
        canvas = iface.createNewMapCanvas3D(VIEW_NAME)
    except Exception as exc:                     # no 3D in this QGIS
        _log(f"3D view: no new 3D map view: {exc}")
        return ""
    if canvas is None:
        return ""
    ready = _tune(canvas)
    if box is not None:
        ready = _aim(canvas, project, box, crs_authid) and ready
    return READY if ready else OPENED


def _tune(canvas) -> bool:
    """Terrain off, eye-dome lighting on; False when either could not be set."""
    ok = True
    try:
        settings = canvas.mapSettings()
    except Exception as exc:
        _log(f"3D view: no settings: {exc}")
        return False
    if settings is None:
        return False
    for step in (lambda: settings.setTerrainRenderingEnabled(False),
                 lambda: settings.setEyeDomeLightingEnabled(True)):
        try:
            step()
        except Exception as exc:
            _log(f"3D view: a setting could not be made: {exc}")
            ok = False
    return ok


def _aim(canvas, project, box, crs_authid: str) -> bool:
    """Point the camera at the middle of ``box``, from far enough to see all of it, facing
    the long side (a profile running north is seen from the east or west)."""
    from qgis.core import QgsVector3D
    xmin, ymin, xmax, ymax, zmin, zmax = (float(v) for v in box)
    try:
        controller = canvas.cameraController()
        if controller is None:
            return False
        x, y = (xmin + xmax) / 2, (ymin + ymax) / 2
        src = QgsCoordinateReferenceSystem(crs_authid)
        dst = canvas.mapSettings().crs()
        if src.isValid() and dst.isValid() and src != dst:
            q = QgsCoordinateTransform(src, dst, project).transform(QgsPointXY(x, y))
            x, y = q.x(), q.y()
        width, height = xmax - xmin, ymax - ymin
        distance = max(DISTANCE_SHARE * max(width, height, zmax - zmin), MIN_DISTANCE)
        yaw = 0.0 if width >= height else 90.0
        controller.setLookingAtMapPoint(QgsVector3D(x, y, (zmin + zmax) / 2), distance,
                                        PITCH, yaw)
    except Exception as exc:                     # not ready, or outside the CRS' area
        _log(f"3D view: the camera could not be set: {exc}")
        return False
    return True
