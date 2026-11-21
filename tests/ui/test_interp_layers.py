"""Interpretation layers in the QGIS project: added once, styled, kept in step with edits."""
import numpy as np
import pytest

from groundwork_geophysics.core.chainage import Chainage
from groundwork_geophysics.core.interpretation import InterpFeature, InterpPiece, new_id

BENT = Chainage(np.array([[0.0, 0.0], [50.0, 0.0], [50.0, 50.0]]))


@pytest.fixture
def interp_store(tmp_path):
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    st = ProjectStore.create(tmp_path / "wb.gpkg", "EPSG:25832")
    st.ensure_interpretation()
    v = st.current_version()
    f = InterpFeature(new_id(), v.id, type="anomaly", name="A")
    st.save_feature(f)
    st.save_piece(InterpPiece(new_id(), v.id, f.id, "prof", "polygon",
                              [(40, 0), (60, 0), (60, -5), (40, -5)]))
    st.rebuild_derived(v.id, {"prof": BENT})
    return st


def test_add_interp_layers_once(qgis_app, interp_store):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.interp_layers import INTERP_GROUP, add_interp_layers

    prj = QgsProject()
    a = add_interp_layers(interp_store, prj)
    b = add_interp_layers(interp_store, prj)
    assert set(a) == set(b) and len(a) == 5 and len(prj.mapLayers()) == 5
    group = prj.layerTreeRoot().findGroup(INTERP_GROUP)
    assert group is not None and len(group.findLayers()) == 5
    assert not a["interp_features"].readOnly()
    assert all(a[n].readOnly() for n in a if n != "interp_features")
    prj.clear()


def test_interp_layers_are_not_crossing_line_candidates(qgis_app, interp_store):
    from qgis.core import QgsProject

    from groundwork_geophysics.section.crossing_lines import own_layer_ids
    from groundwork_geophysics.ui.interp_layers import add_interp_layers

    prj = QgsProject()
    layers = add_interp_layers(interp_store, prj)
    own = own_layer_ids(interp_store, prj)
    assert layers["interp_lines_3d"].id() in own and layers["interp_footprints"].id() in own
    prj.clear()


def test_style_groups_by_entity_with_confidence_line_style(qgis_app, interp_store):
    from qgis.core import QgsProject, QgsSymbolLayer

    from groundwork_geophysics.core.interpretation import InterpFeature, InterpPiece, new_id
    from groundwork_geophysics.ui.interp_layers import add_interp_layers, reload_interp_layers

    prj = QgsProject()
    polys = add_interp_layers(interp_store, prj)["interp_polygons_3d"]
    r = polys.renderer()
    assert r.classAttribute() == "feature_id"
    assert [c.label() for c in r.categories()] == ["A · anomaly"]
    cats = r.categories()                         # keep the copies alive while reading them
    sym = cats[0].symbol()
    prop = sym.symbolLayer(0).dataDefinedProperties().property(
        QgsSymbolLayer.Property.StrokeStyle)
    assert "confidence" in prop.expressionString()
    v = interp_store.current_version()
    f = InterpFeature(new_id(), v.id, type="clay lens", name="B")
    interp_store.save_feature(f)
    interp_store.save_piece(InterpPiece(new_id(), v.id, f.id, "prof", "polygon",
                                        [(0, 0), (5, 0), (5, -2)]))
    reload_interp_layers(interp_store, prj)
    assert sorted(c.label() for c in polys.renderer().categories()) == [
        "A · anomaly", "B · clay lens"]
    interp_store.delete_feature(f.id)
    reload_interp_layers(interp_store, prj)
    assert [c.label() for c in polys.renderer().categories()] == ["A · anomaly"]
    prj.clear()


def test_feature_edit_rebuilds_derived(qgis_app, interp_store):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.interp_layers import InterpSync, add_interp_layers

    prj = QgsProject()
    layers = add_interp_layers(interp_store, prj)
    calls = []
    sync = InterpSync(interp_store, prj, lambda: calls.append(1),
                      version_id=lambda: interp_store.current_version().id,
                      chainages=lambda: {"prof": BENT})
    feats = layers["interp_features"]
    feats.startEditing()
    f = next(feats.getFeatures())
    feats.changeAttributeValue(f.id(), feats.fields().indexOf("name"), "Q")
    assert feats.commitChanges()
    poly = layers["interp_polygons_3d"]
    assert [g["name"] for g in poly.getFeatures()] == ["Q"]
    assert calls == [1]
    sync.detach()
    prj.clear()


