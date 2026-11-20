"""Show in 3D… from the plugin: it opens a ready 3D map view when none is open, and the 3D
data (point clouds, pictures, cells) are only built while a 3D view is open or the user
presses OK; a sync asked for meanwhile waits for the next 3D view."""
import pytest


def _canvas():
    from qgis._3d import Qgs3DMapSettings
    from qgis.core import QgsCoordinateReferenceSystem
    from qgis.PyQt.QtGui import QWindow

    from tests.ui.test_view3d_view import _Controller

    class FakeCanvas(QWindow):                       # what the plugin needs of a 3D map view
        def __init__(self):
            super().__init__()
            self.settings = Qgs3DMapSettings()
            self.settings.setCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
            self.controller = _Controller()

        def mapSettings(self):
            return self.settings

        def cameraController(self):
            return self.controller
    return FakeCanvas()


@pytest.fixture
def plugin(qgis_app, fake_iface, store_with_model, monkeypatch):
    """(plugin with the store open, the iface, the 3D views list, sync calls)."""
    from qgis.core import QgsProject

    from groundwork_geophysics import classFactory
    from groundwork_geophysics.ui import view3d_layers
    from groundwork_geophysics.ui.view3d_layers import Choice, write_choice
    prj = QgsProject.instance()
    prj.clear()
    write_choice(prj, Choice(frozenset({"d1"})))
    views, calls = [], []
    real = view3d_layers.sync

    def counted(*args, **kwargs):
        calls.append(kwargs.get("create", False))
        return real(*args, **kwargs)
    monkeypatch.setattr(view3d_layers, "sync", counted)
    plug = classFactory(fake_iface)
    plug.initGui()
    shown = []
    monkeypatch.setattr(plug, "_info", shown.append)
    yield plug, fake_iface, views, calls, shown
    plug.unload()
    prj.removeAllMapLayers()
    prj.clear()


def _with_3d(iface, views, made=True):
    iface.mapCanvases3D = lambda: list(views)
    iface.made = []

    def create(name):
        canvas = _canvas()
        iface.made.append(canvas)
        views.append(canvas)
        return canvas
    if made:
        iface.createNewMapCanvas3D = create


def _press_ok(monkeypatch):
    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    monkeypatch.setattr(View3dDialog, "exec", lambda self: 1)
    monkeypatch.setattr(View3dDialog, "choice", lambda self: Choice(frozenset({"d1"})))


def test_show_in_3d_opens_a_ready_3d_view(plugin, store_with_model, monkeypatch):
    plug, iface, views, calls, shown = plugin
    _with_3d(iface, views)
    plug.set_store(store_with_model[0])
    _press_ok(monkeypatch)
    plug.show_in_3d()
    canvas, = iface.made
    assert not canvas.settings.terrainRenderingEnabled()
    assert canvas.settings.eyeDomeLightingEnabled() and canvas.controller.looks
    assert "new 3D map view" in shown[-1] and "New 3D Map View" not in shown[-1]
    assert plug.view3d_link._canvases == [canvas]    # the 3D mouse follows it at once


def test_an_open_3d_view_is_used_as_it_is(plugin, store_with_model, monkeypatch):
    plug, iface, views, calls, shown = plugin
    _with_3d(iface, views)
    mine = _canvas()
    mine.settings.setTerrainRenderingEnabled(True)
    views.append(mine)
    plug.set_store(store_with_model[0])
    _press_ok(monkeypatch)
    plug.show_in_3d()
    assert iface.made == [] and mine.settings.terrainRenderingEnabled()
    assert "open 3D map view" in shown[-1]


def test_without_3d_views_the_message_says_how_to_open_one(plugin, store_with_model,
                                                          monkeypatch):
    plug, iface, views, calls, shown = plugin
    plug.set_store(store_with_model[0])              # a QGIS without 3D map views
    _press_ok(monkeypatch)
    plug.show_in_3d()
    assert calls == [True]                           # OK always builds
    assert "View → 3D Map Views → New 3D Map View" in shown[-1]


def test_nothing_is_built_until_a_3d_view_opens(plugin, store_with_model):
    plug, iface, views, calls, shown = plugin
    _with_3d(iface, views, made=False)
    plug.set_store(store_with_model[0])
    plug._sync_3d()                                  # a style change, once things settle
    assert calls == []
    views.append(_canvas())
    plug.view3d_link.poll()                          # the link sees the new 3D view
    assert calls == [False]
    plug.view3d_link.poll()                          # nothing more is waiting
    plug._sync_3d()                                  # with a view open, at once
    assert calls == [False, False]


def test_a_project_opened_with_a_3d_view_open_is_filled(plugin, store_with_model):
    plug, iface, views, calls, shown = plugin
    _with_3d(iface, views, made=False)
    views.append(_canvas())
    plug.set_store(store_with_model[0])
    assert calls == [False]


def test_ok_sizes_the_station_spheres_as_chosen(plugin, store_with_model, monkeypatch):
    from qgis._3d import QgsPoint3DSymbol, QgsRuleBased3DRenderer
    from qgis.core import QgsProject
    from qgis.PyQt import sip

    from groundwork_geophysics.ui.project_actions import add_store_layers
    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    plug, iface, views, calls, shown = plugin
    st = store_with_model[0]
    stations = add_store_layers(st, QgsProject.instance())["stations"]
    plug.set_store(st)
    monkeypatch.setattr(View3dDialog, "exec", lambda self: 1)
    monkeypatch.setattr(View3dDialog, "choice",
                        lambda self: Choice(frozenset({"d1"}), station_size=0.5))
    plug.show_in_3d()
    rule = sip.cast(stations.renderer3D(), QgsRuleBased3DRenderer).rootRule().children()[0]
    assert sip.cast(rule.symbol(), QgsPoint3DSymbol).shapeProperties()["radius"] == \
        pytest.approx(0.25)


def test_ok_restyles_the_interpretation_from_2d_when_ticked(plugin, store_with_model,
                                                           monkeypatch):
    from groundwork_geophysics.ui import interp_layers
    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    plug, iface, views, calls, shown = plugin
    plug.set_store(store_with_model[0])
    restyled = []
    monkeypatch.setattr(interp_layers, "restyle_from_2d",
                        lambda store, project: restyled.append(store) or 3)
    _press_ok(monkeypatch)
    plug.show_in_3d()
    assert restyled == []
    monkeypatch.setattr(View3dDialog, "restyle_interpretation", lambda self: True)
    plug.show_in_3d()
    assert restyled == [store_with_model[0]] and "follows its 2D style" in shown[-1]
