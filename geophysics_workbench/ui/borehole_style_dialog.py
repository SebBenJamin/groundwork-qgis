"""Borehole style…: QGIS's own style editor for a borehole interval table.

QGIS keeps no style on a table without geometry, so the editor works on a temporary memory
**polygon** copy of the table (same fields, one dummy square per row). The copy is never
saved and never added to the project; QGIS's Categorized / Rule-based / Graduated editors,
Classify, the symbol selector, SVG fills (the FGDC patterns included) and the style library
behave as for any layer. Apply stores the copy's renderer for the table
(``borehole_style.save_renderer``) and redraws the section and the viewer."""
from __future__ import annotations

from typing import Callable

from qgis.core import (QgsFeature, QgsFeatureRequest, QgsExpression, QgsGeometry, QgsMapLayer,
                       QgsStyle, QgsVectorLayer)
from qgis.gui import QgsRendererPropertiesDialog
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QHBoxLayout, QLabel,
                                 QPushButton, QVBoxLayout)

from ..section.borehole_style import load_renderer, save_renderer

REMOTE_PROVIDERS = ("WFS", "OAPIF", "arcgisfeatureserver")
_SQUARE = "POLYGON((0 0, 1 0, 1 1, 0 1, 0 0))"
_SYMBOLOGY = QgsMapLayer.StyleCategory.Symbology


def is_remote(layer) -> bool:
    """A live web source: never read in full."""
    return layer.providerType() in REMOTE_PROVIDERS


def style_copy(log_layer: QgsVectorLayer, ids: list[str] | None,
               id_field: str) -> QgsVectorLayer:
    """A memory polygon layer with ``log_layer``'s fields and rows (only the rows of ``ids``
    when given), each with a dummy square, so QGIS's style editors work on it."""
    copy = QgsVectorLayer("Polygon", f"{log_layer.name()} (style)", "memory")
    copy.dataProvider().addAttributes(log_layer.fields().toList())
    copy.updateFields()
    request = QgsFeatureRequest()
    if ids is not None:
        quoted = ", ".join(QgsExpression.quotedString(i) for i in ids) or "''"
        request.setFilterExpression(
            f"trim(to_string({QgsExpression.quotedColumnRef(id_field)})) IN ({quoted})")
    square = QgsGeometry.fromWkt(_SQUARE)
    rows = []
    for f in log_layer.getFeatures(request):
        g = QgsFeature(copy.fields())
        g.setAttributes(f.attributes())
        g.setGeometry(square)
        rows.append(g)
    copy.dataProvider().addFeatures(rows)
    copy.updateExtents()
    return copy


def drawn_look(copy: QgsVectorLayer, text_field: str):
    """What the section draws without a saved style, as a QGIS renderer: one category per
    interval text in its neutral colour (``default_symbol``). Only the editor's starting
    point; nothing is saved until Apply/OK."""
    from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory

    from ..section.borehole_style import default_symbol
    index = copy.fields().indexOf(text_field)
    values = sorted({str(v) for v in copy.uniqueValues(index) if v not in (None, "")}
                    if index >= 0 else set(), key=str.lower)
    return QgsCategorizedSymbolRenderer(text_field, [
        QgsRendererCategory(v, default_symbol(v), v) for v in values])


class BoreholeStyleDialog(QDialog):
    def __init__(self, project, entry, profile_ids: list[str], on_saved: Callable[[], None],
                 parent=None, profile_name: str = ""):
        super().__init__(parent)
        self.project, self.entry, self.on_saved = project, entry, on_saved
        self.log_layer = project.mapLayer(entry.log_layer_id)
        if self.log_layer is None:
            raise ValueError("The interval table of this borehole entry is not in the project.")
        remote = is_remote(self.log_layer)
        self.copy = style_copy(self.log_layer, list(profile_ids) if remote else None,
                               entry.log_id_field)
        stored = load_renderer(project, entry.log_layer_id)
        if stored is not None:
            self.copy.setRenderer(stored)
        elif entry.lithology_field:
            self.copy.setRenderer(drawn_look(self.copy, entry.lithology_field))
        self.setWindowTitle(f"Borehole style – {self.log_layer.name()}")
        layout = QVBoxLayout(self)
        self.note = QLabel(f"Classes from the boreholes of {profile_name or 'this profile'} "
                           f"only (live source)." if remote else "")
        self.note.setVisible(remote)
        layout.addWidget(self.note)
        self._editor_box = QVBoxLayout()
        layout.addLayout(self._editor_box, 1)
        self.editor = None
        self.reload_editor()
        row = QHBoxLayout()
        export_btn, import_btn = QPushButton("Export…"), QPushButton("Import…")
        patterns_btn = QPushButton("Patterns…")
        patterns_btn.setToolTip("A colour and an FGDC pattern for every class, in one table")
        export_btn.clicked.connect(self._export)
        import_btn.clicked.connect(self._import)
        patterns_btn.clicked.connect(self._open_patterns)
        row.addWidget(patterns_btn)
        row.addWidget(export_btn)
        row.addWidget(import_btn)
        row.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Apply
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._ok)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        row.addWidget(buttons)
        layout.addLayout(row)
        self.resize(720, 560)

    def reload_editor(self) -> None:
        """(Re)build QGIS's style editor on the copy's current renderer."""
        if self.editor is not None:
            self._editor_box.removeWidget(self.editor)
            self.editor.deleteLater()
        self.editor = QgsRendererPropertiesDialog(self.copy, QgsStyle.defaultStyle(), True, self)
        # it is a QDialog: as a child it would stay a separate (hidden) window
        self.editor.setWindowFlags(Qt.WindowType.Widget)
        self._editor_box.addWidget(self.editor, 1)
        self.editor.show()

    def patterns_table(self):
        """The Patterns table for the editor's current style, or ``None`` (with a note) when
        the style is not Categorized: the table needs classes."""
        from .pattern_table import PatternTable
        self.editor.apply()
        renderer = self.copy.renderer()
        if renderer is None or renderer.type() != "categorizedSymbol"                 or not renderer.categories():
            self.note.setText("Patterns… works on classes: choose “Categorized”, "
                              "press Classify, then Patterns… again.")
            self.note.setVisible(True)
            return None
        return PatternTable(renderer, self)

    def take_patterns(self, table) -> None:
        """Hand the table's classes to QGIS's editor (saved on Apply/OK, as any edit)."""
        self.copy.setRenderer(table.result())
        self.reload_editor()

    def _open_patterns(self) -> None:
        table = self.patterns_table()
        if table is not None and table.exec():
            self.take_patterns(table)
        if table is not None:
            table.deleteLater()

    def apply(self) -> None:
        self.editor.apply()
        renderer = self.copy.renderer()
        save_renderer(self.project, self.entry.log_layer_id,
                      renderer.clone() if renderer is not None else None)
        self.on_saved()

    def _ok(self) -> None:
        self.apply()
        self.accept()

    def export_to(self, path: str) -> bool:
        self.editor.apply()
        _msg, ok = self.copy.saveNamedStyle(path, _SYMBOLOGY)
        return bool(ok)

    def import_from(self, path: str) -> bool:
        _msg, ok = self.copy.loadNamedStyle(path, _SYMBOLOGY)
        if ok:
            self.reload_editor()
        return bool(ok)

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export borehole style", "",
                                              "QGIS style (*.qml)")
        if path:
            self.export_to(path if path.lower().endswith(".qml") else path + ".qml")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import borehole style", "",
                                              "QGIS style (*.qml)")
        if path:
            self.import_from(path)