def test_features_layer_hides_frozen_versions(qgis_app, interp_store):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.interp_layers import add_interp_layers

    interp_store.freeze_current("R1")                      # a second copy of every feature
    prj = QgsProject()
    feats = add_interp_layers(interp_store, prj)["interp_features"]
    cur = interp_store.current_version().id
    assert [f["version_id"] for f in feats.getFeatures()] == [cur]
    prj.clear()


def test_feature_deleted_in_table_removes_its_pieces(qgis_app, interp_store):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.interp_layers import InterpSync, add_interp_layers

    prj = QgsProject()
    layers = add_interp_layers(interp_store, prj)
    sync = InterpSync(interp_store, prj, lambda: None,
                      version_id=lambda: interp_store.current_version().id,
                      chainages=lambda: {"prof": BENT})
    feats = layers["interp_features"]
    feats.startEditing()
    feats.deleteFeature(next(feats.getFeatures()).id())
    assert feats.commitChanges()
    assert interp_store.pieces(interp_store.current_version().id) == []
    assert layers["interp_polygons_3d"].featureCount() == 0
    sync.detach()
    prj.clear()


def test_layers_panel_legend_lists_a_new_entity(qgis_app, interp_store):
    # a new entity must show up under the layer in the Layers panel, not only in the renderer
    from qgis.core import QgsLayerTreeModel, QgsProject

    from groundwork_geophysics.ui.interp_layers import add_interp_layers, reload_interp_layers

    prj = QgsProject()
    polys = add_interp_layers(interp_store, prj)["interp_polygons_3d"]
    model = QgsLayerTreeModel(prj.layerTreeRoot())
    node = prj.layerTreeRoot().findLayer(polys.id())

    def legend_labels():
        return sorted(n.data(0) for n in model.layerLegendNodes(node))

    assert legend_labels() == ["A · anomaly"]
    v = interp_store.current_version()
    f = InterpFeature(new_id(), v.id, type="geology", name="B")
    interp_store.save_feature(f)
    interp_store.save_piece(InterpPiece(new_id(), v.id, f.id, "prof", "polygon",
                                        [(0, 0), (5, 0), (5, -2)]))
    reload_interp_layers(interp_store, prj)
    assert legend_labels() == ["A · anomaly", "B · geology"]
    prj.clear()


def _colour_3d(symbol):
    from qgis._3d import QgsPolygon3DSymbol
    from qgis.PyQt import sip
    c = sip.cast(symbol, QgsPolygon3DSymbol).materialSettings().diffuse()
    return c.red(), c.green(), c.blue()


def test_the_3d_layers_get_one_3d_category_per_entity_in_its_2d_colour(qgis_app, interp_store):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.interp_layers import add_interp_layers

    prj = QgsProject()
    layers = add_interp_layers(interp_store, prj)
    for name in ("interp_lines_3d", "interp_polygons_3d", "interp_points_3d"):
        r3d = layers[name].renderer3D()
        assert r3d is not None and r3d.type() == "categorized", name
        assert r3d.classAttribute() == "feature_id"
    polys = layers["interp_polygons_3d"]
    cats2d, cats3d = polys.renderer().categories(), polys.renderer3D().categories()
    assert [c.value() for c in cats3d] == [c.value() for c in cats2d]
    c2 = cats2d[0].symbol().color()
    assert _colour_3d(cats3d[0].symbol()) == (c2.red(), c2.green(), c2.blue())
    assert layers["interp_footprints"].renderer3D() is None
    prj.clear()


def test_a_new_entity_gets_its_3d_category_and_a_deleted_one_loses_it(qgis_app, interp_store):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.interp_layers import add_interp_layers, reload_interp_layers

    prj = QgsProject()
    polys = add_interp_layers(interp_store, prj)["interp_polygons_3d"]
    v = interp_store.current_version()
    f = InterpFeature(new_id(), v.id, type="clay lens", name="B")
    interp_store.save_feature(f)
    interp_store.save_piece(InterpPiece(new_id(), v.id, f.id, "prof", "polygon",
                                        [(0, 0), (5, 0), (5, -2)]))
    reload_interp_layers(interp_store, prj)
    assert len(polys.renderer3D().categories()) == 2
    interp_store.delete_feature(f.id)
    reload_interp_layers(interp_store, prj)
    assert [c.value() for c in polys.renderer3D().categories()] == [
        c.value() for c in polys.renderer().categories()]
    prj.clear()


