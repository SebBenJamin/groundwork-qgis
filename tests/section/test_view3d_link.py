"""The 3D view's mouse moves the section's cursor: a curtain hit under the mouse in a QGIS 3D
map view becomes chainage and elevation on the open profile."""
import numpy as np
import pytest

from groundwork_geophysics.core.chainage import Chainage


def test_a_point_on_the_line_gives_chainage_and_elevation():
    from groundwork_geophysics.section.view3d_link import section_point
    line = Chainage(np.array([[0.0, 0.0], [50.0, 0.0]]))
    assert section_point((10.0, 0.2, 97.5), line) == pytest.approx((10.0, 97.5))


def test_a_point_off_the_line_or_beyond_its_ends_gives_nothing():
    from groundwork_geophysics.section.view3d_link import section_point
    line = Chainage(np.array([[0.0, 0.0], [50.0, 0.0]]))
    assert section_point((10.0, 3.0, 97.5), line) is None       # 3 m away, 1 m allowed
    assert section_point((60.0, 0.0, 97.5), line) is None       # past the end


def test_the_dock_shows_the_elevation_on_its_guide(qgis_app, store_with_model, make_dock):
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    dock.show_cursor(25.0, 99.0)
    assert dock.cursor_chainage() == 25.0
    assert dock.cursor_marker.isVisible()
    assert "z = 99" in dock.readout.text()
    dock.show_cursor(25.0)                          # the map's hover: no elevation
    assert not dock.cursor_marker.isVisible()
    dock.show_cursor(None)
    assert not dock.cursor_marker.isVisible() and dock.cursor_chainage() is None


class _Hit:
    def __init__(self, xyz, distance):
        from qgis.core import QgsVector3D
        self._p, self._d = QgsVector3D(*xyz), distance

    def mapCoordinates(self):
        return self._p

    def distance(self):
        return self._d


class _Result:
    def __init__(self, hits):
        self._hits = hits

    def allHits(self):
        return self._hits


def _canvas(hits):
    from qgis.PyQt.QtGui import QWindow

    class FakeCanvas(QWindow):                       # what castRay needs of a 3D map view
        contexts = []

        def castRay(self, point, context):
            self.contexts.append(context)
            return _Result(hits)
    return FakeCanvas()


def _move(canvas, held=False):
    from qgis.PyQt.QtCore import QCoreApplication, QEvent, QPointF, Qt
    from qgis.PyQt.QtGui import QMouseEvent
    buttons = Qt.MouseButton.LeftButton if held else Qt.MouseButton.NoButton
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(5, 5), QPointF(5, 5),
                        Qt.MouseButton.NoButton, buttons, Qt.KeyboardModifier.NoModifier)
    QCoreApplication.sendEvent(canvas, event)


def test_the_mouse_over_a_curtain_moves_the_section_cursor(qgis_app, store_with_model,
                                                           make_dock):
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from groundwork_geophysics.section.view3d_link import View3dLink
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    x, y = (float(v) for v in p.chainage.to_xy(20.0))
    near, far = _Hit((x, y, 98.0), 5.0), _Hit((x, y, 90.0), 9.0)
    canvas = _canvas([far, near])

    class Iface:
        def mapCanvases3D(self):
            return [canvas]
    link = View3dLink(Iface(), dock)
    link.poll()                                      # picks up the open 3D view
    _move(canvas)
    link.cast_now()                                  # the throttled ray, at once
    assert dock.cursor_chainage() == pytest.approx(20.0, abs=1e-6)
    assert "z = 98" in dock.readout.text()           # the nearest hit
    QCoreApplication.sendEvent(canvas, QEvent(QEvent.Type.Leave))
    assert dock.cursor_chainage() is None
    link.unload()


def test_without_a_hit_on_the_open_profile_the_cursor_hides(qgis_app, store_with_model,
                                                            make_dock):
    from groundwork_geophysics.section.view3d_link import View3dLink
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    dock.show_cursor(10.0, 99.0)
    canvas = _canvas([_Hit((1000.0, 1000.0, 98.0), 5.0)])      # another profile's curtain

    class Iface:
        def mapCanvases3D(self):
            return [canvas]
    link = View3dLink(Iface(), dock)
    link.poll()
    _move(canvas)
    link.cast_now()
    # a miss is held a moment (a ray slipping between a cloud's points must not blink the
    # cursor off), then the cursor hides
    assert dock.cursor_chainage() == 10.0 and link.holding()
    link.hide_now()
    assert dock.cursor_chainage() is None
    link.unload()


