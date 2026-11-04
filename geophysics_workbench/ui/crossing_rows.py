"""The 'Crossing lines' rows of the Context layers dialog.

A row is automatic until the user clicks its tick box: until then it follows the layer's
visibility in the layer tree, live, and saves ``checked=None``."""
from __future__ import annotations

from qgis.core import Qgis, QgsMessageLog
from qgis.gui import QgsColorButton
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QCheckBox, QComboBox, QGridLayout, QGroupBox, QLabel

from ..core.context_settings import LineLayerSetting
from ..section.crossing_lines import candidate_line_layers, map_visible, symbol_colour
from .borehole_mapping import field_of, fill_field_combo

HEADERS = ("Layer", "Label field", "", "Colour")


def _guarded(slot):
    """A Qt slot must never raise (PyQt6 aborts the process): log once-per-call instead."""
    def run(self, *args):
        try:
            slot(self, *args)
        except Exception as exc:
            QgsMessageLog.logMessage(f"Crossing lines dialog: {type(exc).__name__}: {exc}",
                                     "Geophysics Workbench", Qgis.MessageLevel.Warning)
    run.__name__ = slot.__name__
    return run


class LineRow:
    """One line layer: tick, label field, 'Only selected' and colour."""

    def __init__(self, layer, visible: bool):
        self.layer_id = layer.id()
        self.check = QCheckBox(layer.name())
        self.check.setChecked(visible)
        self.label = QComboBox()
        fill_field_combo(self.label, layer)
        self.selected_only = QCheckBox("Only selected")
        self.colour = QgsColorButton()
        default = QColor(*symbol_colour(layer))
        self.colour.setDefaultColor(default)
        self.colour.setColor(default)
        self.explicit = False
        self.check.clicked.connect(self._clicked)

    def widgets(self) -> tuple:
        return (self.check, self.label, self.selected_only, self.colour)

    def _clicked(self, _checked: bool = False) -> None:
        self.explicit = True

    def load(self, s: LineLayerSetting) -> None:
        self.label.setCurrentIndex(max(0, self.label.findData(s.label_field)))
        self.selected_only.setChecked(s.selected_only)
        if s.colour:
            self.colour.setColor(QColor(s.colour))
        if s.checked is not None:
            self.explicit = True
            self.check.setChecked(s.checked)

    def follow_visibility(self, visible: bool) -> None:
        if not self.explicit:
            self.check.setChecked(visible)

    def setting(self) -> LineLayerSetting:
        colour = self.colour.color().name()
        if colour == self.colour.defaultColor().name():
            colour = ""                                   # the layer's symbol colour, read live
        return LineLayerSetting(self.layer_id, field_of(self.label), colour,
                                self.selected_only.isChecked(),
                                self.check.isChecked() if self.explicit else None)


class CrossingLinesGroup(QGroupBox):
    """Rows for every candidate line layer, kept in step with the project while open."""

    def __init__(self, project, exclude: set[str]):
        super().__init__("Crossing lines")
        self.project = project
        self.exclude = set(exclude)
        self.rows: dict[str, LineRow] = {}
        self.stale: list[LineLayerSetting] = []
        self.grid = QGridLayout(self)
        for col, text in enumerate(HEADERS):
            self.grid.addWidget(QLabel(f"<b>{text}</b>" if text else ""), 0, col)
        self.empty = QLabel("No matching layers in this project.")
        self.grid.addWidget(self.empty, 1, 0, 1, len(HEADERS))
        for layer in candidate_line_layers(project, self.exclude):
            self._add_row(layer)
        self._update_empty()
        for signal, slot in self._connections():
            signal.connect(slot)

    def _connections(self) -> list:
        """Built on demand: a stored bound signal would pin the project until exitQgis."""
        root = self.project.layerTreeRoot()
        return [(self.project.layersAdded, self._layers_added),
                (self.project.layersWillBeRemoved, self._layers_removed),
                (root.visibilityChanged, self._follow_map),
                (root.addedChildren, self._follow_map)]   # the tree node follows layersAdded

    def _add_row(self, layer) -> LineRow:
        row = LineRow(layer, map_visible(self.project, layer.id()))
        at = self.grid.rowCount()
        for col, widget in enumerate(row.widgets()):
            self.grid.addWidget(widget, at, col)
        self.rows[row.layer_id] = row
        return row

    def _update_empty(self) -> None:
        self.empty.setVisible(not self.rows)

    def load(self, items: list[LineLayerSetting]) -> None:
        self.stale = []
        for item in items:
            if item.layer_id in self.rows:
                self.rows[item.layer_id].load(item)
            elif not self._valid_layer(item.layer_id):
                self.stale.append(item)                   # missing or unavailable: keep it;
                                                          # excluded or non-line layers are dropped

    def _valid_layer(self, layer_id: str) -> bool:
        layer = self.project.mapLayer(layer_id)
        return layer is not None and layer.isValid()

    def stale_count(self) -> int:
        return len(self.stale)

    def settings(self) -> list[LineLayerSetting]:
        return [row.setting() for row in self.rows.values()] + list(self.stale)

    @_guarded
    def _layers_added(self, layers) -> None:
        ids = {layer.id() for layer in layers}
        for layer in candidate_line_layers(self.project, self.exclude):
            if layer.id() in ids and layer.id() not in self.rows:
                row = self._add_row(layer)
                saved = [s for s in self.stale if s.layer_id == layer.id()]
                if saved:                                 # a removed layer came back
                    row.load(saved[0])
                    self.stale.remove(saved[0])
        self._update_empty()

    @_guarded
    def _layers_removed(self, layers) -> None:
        for item in layers:                               # ids or layers, by signal overload
            row = self.rows.pop(item if isinstance(item, str) else item.id(), None)
            if row is None:
                continue
            if row.explicit:
                self.stale.append(row.setting())
            for widget in row.widgets():
                self.grid.removeWidget(widget)
                widget.deleteLater()
        self._update_empty()

    @_guarded
    def _follow_map(self, *_args) -> None:
        for layer_id, row in self.rows.items():
            row.follow_visibility(map_visible(self.project, layer_id))

    def detach(self) -> None:
        try:
            connections = self._connections()
        except RuntimeError:                              # the project is already deleted
            return
        for signal, slot in connections:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):             # already disconnected
                pass