def test_older_projects_get_the_3d_style_once_and_a_users_own_is_kept(qgis_app, interp_store):
    from qgis._3d import QgsLine3DSymbol, QgsVectorLayer3DRenderer
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.interp_layers import add_interp_layers, ensure_3d_styles

    prj = QgsProject()
    layers = add_interp_layers(interp_store, prj)
    from groundwork_geophysics.ui.interp_layers import STYLED_3D
    layers["interp_polygons_3d"].setRenderer3D(None)                 # as before 0.14
    layers["interp_polygons_3d"].removeCustomProperty(STYLED_3D)
    own = QgsVectorLayer3DRenderer(QgsLine3DSymbol())
    layers["interp_lines_3d"].setRenderer3D(own)                     # the user's
    assert ensure_3d_styles(interp_store, prj) == 1
    assert layers["interp_polygons_3d"].renderer3D().type() == "categorized"
    assert layers["interp_lines_3d"].renderer3D().type() == "vector"
    assert ensure_3d_styles(interp_store, prj) == 0
    prj.clear()


def test_a_3d_style_the_user_removed_stays_removed(qgis_app, interp_store):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.interp_layers import add_interp_layers, ensure_3d_styles

    prj = QgsProject()
    layers = add_interp_layers(interp_store, prj)
    layers["interp_lines_3d"].setRenderer3D(None)                    # "No symbols"
    assert ensure_3d_styles(interp_store, prj) == 0
    assert layers["interp_lines_3d"].renderer3D() is None
    prj.clear()


def test_without_qgis_3d_the_layers_still_open(qgis_app, interp_store, monkeypatch):
    import sys

    from qgis.core import QgsProject

    from groundwork_geophysics.ui.interp_layers import add_interp_layers, ensure_3d_styles

    monkeypatch.setitem(sys.modules, "qgis._3d", None)               # a build without 3D
    prj = QgsProject()
    layers = add_interp_layers(interp_store, prj)
    assert len(layers) == 5 and layers["interp_lines_3d"].renderer3D() is None
    assert ensure_3d_styles(interp_store, prj) == 0
    prj.clear()


def test_interpretation_lines_keep_their_heights_in_3d(qgis_app, interp_store):
    """A buffered 3D line lies flat at height 0; simple lines keep the drawn depth."""
    from qgis._3d import QgsLine3DSymbol
    from qgis.core import QgsWkbTypes
    from qgis.PyQt import sip

    from groundwork_geophysics.ui.interp_layers import _symbol_3d
    symbol = sip.cast(_symbol_3d(QgsWkbTypes.GeometryType.LineGeometry, (10, 20, 30)),
                      QgsLine3DSymbol)
    assert symbol.renderAsSimpleLines()
    material = symbol.materialSettings()
    assert material.type() == "simpleline"
    c = material.ambient()
    assert (c.red(), c.green(), c.blue()) == (10, 20, 30)


# -- the 3D interpretation carries its 2D style as far as QGIS 3D can --------------------------
def _poly_layer(interp_store):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.interp_layers import add_interp_layers
    prj = QgsProject()
    return prj, add_interp_layers(interp_store, prj)["interp_polygons_3d"]


def _restyle(layer, change):
    """Change the first 2D category's symbol as Layer Properties would (setRenderer)."""
    r2d = layer.renderer().clone()
    categories = r2d.categories()                       # keep the copies alive
    symbol = categories[0].symbol().clone()
    change(symbol)
    r2d.updateCategorySymbol(0, symbol)
    layer.setRenderer(r2d)
    _qgis_holds(r2d)


def _qgis_holds(obj):
    """As QGIS's own widgets hand it over: no Python wrapper stays tied to the layer (a stale
    one would come back later as another object of the wrong class)."""
    from qgis.PyQt import sip
    sip.transferto(obj, None)


