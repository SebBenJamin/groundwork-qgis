"""Interpretation layers in the QGIS project: added once, styled, kept in step with edits."""
import numpy as np
import pytest

from geophysics_workbench.core.chainage import Chainage
from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id

BENT = Chainage(np.array([[0.0, 0.0], [50.0, 0.0], [50.0, 50.0]]))


@pytest.fixture
def interp_store(tmp_path):
    from geophysics_workbench.store.gpkg_store import ProjectStore
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

    from geophysics_workbench.ui.interp_layers import INTERP_GROUP, add_interp_layers

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

    from geophysics_workbench.section.crossing_lines import own_layer_ids
    from geophysics_workbench.ui.interp_layers import add_interp_layers

    prj = QgsProject()
    layers = add_interp_layers(interp_store, prj)
    own = own_layer_ids(interp_store, prj)
    assert layers["interp_lines_3d"].id() in own and layers["interp_footprints"].id() in own
    prj.clear()


def test_style_groups_by_entity_with_confidence_line_style(qgis_app, interp_store):
    from qgis.core import QgsProject, QgsSymbolLayer

    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id
    from geophysics_workbench.ui.interp_layers import add_interp_layers, reload_interp_layers

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

    from geophysics_workbench.ui.interp_layers import InterpSync, add_interp_layers

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

    from geophysics_workbench.ui.interp_layers import add_interp_layers

    interp_store.freeze_current("R1")                      # a second copy of every feature
    prj = QgsProject()
    feats = add_interp_layers(interp_store, prj)["interp_features"]
    cur = interp_store.current_version().id
    assert [f["version_id"] for f in feats.getFeatures()] == [cur]
    prj.clear()


def test_feature_deleted_in_table_removes_its_pieces(qgis_app, interp_store):
    from qgis.core import QgsProject

    from geophysics_workbench.ui.interp_layers import InterpSync, add_interp_layers

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

    from geophysics_workbench.ui.interp_layers import add_interp_layers, reload_interp_layers

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