def test_a_hit_after_a_short_miss_keeps_the_cursor_steady(qgis_app, store_with_model,
                                                          make_dock):
    from groundwork_geophysics.section.view3d_link import View3dLink
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    x, y = (float(v) for v in p.chainage.to_xy(20.0))
    hits = [_Hit((x, y, 98.0), 5.0)]
    canvas = _canvas(hits)
    link = View3dLink(_iface(canvas), dock)
    link.poll()
    _move(canvas)
    link.cast_now()
    hits.clear()                                     # the ray slips between points
    _move(canvas)
    link.cast_now()
    hits.append(_Hit((x, y, 97.0), 5.0))
    _move(canvas)
    link.cast_now()
    assert not link.holding() and dock.cursor_chainage() == pytest.approx(20.0, abs=1e-6)
    link.unload()


def test_the_map_marker_follows_the_3d_pointer(qgis_app, store_with_model, make_dock_and_link):
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from groundwork_geophysics.section.view3d_link import View3dLink
    st, p, _ = store_with_model
    dock, map_link = make_dock_and_link(st)
    dock.open_profile(p.id)
    x, y = (float(v) for v in p.chainage.to_xy(20.0))
    canvas = _canvas([_Hit((x, y, 98.0), 5.0)])
    link = View3dLink(_iface(canvas), dock)
    link.poll()
    _move(canvas)
    link.cast_now()
    c = map_link.marker.center()
    assert map_link.marker.isVisible() and (c.x(), c.y()) == pytest.approx((x, y))
    QCoreApplication.sendEvent(canvas, QEvent(QEvent.Type.Leave))
    assert not map_link.marker.isVisible()
    link.unload()


def test_a_qgis_without_3d_views_is_fine(qgis_app, store_with_model, make_dock):
    from groundwork_geophysics.section.view3d_link import View3dLink
    st, _p, _ = store_with_model
    link = View3dLink(object(), make_dock(st))       # an iface without mapCanvases3D
    link.poll()
    link.unload()


def _iface(canvas):
    class Iface:
        def mapCanvases3D(self):
            return [canvas]
    return Iface()


def test_rays_find_point_clouds_too(qgis_app, store_with_model, make_dock):
    """QGIS skips every point of a cloud with the default angle tolerance (0); its own
    identify tool uses half a degree."""
    from groundwork_geophysics.section.view3d_link import View3dLink
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    canvas = _canvas([])
    link = View3dLink(_iface(canvas), dock)
    link.poll()
    _move(canvas)
    link.cast_now()
    assert canvas.contexts and canvas.contexts[-1].angleThreshold() == pytest.approx(0.5)
    link.unload()


def test_no_rays_while_nothing_can_be_shown(qgis_app, store_with_model, make_dock):
    """Rays cost the 3D view time: none while the panel is hidden or has no profile open,
    and none while a button is held (the user turns or pans the 3D view)."""
    from groundwork_geophysics.section.view3d_link import View3dLink
    st, p, _ = store_with_model
    dock = make_dock(st)
    canvas = _canvas([])
    link = View3dLink(_iface(canvas), dock)
    link.poll()
    _move(canvas)                                    # no profile open
    link.cast_now()
    dock.open_profile(p.id)
    _move(canvas, held=True)                         # turning the view
    link.cast_now()
    dock.hide()
    _move(canvas)                                    # the panel is hidden
    link.cast_now()
    assert canvas.contexts == []
    link.unload()


def _click(canvas, at=(5, 5), to=None, button=None):
    """Press and release the left button (``to``: released elsewhere, after a drag).
    Returns what the event filters answered for the release (False: QGIS handles it)."""
    from qgis.PyQt.QtCore import QCoreApplication, QEvent, QPointF, Qt
    from qgis.PyQt.QtGui import QMouseEvent
    left = button or Qt.MouseButton.LeftButton
    to = to or at
    for etype, (x, y), held in ((QEvent.Type.MouseButtonPress, at, left),
                                (QEvent.Type.MouseMove, to, left),
                                (QEvent.Type.MouseButtonRelease, to, Qt.MouseButton.NoButton)):
        event = QMouseEvent(etype, QPointF(x, y), QPointF(x, y),
                            Qt.MouseButton.NoButton if etype == QEvent.Type.MouseMove else left,
                            held, Qt.KeyboardModifier.NoModifier)
        QCoreApplication.sendEvent(canvas, event)
    return event


@pytest.fixture
def two_profiles(store_with_model):
    """The store with a second profile, P2, 100 m north of P1 and parallel to it."""
    from groundwork_geophysics.core.model import profile_from_polyline
    st, p, _ = store_with_model
    p2 = profile_from_polyline("P2", "EPSG:25832", np.array([[0.0, 100.0], [50.0, 100.0]]))
    st.save_profile(p2)
    return st, p, p2