_KEEP = []          # clones behind sip.cast wrappers: the wrapper does not own them


def _symbol3d(layer):
    from qgis._3d import QgsPolygon3DSymbol
    from qgis.PyQt import sip
    categories = layer.renderer3D().categories()
    clone = categories[0].symbol().clone()
    _KEEP.append(clone)
    return sip.cast(clone, QgsPolygon3DSymbol)


def test_3d_polygons_carry_the_2d_transparency_and_outline(qgis_app, interp_store):
    from qgis.PyQt.QtGui import QColor
    prj, polys = _poly_layer(interp_store)

    def change(symbol):
        fill = symbol.symbolLayer(0)
        fill.setFillColor(QColor(200, 100, 50, 128))
        fill.setStrokeColor(QColor(0, 0, 255))
        fill.setStrokeWidth(0.5)                         # mm
        symbol.setOpacity(0.8)
    _restyle(polys, change)                              # followed without a call of ours
    s3d = _symbol3d(polys)
    material = s3d.materialSettings()
    assert material.diffuse().name() == "#c86432"
    assert material.opacity() == pytest.approx(128 / 255 * 0.8, abs=0.01)
    assert s3d.edgesEnabled() and s3d.edgeColor().name() == "#0000ff"
    assert s3d.edgeWidth() == pytest.approx(0.5 * 96 / 25.4, rel=0.01)
    prj.clear()


def test_a_hatched_fill_is_its_colour_half_see_through(qgis_app, interp_store):
    from qgis.PyQt.QtCore import Qt
    prj, polys = _poly_layer(interp_store)
    _restyle(polys, lambda s: s.symbolLayer(0).setBrushStyle(Qt.BrushStyle.BDiagPattern))
    assert _symbol3d(polys).materialSettings().opacity() == pytest.approx(0.5, abs=0.01)
    prj.clear()


def test_an_outline_only_polygon_is_only_its_edges(qgis_app, interp_store):
    from qgis.PyQt.QtCore import Qt
    prj, polys = _poly_layer(interp_store)
    _restyle(polys, lambda s: s.symbolLayer(0).setBrushStyle(Qt.BrushStyle.NoBrush))
    s3d = _symbol3d(polys)
    assert s3d.materialSettings().opacity() == pytest.approx(0.0) and s3d.edgesEnabled()
    prj.clear()


def test_a_3d_category_the_user_restyled_is_not_followed(qgis_app, interp_store):
    from qgis._3d import QgsPhongMaterialSettings
    from qgis.PyQt.QtGui import QColor
    prj, polys = _poly_layer(interp_store)
    from qgis._3d import QgsPolygon3DSymbol
    from qgis.core import Qgis
    r3d = polys.renderer3D().clone()
    own = QgsPolygon3DSymbol()                           # the user's own 3D style
    own.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
    material = QgsPhongMaterialSettings()
    material.setDiffuse(QColor("#123456"))
    own.setMaterialSettings(material)
    r3d.updateCategorySymbol(0, own)
    polys.setRenderer3D(r3d)
    _qgis_holds(r3d)
    _restyle(polys, lambda s: s.symbolLayer(0).setFillColor(QColor("#ff0000")))
    assert _symbol3d(polys).materialSettings().diffuse().name() == "#123456"
    prj.clear()


def test_3d_lines_take_the_2d_width(qgis_app, interp_store):
    from qgis._3d import QgsLine3DSymbol
    from qgis.core import QgsProject
    from qgis.PyQt import sip

    from groundwork_geophysics.ui.interp_layers import add_interp_layers
    v = interp_store.current_version()
    f = InterpFeature(new_id(), v.id, type="fault", name="F")
    interp_store.save_feature(f)
    interp_store.save_piece(InterpPiece(new_id(), v.id, f.id, "prof", "line",
                                        [(10, 0), (20, -5)]))
    interp_store.rebuild_derived(v.id, {"prof": BENT})
    prj = QgsProject()
    lines = add_interp_layers(interp_store, prj)["interp_lines_3d"]
    _restyle(lines, lambda s: s.setWidth(1.0))           # mm
    categories = lines.renderer3D().categories()
    clone = categories[0].symbol().clone()
    s3d = sip.cast(clone, QgsLine3DSymbol)
    assert s3d.width() == pytest.approx(96 / 25.4, rel=0.01)
    prj.clear()


