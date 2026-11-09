"""Field-note map layers in the QGIS project ("Field notes" and "Field notes (stretches)").

The plugin's own data, derived from the notes in the workbench GeoPackage: read-only,
labelled with the note's text, notes switched off left out (subset string). Their look is
an ordinary QGIS style the user can change."""
from __future__ import annotations

from qgis.core import (QgsPalLayerSettings, QgsProject, QgsTextFormat, QgsVectorLayer,
                       QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtGui import QColor

from ..store.gpkg_store import ProjectStore
from .project_actions import GROUP_NAME, find_store_layers

NOTE_NAMES = ("field_notes_points", "field_notes_lines")
TITLES = {"field_notes_points": "Field notes",
          "field_notes_lines": "Field notes (stretches)"}
LABEL_RGB = (150, 70, 0)


def field_note_layers(store: ProjectStore, project: QgsProject) -> dict[str, QgsVectorLayer]:
    return find_store_layers(store, project, NOTE_NAMES)


def _label(layer: QgsVectorLayer) -> None:
    settings = QgsPalLayerSettings()
    settings.fieldName = "text"
    fmt = QgsTextFormat()
    fmt.setSize(8.0)
    fmt.setColor(QColor(*LABEL_RGB))
    buffer = fmt.buffer()
    buffer.setEnabled(True)
    fmt.setBuffer(buffer)
    settings.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def add_field_note_layers(store: ProjectStore, project: QgsProject) -> dict[str, QgsVectorLayer]:
    """Add the field-note layers to the workbench group unless already there."""
    store.ensure_field_notes()
    have = field_note_layers(store, project)
    root = project.layerTreeRoot()
    group = root.findGroup(GROUP_NAME) or root.insertGroup(0, GROUP_NAME)
    for name in NOTE_NAMES:
        if name in have:
            continue
        layer = QgsVectorLayer(store.layer_uri(name), TITLES[name], "ogr")
        if not layer.isValid():
            raise ValueError(f"QGIS cannot load layer {name!r} from {store.path}")
        layer.setSubsetString('"shown" = 1')
        layer.setReadOnly(True)
        if name == "field_notes_points":
            _label(layer)
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        have[name] = layer
    return have


def reload_field_note_layers(store: ProjectStore, project: QgsProject) -> None:
    for layer in field_note_layers(store, project).values():
        layer.dataProvider().reloadData()
        layer.reload()
        layer.updateExtents()
        layer.triggerRepaint()
