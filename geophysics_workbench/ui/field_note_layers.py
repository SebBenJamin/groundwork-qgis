"""Field-note map layers in the QGIS project ("Field notes" and "Field notes (stretches)").

The plugin's own data, derived from the notes in the workbench GeoPackage: read-only,
labelled with the note's text, notes switched off left out (subset string). Their look is
an ordinary QGIS style the user can change."""
from __future__ import annotations

from qgis.core import (QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings, QgsProject,
                       QgsSingleSymbolRenderer, QgsTextFormat, QgsVectorLayer,
                       QgsVectorLayerSimpleLabeling)
from qgis.PyQt.QtGui import QColor

from ..store.gpkg_store import ProjectStore
from .project_actions import GROUP_NAME, find_store_layers

NOTE_NAMES = ("field_notes_points", "field_notes_lines")
TITLES = {"field_notes_points": "Field notes",
          "field_notes_lines": "Field notes (stretches)"}
LABEL_RGB = (150, 70, 0)
NOTE_STYLE_PROPERTY = "wb_note_style"     # the workbench style was given (once)


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
        default_note_style(layer, name)
        project.addMapLayer(layer, False)
        group.addLayer(layer)
        have[name] = layer
    return have


def default_note_style(layer: QgsVectorLayer, name: str) -> None:
    """The workbench's look, as the section draws notes when unstyled: a marker for notes
    at one chainage (labelled), a 0.5 mm line for stretches. The user restyles freely."""
    from ..section.field_notes_render import NOTE_RGB, STRETCH_MM
    rgb = ",".join(str(v) for v in NOTE_RGB)
    if name == "field_notes_points":
        sym = QgsMarkerSymbol.createSimple({"name": "filled_arrowhead", "color": rgb,
                                            "outline_style": "no", "size": "2.5",
                                            "angle": "90"})
        _label(layer)
    else:
        sym = QgsLineSymbol.createSimple({"color": rgb, "width": str(STRETCH_MM)})
    layer.setRenderer(QgsSingleSymbolRenderer(sym))
    layer.setCustomProperty(NOTE_STYLE_PROPERTY, "1")
    layer.triggerRepaint()


def ensure_note_layers(store: ProjectStore, project: QgsProject) -> dict[str, QgsVectorLayer]:
    """Add the field-note layers when the store has notes and they are missing, so there
    is always a layer to style them with (agreed with the user)."""
    if not store.has_field_notes() or not store.field_notes():
        return field_note_layers(store, project)
    try:
        return add_field_note_layers(store, project)
    except ValueError:                          # the file cannot be loaded as layers
        return field_note_layers(store, project)


def migrate_note_styles(store: ProjectStore, project: QgsProject) -> int:
    """0.7 left the note layers with QGIS's random symbol (it did not draw the section).
    Give such layers the workbench style once; later the user's style is kept."""
    changed = 0
    for name, layer in field_note_layers(store, project).items():
        if layer.customProperty(NOTE_STYLE_PROPERTY) is None:
            default_note_style(layer, name)
            changed += 1
    return changed


def stretch_rgb(store: ProjectStore, project: QgsProject) -> tuple[int, int, int]:
    """The stretches layer's colour (the Note tool's drag preview), else the default."""
    from ..section.field_notes_render import NOTE_RGB
    layer = field_note_layers(store, project).get("field_notes_lines")
    renderer = layer.renderer() if layer is not None else None
    from qgis.core import QgsRenderContext
    symbols = renderer.symbols(QgsRenderContext()) if renderer is not None else []
    if not symbols:
        return NOTE_RGB
    c = symbols[0].color()
    return c.red(), c.green(), c.blue()


def reload_field_note_layers(store: ProjectStore, project: QgsProject) -> None:
    for layer in field_note_layers(store, project).values():
        layer.dataProvider().reloadData()
        layer.reload()
        layer.updateExtents()
        layer.triggerRepaint()