def test_restyling_from_2d_resets_every_3d_category_and_style(qgis_app, interp_store):
    """Show in 3D's "Restyle the interpretation from 2D": a 3D category the user restyled
    follows its 2D style again, and a layer whose 3D style was replaced or removed gets the
    categorized one back."""
    from qgis._3d import (QgsLine3DSymbol, QgsPhongMaterialSettings, QgsPolygon3DSymbol,
                          QgsVectorLayer3DRenderer)
    from qgis.core import Qgis
    from qgis.PyQt.QtGui import QColor

    from groundwork_geophysics.ui.interp_layers import interp_layers, restyle_from_2d
    prj, polys = _poly_layer(interp_store)
    r3d = polys.renderer3D().clone()
    own = QgsPolygon3DSymbol()
    own.setAltitudeClamping(Qgis.AltitudeClamping.Absolute)
    material = QgsPhongMaterialSettings()
    material.setDiffuse(QColor("#123456"))
    own.setMaterialSettings(material)
    r3d.updateCategorySymbol(0, own)
    polys.setRenderer3D(r3d)
    _qgis_holds(r3d)
    layers = interp_layers(interp_store, prj)
    layers["interp_lines_3d"].setRenderer3D(QgsVectorLayer3DRenderer(QgsLine3DSymbol()))
    layers["interp_points_3d"].setRenderer3D(None)
    _restyle(polys, lambda s: s.symbolLayer(0).setFillColor(QColor("#ff0000")))
    assert _symbol3d(polys).materialSettings().diffuse().name() == "#123456"
    assert restyle_from_2d(interp_store, prj) == 3
    assert _symbol3d(polys).materialSettings().diffuse().name() == "#ff0000"
    for name in ("interp_lines_3d", "interp_points_3d"):
        r = layers[name].renderer3D()
        assert r is not None and r.type() == "categorized"
    _restyle(polys, lambda s: s.symbolLayer(0).setFillColor(QColor("#00ff00")))
    assert _symbol3d(polys).materialSettings().diffuse().name() == "#00ff00"   # follows again
    prj.clear()


def test_the_3d_renderer_has_the_source_symbol_qgis_needs(qgis_app, interp_store):
    """QGIS's 3D style page clones the categorized renderer's source symbol without checking
    for one: a renderer without it crashed QGIS when the layer was selected or its
    properties opened. New layers get one, and so does a layer saved without it."""
    from qgis._3d import QgsCategorized3DRenderer
    from qgis.core import QgsProject
    from qgis.PyQt import sip

    from groundwork_geophysics.ui.interp_layers import (LAYERS_3D, add_interp_layers,
                                                        ensure_3d_styles)
    prj = QgsProject()
    layers = add_interp_layers(interp_store, prj)
    for name in LAYERS_3D:
        r3d = sip.cast(layers[name].renderer3D(), QgsCategorized3DRenderer)
        assert r3d.sourceSymbol() is not None, name
    polys = layers["interp_polygons_3d"]
    bare = QgsCategorized3DRenderer("feature_id", [])      # as saved before this fix
    polys.setRenderer3D(bare)
    ensure_3d_styles(interp_store, prj)
    r3d = sip.cast(polys.renderer3D(), QgsCategorized3DRenderer)
    assert r3d.sourceSymbol() is not None
    prj.clear()


# -- a renderer handed to QGIS is QGIS's: no stale Python wrapper stays behind ---------------
class _Entity:
    def __init__(self, fid):
        self.id, self.name, self.type = fid, "n" + fid, "t"


def _alive(type_name):
    import gc
    gc.collect()
    return sum(1 for o in gc.get_objects() if type(o).__name__ == type_name)


def _memory_interp_layer(geometry="PolygonZ"):
    from qgis.core import QgsVectorLayer

    from groundwork_geophysics.ui import interp_layers as il
    layer = QgsVectorLayer(f"{geometry}?crs=EPSG:25832&field=feature_id:string&field=type:string",
                           "p", "memory")
    il.default_style(layer)
    il.sync_categories(layer, [_Entity("a"), _Entity("b")])
    il.default_3d(layer)
    il.follow_2d(layer)
    return layer