def test_a_click_on_another_curtain_opens_its_profile(qgis_app, two_profiles, make_dock):
    from groundwork_geophysics.section.view3d_link import View3dLink
    st, p1, p2 = two_profiles
    dock = make_dock(st)
    dock.open_profile(p1.id)
    canvas = _canvas([_Hit((20.0, 100.3, 97.0), 5.0), _Hit((20.0, 0.0, 97.0), 50.0)])
    link = View3dLink(_iface(canvas), dock)
    link.poll()
    _move(canvas)                                    # hovering never switches
    link.cast_now()
    assert dock.current_profile_id() == p1.id
    _click(canvas)
    assert dock.current_profile_id() == p2.id        # the nearest hit's profile
    assert dock.cursor_chainage() == pytest.approx(20.0, abs=1e-6)
    link.unload()


def test_a_drag_or_another_button_does_not_switch(qgis_app, two_profiles, make_dock):
    from qgis.PyQt.QtCore import Qt

    from groundwork_geophysics.section.view3d_link import View3dLink
    st, p1, _p2 = two_profiles
    dock = make_dock(st)
    dock.open_profile(p1.id)
    canvas = _canvas([_Hit((20.0, 100.0, 97.0), 5.0)])
    link = View3dLink(_iface(canvas), dock)
    link.poll()
    _click(canvas, at=(5, 5), to=(30, 5))           # turning the view
    _click(canvas, button=Qt.MouseButton.RightButton)
    assert dock.current_profile_id() == p1.id
    _click(canvas, at=(5, 5), to=(8, 7))             # a hand that shakes a little
    assert dock.current_profile_id() != p1.id
    link.unload()


def test_a_click_opens_the_panel_hidden_or_empty(qgis_app, two_profiles, make_dock):
    from groundwork_geophysics.section.view3d_link import View3dLink
    st, _p1, p2 = two_profiles
    dock = make_dock(st)
    dock.hide()                                      # hidden, no profile open
    canvas = _canvas([_Hit((20.0, 100.0, 97.0), 5.0)])
    link = View3dLink(_iface(canvas), dock)
    link.poll()
    _click(canvas)
    assert dock.current_profile_id() == p2.id and dock.isVisible()
    link.unload()


def test_a_click_off_every_profile_or_without_a_project_changes_nothing(
        qgis_app, two_profiles, make_dock):
    from groundwork_geophysics.section.view3d_link import View3dLink
    st, p1, _p2 = two_profiles
    dock = make_dock(st)
    dock.open_profile(p1.id)
    canvas = _canvas([_Hit((20.0, 50.0, 97.0), 5.0)])          # between the two lines
    link = View3dLink(_iface(canvas), dock)
    link.poll()
    _click(canvas)
    assert dock.current_profile_id() == p1.id
    dock.set_provider(None)
    canvas.contexts.clear()
    _click(canvas)
    assert canvas.contexts == []                     # no project: no ray
    link.unload()


def test_the_click_goes_on_to_qgis(qgis_app, two_profiles, make_dock):
    from qgis.PyQt.QtCore import QEvent, QPointF, Qt
    from qgis.PyQt.QtGui import QMouseEvent

    from groundwork_geophysics.section.view3d_link import View3dLink
    st, p1, _p2 = two_profiles
    dock = make_dock(st)
    canvas = _canvas([_Hit((20.0, 100.0, 97.0), 5.0)])
    link = View3dLink(_iface(canvas), dock)
    link.poll()
    left = Qt.MouseButton.LeftButton
    for etype, held in ((QEvent.Type.MouseButtonPress, left),
                        (QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton)):
        event = QMouseEvent(etype, QPointF(5, 5), QPointF(5, 5), left, held,
                            Qt.KeyboardModifier.NoModifier)
        assert link.eventFilter(canvas, event) is False
    link.unload()


def test_a_newly_seen_3d_view_is_announced_once(qgis_app, store_with_model, make_dock):
    from groundwork_geophysics.section.view3d_link import View3dLink
    st, _p, _ = store_with_model
    canvases, seen = [], []

    class Iface:
        def mapCanvases3D(self):
            return list(canvases)
    link = View3dLink(Iface(), make_dock(st))
    link.on_opened = lambda: seen.append(1)
    link.poll()
    assert seen == []
    canvases.append(_canvas([]))
    link.poll()
    link.poll()
    assert seen == [1]
    link.unload()
