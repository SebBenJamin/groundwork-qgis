"""Show in 3D… opens a ready 3D map view: when none is open, one the project has saved is
opened again (the plugin's own first, else the first listed), and only a project without any
gets a new one with the terrain off (the curtains hang below the ground surface, an opaque
terrain hides them), eye-dome lighting on (a point cloud looks flat without it) and the
camera on what is shown. A view the user already has, open or saved, is left exactly as it
is. Every step may fail on a QGIS that has
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
#: what look_at_profile did
LOOKED, CUT = "looked", "cut"
#: a cut along a profile is this wide on each side of the line beyond its bends:
#: a share of the profile's length, at least CUT_MARGIN_M
CUT_MARGIN_SHARE, CUT_MARGIN_M = 0.05, 5.0


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
        if list(iface.mapCanvases3D()) or _reopen_saved(iface):
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


#: QGIS's View → 3D Map Views menu; it lists the project's saved views above a separator
VIEWS_MENU = "m3DMapViewsMenu"


def _reopen_saved(iface) -> bool:
    """Open a 3D map view the project has saved (closed views stay in the project): the
    plugin's own, else the first listed. True when a 3D view is open afterwards. QGIS has no
    call for this, so the view's entry in View → 3D Map Views is triggered."""
    try:
        from qgis.PyQt.QtWidgets import QMenu
        menu = iface.mainWindow().findChild(QMenu, VIEWS_MENU)
        if menu is None:
            return False
        menu.aboutToShow.emit()                  # QGIS fills the menu when it is shown
        saved = []
        for action in menu.actions():
            if action.isSeparator():
                break
            saved.append(action)
        else:
            return False                         # no separator: not the list we know
        if not saved:
            return False
        mine = [a for a in saved if a.text().replace("&", "") == VIEW_NAME]
        (mine or saved)[0].trigger()
        return bool(list(iface.mapCanvases3D()))
    except Exception as exc:                     # no main window, or no 3D in this QGIS
        _log(f"3D view: a saved 3D map view could not be opened: {exc}")
        return False


def profile_section(canvas, project, profile, crs_authid: str):
    """QGIS's cross section along ``profile`` in ``canvas``'s map coordinates: from its first
    to its last point, wide enough for its bends plus a margin (``CUT_MARGIN_*``)."""
    import numpy as np
    from qgis._3d import QgsCrossSection
    from qgis.core import QgsPoint
    xy = np.asarray(profile.chainage.xy, float)
    a, b = xy[0], xy[-1]
    d = b - a
    length = float(np.hypot(*d)) or 1.0
    off = np.abs((xy[:, 0] - a[0]) * d[1] - (xy[:, 1] - a[1]) * d[0]) / length
    half = float(off.max()) + max(CUT_MARGIN_M, CUT_MARGIN_SHARE * profile.chainage.length)
    src = QgsCoordinateReferenceSystem(crs_authid)
    dst = canvas.mapSettings().crs()
    ends = [QgsPointXY(float(p[0]), float(p[1])) for p in (a, b)]
    if src.isValid() and dst.isValid() and src != dst:
        transform = QgsCoordinateTransform(src, dst, project)
        ends = [transform.transform(p) for p in ends]
    return QgsCrossSection(QgsPoint(ends[0].x(), ends[0].y()),
                           QgsPoint(ends[1].x(), ends[1].y()), half)


def _first_view(iface):
    try:
        views = list(iface.mapCanvases3D())
    except Exception:                            # no 3D in this QGIS
        return None
    return views[0] if views else None


def look_at_profile(iface, project, profile, crs_authid: str, cut: bool = False) -> str:
    """Turn the first open 3D map view's camera side-on to ``profile`` (QGIS's cross-section
    side view); with ``cut``, also clip the view to a slab along it, so the curtain shows
    through the terrain. ``LOOKED``, ``CUT``, or "" (no 3D view, or it failed: logged)."""
    canvas = _first_view(iface)
    if canvas is None:
        return ""
    try:
        section = profile_section(canvas, project, profile, crs_authid)
        if cut:
            canvas.setCrossSection(section)
        canvas.cameraController().setCrossSectionSideView(section)
    except Exception as exc:                     # not ready, or outside the CRS' area
        _log(f"3D view: the camera could not be turned to the profile: {exc}")
        return ""
    return CUT if cut else LOOKED


def cut_active(iface) -> bool:
    """An open 3D map view is clipped to a cross section."""
    try:
        return any(c.crossSectionEnabled() for c in iface.mapCanvases3D())
    except Exception:                            # no 3D in this QGIS
        return False


def remove_cuts(iface) -> int:
    """Take the cross-section clipping off every open 3D map view; how many had one."""
    from qgis._3d import QgsCrossSection
    removed = 0
    try:
        for canvas in iface.mapCanvases3D():
            if canvas.crossSectionEnabled():
                canvas.setCrossSection(QgsCrossSection())     # invalid: no clipping
                removed += 1
    except Exception as exc:                     # no 3D in this QGIS
        _log(f"3D view: the cut could not be removed: {exc}")
    return removed


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