def test_renderers_set_by_the_plugin_leave_no_python_wrapper_behind(qgis_app):
    """A renderer copy handed to the layer stayed wrapped for as long as the layer lived;
    once QGIS deleted it, a new object QGIS made at its address came back to Python as
    that stale wrapper, of the wrong class (a graduated renderer seen as categorized:
    sync_categories on it crashed QGIS)."""
    from groundwork_geophysics.ui import interp_layers as il
    layer = _memory_interp_layer()
    before_2d = _alive("QgsCategorizedSymbolRenderer")
    before_3d = _alive("QgsCategorized3DRenderer")
    for i in range(40):                                  # every sync replaces both renderers
        il.sync_categories(layer, [_Entity("a"), _Entity("b"), _Entity(str(i))])
    assert _alive("QgsCategorizedSymbolRenderer") <= before_2d + 1
    assert _alive("QgsCategorized3DRenderer") <= before_3d + 1
    assert layer.renderer().type() == "categorizedSymbol"
    assert len(layer.renderer().categories()) == 3 and len(layer.renderer3D().categories()) == 3


def test_a_renderer_of_another_kind_is_never_taken_for_categorized(qgis_app):
    """The user's graduated, rule-based or single-symbol renderer (made by QGIS, as Layer
    Properties does) stays as it is, however often the plugin syncs in between."""
    from qgis._3d import QgsPolygon3DSymbol, QgsVectorLayer3DRenderer
    from qgis.core import (QgsFillSymbol, QgsGraduatedSymbolRenderer, QgsRuleBasedRenderer,
                           QgsSingleSymbolRenderer)
    from qgis.PyQt import sip

    from groundwork_geophysics.ui import interp_layers as il
    layer = _memory_interp_layer()
    others = [lambda: QgsGraduatedSymbolRenderer("feature_id", []),
              lambda: QgsRuleBasedRenderer(QgsFillSymbol.createSimple({})),
              lambda: QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({}))]
    wrong = 0
    for i in range(150):
        il.sync_categories(layer, [_Entity("a"), _Entity("b"), _Entity(str(i))])
        made = others[i % 3]().clone()                   # made in C++, as QGIS's own widget
        kind = made.type()
        layer.setRenderer(made)
        sip.transferto(made, None)                       # as QGIS holds it: no Python owner
        del made
        got = layer.renderer()
        wrong += type(got).__name__ == "QgsCategorizedSymbolRenderer"
        il.sync_categories(layer, [_Entity("a")])        # leaves the user's renderer alone
        il.sync_3d(layer)
        assert layer.renderer().type() == kind
        user_3d = QgsVectorLayer3DRenderer(QgsPolygon3DSymbol()).clone()
        layer.setRenderer3D(user_3d)
        sip.transferto(user_3d, None)
        del user_3d
        assert type(layer.renderer3D()).__name__ != "QgsCategorized3DRenderer"
        il.default_style(layer)
        il.default_3d(layer)
    assert wrong == 0


def test_the_source_symbol_is_there_whatever_the_2d_style(qgis_app, interp_store):
    """QGIS's 3D style page dereferences the categorized 3D renderer's source symbol: it is
    given also when the 2D style is not the per-entity one (e.g. a 0.13 project restyled in
    2D, upgraded; or "Restyle the interpretation from 2D" with such a style)."""
    from qgis._3d import QgsCategorized3DRenderer
    from qgis.core import QgsFillSymbol, QgsSingleSymbolRenderer
    from qgis.PyQt import sip

    from groundwork_geophysics.ui import interp_layers as il
    prj, polys = _poly_layer(interp_store)
    polys.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({})))
    il.default_3d(polys)
    r3d = sip.cast(polys.renderer3D(), QgsCategorized3DRenderer)
    assert r3d.sourceSymbol() is not None
    polys.setRenderer3D(QgsCategorized3DRenderer("feature_id", []))   # saved without one
    il.ensure_3d_styles(interp_store, prj)
    assert sip.cast(polys.renderer3D(), QgsCategorized3DRenderer).sourceSymbol() is not None
    polys.setRenderer3D(None)
    il.restyle_from_2d(interp_store, prj)
    assert sip.cast(polys.renderer3D(), QgsCategorized3DRenderer).sourceSymbol() is not None
    prj.clear()
