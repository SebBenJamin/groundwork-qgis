"""Round 2, F6: the interpretation form, labels and saved QGIS styles use Name, not Letter.
A 0.7 project's interpretation layers keep labelling after their store is updated."""
import numpy as np
import pytest

from groundwork_geophysics.core.chainage import Chainage
from groundwork_geophysics.core.interpretation import InterpFeature, InterpPiece, new_id

TABLES = ("interp_features", "interp_lines_3d", "interp_polygons_3d", "interp_points_3d",
          "interp_footprints")


def _store(path, name="Clay A"):
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    st = ProjectStore.create(path, "EPSG:25832")
    st.ensure_interpretation()
    v = st.current_version()
    f = InterpFeature(new_id(), v.id, type="clay", name=name)
    st.save_feature(f)
    st.save_piece(InterpPiece(new_id(), v.id, f.id, "prof", "polygon",
                              [(10, 0), (30, 0), (30, -5), (10, -5)]))
    st.rebuild_derived(v.id, {"prof": Chainage(np.array([[0.0, 0.0], [50.0, 0.0]]))})
    return st


def _to_schema_1(path):
    from osgeo import ogr
    ds = ogr.Open(str(path), 1)
    for table in TABLES:
        lyr = ds.GetLayerByName(table)
        defn = lyr.GetLayerDefn()
        lyr.AlterFieldDefn(defn.GetFieldIndex("name"), ogr.FieldDefn("letter", ogr.OFTString),
                           ogr.ALTER_NAME_FLAG)
    ds.ExecuteSQL("UPDATE wb_meta SET value = '1' WHERE key = 'schema_version'")
    ds = None


def _old_style(layer):
    """What 0.7 wrote and what a user may have added: labels and a rule on ``letter``."""
    from qgis.core import (QgsPalLayerSettings, QgsRuleBasedRenderer, QgsSymbol,
                           QgsVectorLayerSimpleLabeling)
    settings = QgsPalLayerSettings()
    settings.fieldName = "letter"
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)
    root = QgsRuleBasedRenderer.Rule(None)
    root.appendChild(QgsRuleBasedRenderer.Rule(QgsSymbol.defaultSymbol(layer.geometryType()),
                                               0, 0, "\"letter\" = 'Clay A'", "Clay A"))
    layer.setRenderer(QgsRuleBasedRenderer(root))


@pytest.fixture
def project(qgis_app):
    from qgis.core import QgsProject
    prj = QgsProject.instance()
    prj.clear()
    yield prj
    prj.removeAllMapLayers()
    prj.clear()


def test_form_says_name(qgis_app):
    from groundwork_geophysics.ui.interp_form import InterpForm
    form = InterpForm(None, InterpFeature("f", "v", name="Clay A"), [], {"clay b"})
    label = form.layout().labelForField(form.name_edit)
    assert label.text() == "Name"
    assert form.name_edit.placeholderText() == "e.g. Clay A"
    form.name_edit.setText("Clay B")
    assert form.name_warning.isVisibleTo(form)
    assert form.name_warning.text() == "This name is already used by another feature."
    assert form.feature().name == "Clay B"


def test_default_style_labels_name(qgis_app, tmp_path, project):
    from groundwork_geophysics.ui.interp_layers import add_interp_layers
    layers = add_interp_layers(_store(tmp_path / "wb.gpkg"), project)
    assert layers["interp_polygons_3d"].labeling().settings().fieldName == "name"


def test_migrate_letter_styles(qgis_app, tmp_path, project):
    from groundwork_geophysics.ui.interp_layers import add_interp_layers, migrate_letter_styles
    st = _store(tmp_path / "wb.gpkg")
    layer = add_interp_layers(st, project)["interp_polygons_3d"]
    _old_style(layer)
    assert migrate_letter_styles(st, project) == 1
    assert layer.labeling().settings().fieldName == "name"
    [rule] = layer.renderer().rootRule().children()
    assert rule.filterExpression() == "\"name\" = 'Clay A'"
    assert migrate_letter_styles(st, project) == 0


def test_open_project_layers_survive_migration(qgis_app, tmp_path, project, fake_iface):
    """Review Focus 1: the layers are loaded from the 0.7 file before the plugin updates it."""
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from groundwork_geophysics import classFactory
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    from groundwork_geophysics.ui.interp_layers import add_interp_layers
    path = tmp_path / "wb.gpkg"
    _store(path)
    _to_schema_1(path)
    old = ProjectStore(path, "EPSG:25832")                 # as 0.7 saw it, not opened
    layer = add_interp_layers(old, project)["interp_polygons_3d"]
    _old_style(layer)
    assert layer.fields().indexOf("letter") >= 0
    plug = classFactory(fake_iface)
    plug.initGui()
    try:
        plug.set_store(ProjectStore.open(path))            # updates the file to schema 2
        assert layer.isValid() and layer.fields().indexOf("name") >= 0
        assert layer.labeling().settings().fieldName == "name"
        assert [f["name"] for f in layer.getFeatures()] == ["Clay A"]
    finally:
        plug.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
