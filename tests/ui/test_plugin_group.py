"""The plugin's layer group: old projects keep theirs, new ones get "Groundwork"."""
from qgis.core import QgsProject

from groundwork_geophysics.ui import field_note_layers, interp_layers, project_actions
from groundwork_geophysics.ui.project_actions import (default_store_name, new_store,
                                                      plugin_group)

OLD = "Geophysics Workbench"
NEW = "Groundwork"


def _names(root):
    return [g.name() for g in root.findGroups()]


def test_new_project_gets_groundwork_group(qgis_app):
    prj = QgsProject()
    root = prj.layerTreeRoot()
    group = plugin_group(root)
    assert group.name() == NEW
    assert plugin_group(root) is group
    assert _names(root) == [NEW]


def test_old_group_is_reused(qgis_app):
    prj = QgsProject()
    root = prj.layerTreeRoot()
    old = root.addGroup(OLD)
    assert plugin_group(root) is old
    assert _names(root) == [OLD]


def test_new_group_wins_when_both_exist(qgis_app):
    prj = QgsProject()
    root = prj.layerTreeRoot()
    root.addGroup(OLD)
    new = root.addGroup(NEW)
    assert plugin_group(root) is new
    assert len(_names(root)) == 2


def test_old_project_opens_with_its_store(qgis_app, tmp_path):
    prj = QgsProject()
    prj.layerTreeRoot().addGroup(OLD)
    store = new_store(tmp_path / "old.gpkg", "EPSG:25832", prj)
    prj.writeEntry("geophysics_workbench", "store_path", str(store.path))
    qgz = tmp_path / "old.qgz"
    assert prj.write(str(qgz))

    reopened = QgsProject()
    assert reopened.read(str(qgz))
    again = project_actions.attach_store(reopened)
    assert again is not None and again.path == store.path
    project_actions.add_store_layers(again, reopened)
    field_note_layers.add_field_note_layers(again, reopened)
    root = reopened.layerTreeRoot()
    assert NEW not in _names(root)
    old = root.findGroup(OLD)
    assert {"profiles", "stations"} <= {n.layer().name() for n in old.findLayers()}
    again.ensure_interpretation()
    interp_layers.add_interp_layers(again, reopened)
    assert NEW not in _names(root)


def test_default_store_name(qgis_app, tmp_path):
    prj = QgsProject()
    assert default_store_name(prj) == ""
    prj.setFileName(str(tmp_path / "site.qgz"))
    assert default_store_name(prj) == str(tmp_path / "site_groundwork.gpkg")
