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
