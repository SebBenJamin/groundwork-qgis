"""Stations in the 3D view: small spheres at their surveyed height, in the outline colour of
the stations' 2D symbol (its white fill would vanish against the 3D view's light sky);
a station without a height is left out; the 3D style is given once."""
import pytest


@pytest.fixture
def project(qgis_app):
    from qgis.core import QgsProject
    prj = QgsProject.instance()
    prj.clear()
    yield prj
    prj.removeAllMapLayers()
    prj.clear()


def _rule(layer):
    from qgis._3d import QgsRuleBased3DRenderer
    from qgis.PyQt import sip
    r3d = layer.renderer3D()
    assert r3d is not None and r3d.type() == "rulebased"
    return sip.cast(r3d, QgsRuleBased3DRenderer).rootRule().children()[0]


def test_new_stations_stand_at_their_height_in_their_2d_colour(project, store_with_model):
    from qgis._3d import QgsPoint3DSymbol
    from qgis.core import Qgis, QgsRenderContext
    from qgis.PyQt import sip

    from groundwork_geophysics.ui.project_actions import add_store_layers
    st, _p, _ = store_with_model
    stations = add_store_layers(st, project)["stations"]
    rule = _rule(stations)
    assert rule.filterExpression() == "z($geometry) IS NOT NULL"
    symbol = sip.cast(rule.symbol(), QgsPoint3DSymbol)
    assert symbol.altitudeClamping() == Qgis.AltitudeClamping.Absolute
    assert symbol.shape() == Qgis.Point3DShape.Sphere
    marker = stations.renderer().symbols(QgsRenderContext())[0].symbolLayer(0)
    assert symbol.materialSettings().diffuse().name() == marker.strokeColor().name()


def test_a_station_without_height_is_filtered_out(project, store_with_model):
    from qgis.core import QgsExpression, QgsExpressionContext, QgsFeature, QgsGeometry, QgsPoint

    from groundwork_geophysics.ui.project_actions import add_store_layers
    st, _p, _ = store_with_model
    rule = _rule(add_store_layers(st, project)["stations"])
    f = QgsFeature()
    f.setGeometry(QgsGeometry(QgsPoint(1.0, 2.0, float("nan"))))
    ctx = QgsExpressionContext()
    ctx.setFeature(f)
    assert not QgsExpression(rule.filterExpression()).evaluate(ctx)


def test_older_projects_get_it_once_and_a_removed_one_stays_removed(project, store_with_model):
    from groundwork_geophysics.ui.interp_layers import STYLED_3D
    from groundwork_geophysics.ui.project_actions import add_store_layers, ensure_station_3d
    st, _p, _ = store_with_model
    stations = add_store_layers(st, project)["stations"]
    stations.setRenderer3D(None)
    stations.removeCustomProperty(STYLED_3D)                  # as before 0.14
    assert ensure_station_3d(st, project) == 1 and stations.renderer3D() is not None
    stations.setRenderer3D(None)                              # the user's "No symbols"
    assert ensure_station_3d(st, project) == 0 and stations.renderer3D() is None


def test_the_sphere_size_follows_the_station_spacing(project, tmp_path):
    """Spheres 0.4 m across merged into one tube on 0.5 m electrode spacing: the radius is
    0.3 x the median spacing of neighbouring stations."""
    import numpy as np
    from qgis._3d import QgsPoint3DSymbol
    from qgis.PyQt import sip

    from groundwork_geophysics.core.model import profile_from_stations
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    from groundwork_geophysics.ui.project_actions import add_store_layers, station_radius
    st = ProjectStore.create(tmp_path / "s.gpkg", "EPSG:25832")
    xyz = np.column_stack([np.arange(11) * 0.5, np.zeros(11), np.full(11, 100.0)])
    p, s = profile_from_stations("P", "EPSG:25832", xyz)
    st.save_profile(p)
    st.save_station_set(s)
    assert station_radius(st) == pytest.approx(0.15)
    stations = add_store_layers(st, project)["stations"]
    symbol = sip.cast(_rule(stations).symbol(), QgsPoint3DSymbol)
    assert symbol.shapeProperties()["radius"] == pytest.approx(0.15)


def test_show_in_3d_fits_the_spheres_to_stations_imported_later(project, tmp_path):
    """A new project gets its stations layer before any data: Show in 3D fits the spheres
    to the stations then, but never changes a radius the user set."""
    import numpy as np
    from qgis._3d import QgsPoint3DSymbol
    from qgis.PyQt import sip

    from groundwork_geophysics.core.model import profile_from_stations
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    from groundwork_geophysics.ui.project_actions import (add_store_layers, fit_station_spheres,
                                                          style_stations_3d)
    st = ProjectStore.create(tmp_path / "s.gpkg", "EPSG:25832")
    stations = add_store_layers(st, project)["stations"]          # no stations yet: 0.4
    xyz = np.column_stack([np.arange(11) * 0.5, np.zeros(11), np.full(11, 100.0)])
    p, s = profile_from_stations("P", "EPSG:25832", xyz)
    st.save_profile(p)
    st.save_station_set(s)

    def radius():
        return sip.cast(_rule(stations).symbol(), QgsPoint3DSymbol).shapeProperties()["radius"]

    assert fit_station_spheres(st, project) and radius() == pytest.approx(0.15)
    style_stations_3d(stations, 1.0)
    stations.setCustomProperty("groundwork/station_radius", None)  # as the user's own style
    assert not fit_station_spheres(st, project) and radius() == pytest.approx(1.0)


def test_fitting_the_spheres_keeps_the_users_colour(project, tmp_path):
    import numpy as np
    from qgis._3d import (QgsPhongMaterialSettings, QgsPoint3DSymbol,
                          QgsRuleBased3DRenderer)
    from qgis.core import Qgis
    from qgis.PyQt import sip
    from qgis.PyQt.QtGui import QColor

    from groundwork_geophysics.core.model import profile_from_stations
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    from groundwork_geophysics.ui.project_actions import (HAS_HEIGHT, add_store_layers,
                                                          fit_station_spheres)
    st = ProjectStore.create(tmp_path / "s.gpkg", "EPSG:25832")
    stations = add_store_layers(st, project)["stations"]          # 0.4, no stations yet
    symbol = QgsPoint3DSymbol()                                   # the user's red, same size
    symbol.setShape(Qgis.Point3DShape.Sphere)
    symbol.setShapeProperties({"radius": 0.4})
    symbol.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
    material = QgsPhongMaterialSettings()
    material.setDiffuse(QColor("red"))
    symbol.setMaterialSettings(material)
    root = QgsRuleBased3DRenderer.Rule(None)
    root.appendChild(QgsRuleBased3DRenderer.Rule(symbol, HAS_HEIGHT, "mine"))
    stations.setRenderer3D(QgsRuleBased3DRenderer(root))
    xyz = np.column_stack([np.arange(11) * 0.5, np.zeros(11), np.full(11, 100.0)])
    p, s = profile_from_stations("P", "EPSG:25832", xyz)
    st.save_profile(p)
    st.save_station_set(s)
    assert fit_station_spheres(st, project)
    rule = _rule(stations)
    fitted = sip.cast(rule.symbol(), QgsPoint3DSymbol)
    assert fitted.shapeProperties()["radius"] == pytest.approx(0.15)
    assert fitted.materialSettings().diffuse().name() == QColor("red").name()
    assert rule.description() == "mine"
