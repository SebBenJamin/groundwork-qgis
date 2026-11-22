"""Show in 3D… opens a ready 3D map view: when none is open, a new one with the terrain off,
eye-dome lighting on and the camera on what is shown; an open one is left as it is; any
failure leaves the user with the hint to open one by hand."""
import pytest


class _Controller:
    def __init__(self):
        self.looks = []
        self.sides = []

    def setLookingAtMapPoint(self, point, distance, pitch, yaw):
        self.looks.append(((point.x(), point.y(), point.z()), distance, pitch, yaw))

    def setCrossSectionSideView(self, section):
        self.sides.append(section)


class _Canvas:
    def __init__(self, controller=True):
        from qgis._3d import Qgs3DMapSettings
        from qgis.core import QgsCoordinateReferenceSystem
        self.settings = Qgs3DMapSettings()
        self.settings.setCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
        self.controller = _Controller() if controller else None
        self.section = None

    def mapSettings(self):
        return self.settings

    def setCrossSection(self, section):
        self.section = section if section.isValid() else None

    def crossSectionEnabled(self):
        return self.section is not None

    def cameraController(self):
        return self.controller


class _Iface:
    def __init__(self, open_views=(), made=None):
        self.views, self.made, self.names = list(open_views), made, []

    def mapCanvases3D(self):
        return list(self.views)

    def createNewMapCanvas3D(self, name):
        self.names.append(name)
        if isinstance(self.made, Exception):
            raise self.made
        if self.made is not None:
            self.views.append(self.made)
        return self.made


BOX = (0.0, -2.0, 60.0, 2.0, 80.0, 100.0)          # x, y, x, y, z, z in the store's CRS


def test_without_a_3d_view_a_ready_one_opens(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_view import READY, open_ready_view
    canvas = _Canvas()
    canvas.settings.setTerrainRenderingEnabled(True)
    iface = _Iface(made=canvas)
    assert open_ready_view(iface, QgsProject.instance(), BOX, "EPSG:25832") == READY
    assert len(iface.names) == 1 and iface.names[0]
    assert not canvas.settings.terrainRenderingEnabled()
    assert canvas.settings.eyeDomeLightingEnabled()
    (centre, distance, pitch, yaw), = canvas.controller.looks
    assert centre == pytest.approx((30.0, 0.0, 90.0))
    assert distance >= 60.0 and 0.0 < pitch < 90.0


def test_a_profile_running_north_is_seen_from_the_side(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_view import open_ready_view
    east, north = _Canvas(), _Canvas()
    open_ready_view(_Iface(made=east), QgsProject.instance(), BOX, "EPSG:25832")
    open_ready_view(_Iface(made=north), QgsProject.instance(),
                    (-2.0, 0.0, 2.0, 60.0, 80.0, 100.0), "EPSG:25832")
    yaw_east, yaw_north = east.controller.looks[0][3], north.controller.looks[0][3]
    assert abs(yaw_east - yaw_north) == pytest.approx(90.0)


def test_an_open_3d_view_is_left_as_it_is(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_view import ALREADY_OPEN, open_ready_view
    canvas = _Canvas()
    canvas.settings.setTerrainRenderingEnabled(True)
    iface = _Iface(open_views=[canvas], made=_Canvas())
    assert open_ready_view(iface, QgsProject.instance(), BOX, "EPSG:25832") == ALREADY_OPEN
    assert iface.names == [] and canvas.settings.terrainRenderingEnabled()
    assert not canvas.settings.eyeDomeLightingEnabled() and canvas.controller.looks == []


@pytest.mark.parametrize("made", [None, RuntimeError("no 3D")])
def test_a_view_that_cannot_be_made_gives_nothing(qgis_app, made):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_view import open_ready_view
    assert open_ready_view(_Iface(made=made), QgsProject.instance(), BOX, "EPSG:25832") == ""


def test_a_qgis_without_3d_views_gives_nothing(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_view import open_ready_view, views_open
    assert open_ready_view(object(), QgsProject.instance(), BOX, "EPSG:25832") == ""
    assert not views_open(object())


def test_a_view_opened_but_not_tuned_says_so(qgis_app):
    """A view without a camera yet (or settings that refuse) is open but not ready."""
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_view import OPENED, open_ready_view
    canvas = _Canvas(controller=False)
    assert open_ready_view(_Iface(made=canvas), QgsProject.instance(), BOX,
                           "EPSG:25832") == OPENED
    assert not canvas.settings.terrainRenderingEnabled()     # what could be done, was


def _bent():
    import numpy as np

    from groundwork_geophysics.core.model import profile_from_polyline
    return profile_from_polyline("P1", "EPSG:25832",
                                 np.array([[0.0, 0.0], [50.0, 4.0], [100.0, 0.0]]))


def test_the_section_of_a_profile_spans_its_ends_and_its_bends(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_view import profile_section
    section = profile_section(_Canvas(), QgsProject.instance(), _bent(), "EPSG:25832")
    a, b = section.startPoint(), section.endPoint()
    assert (a.x(), a.y(), b.x(), b.y()) == pytest.approx((0.0, 0.0, 100.0, 0.0))
    assert section.halfWidth() > 4.0                # the bend 4 m off the chord is inside


def test_looking_at_a_profile_turns_the_camera_side_on_without_a_cut(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_view import LOOKED, look_at_profile
    canvas = _Canvas()
    iface = _Iface(open_views=[canvas])
    assert look_at_profile(iface, QgsProject.instance(), _bent(), "EPSG:25832") == LOOKED
    assert len(canvas.controller.sides) == 1 and canvas.section is None


def test_cutting_along_a_profile_clips_the_view_and_removing_undoes_it(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_view import (CUT, cut_active, look_at_profile,
                                                      remove_cuts)
    canvas = _Canvas()
    iface = _Iface(open_views=[canvas])
    assert not cut_active(iface)
    assert look_at_profile(iface, QgsProject.instance(), _bent(), "EPSG:25832", cut=True) == CUT
    assert canvas.section is not None and len(canvas.controller.sides) == 1
    assert cut_active(iface)
    assert remove_cuts(iface) == 1 and canvas.section is None and not cut_active(iface)


def test_without_a_3d_view_looking_gives_nothing(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_view import look_at_profile
    assert look_at_profile(_Iface(), QgsProject.instance(), _bent(), "EPSG:25832") == ""
    assert look_at_profile(object(), QgsProject.instance(), _bent(), "EPSG:25832") == ""


def test_without_anything_to_aim_at_the_view_keeps_its_own_camera(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_view import READY, open_ready_view
    canvas = _Canvas()
    assert open_ready_view(_Iface(made=canvas), QgsProject.instance(), None,
                           "EPSG:25832") == READY
    assert canvas.controller.looks == [] and canvas.settings.eyeDomeLightingEnabled()
