"""The 'Surface Strips' list of the Context layers dialog.

Each row is one polygon layer drawn as a strip above the ground: layer, label field, an
optional title and a 'Show' tick. The first row is the top strip. Remove, Move Up and Move
Down act on the row that has focus or was last clicked."""
from __future__ import annotations

from qgis.PyQt.QtCore import QEvent
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout,
                                 QLabel, QLineEdit, QPushButton, QVBoxLayout)

from ..core.context_settings import BandSetting
from .borehole_mapping import MISSING, field_of, fill_field_combo, fill_layer_combo

HEADERS = ("", "Layer", "Label field", "Title", "")
HINT = "Polygon layers drawn as strips above the ground; the first row is the top strip."


class StripRow:
    """One strip's widgets."""

    def __init__(self, project, polygon_layers):
        self.project = project
        self.number = QLabel()
        self.layer = QComboBox()
        fill_layer_combo(self.layer, polygon_layers)
        self.layer.removeItem(0)                          # a strip always has a layer
        self.field = QComboBox()
        self.title = QLineEdit()
        self.title.setToolTip("Shown above the strip; empty uses the layer's name")
        self.show = QCheckBox("Show")
        self.layer.currentIndexChanged.connect(lambda _i: self._layer_changed())
        self._layer_changed()

    def widgets(self) -> tuple:
        return (self.number, self.layer, self.field, self.title, self.show)

    def layer_id(self) -> str:
        return self.layer.currentData() or ""

    def is_missing(self) -> bool:
        return self.layer.currentText() == MISSING

    def _layer_changed(self) -> None:
        keep = field_of(self.field)
        layer = self.project.mapLayer(self.layer_id())
        fill_field_combo(self.field, layer, keep)
        self.title.setPlaceholderText("" if self.is_missing() else self.layer.currentText())

    def load(self, band: BandSetting) -> None:
        if self.layer.findData(band.layer_id) < 0:        # gone from the project, or no polygons now
            self.layer.addItem(MISSING, band.layer_id)
        self.layer.setCurrentIndex(self.layer.findData(band.layer_id))
        if self.field.findData(band.label_field) < 0 and band.label_field:
            self.field.addItem(band.label_field, band.label_field)   # its layer is gone: keep it
        self.field.setCurrentIndex(max(0, self.field.findData(band.label_field)))
        self.title.setText(band.title)
        self.show.setChecked(band.shown)

    def setting(self) -> BandSetting:
        return BandSetting(self.layer_id(), field_of(self.field), self.title.text(),
                           self.show.isChecked())


class StripRows(QGroupBox):
    """The strip list with its Add, Remove, Move Up and Move Down buttons."""

    def __init__(self, project, polygon_layers):
        super().__init__("Surface Strips")
        self.project = project
        self.polygon_layers = list(polygon_layers)
        self.rows: list[StripRow] = []
        self.current = -1
        hint = QLabel(HINT)
        hint.setWordWrap(True)
        self.grid = QGridLayout()
        for col, text in enumerate(HEADERS):
            head = QLabel(text)
            font = head.font()
            font.setBold(True)
            head.setFont(font)
            self.grid.addWidget(head, 0, col)
        self.grid.setColumnStretch(1, 1)
        self.grid.setColumnStretch(2, 1)
        self.grid.setColumnStretch(3, 1)
        self.empty = QLabel("No strips yet.")
        self.add_button = QPushButton("Add")
        self.remove_button = QPushButton("Remove")
        self.up_button = QPushButton("Move Up")
        self.down_button = QPushButton("Move Down")
        self.add_button.clicked.connect(lambda _c=False: self.add_row())
        self.remove_button.clicked.connect(lambda _c=False: self.remove_row(self.current))
        self.up_button.clicked.connect(lambda _c=False: self.move_row(self.current, -1))
        self.down_button.clicked.connect(lambda _c=False: self.move_row(self.current, 1))
        buttons = QHBoxLayout()
        for b in (self.add_button, self.remove_button, self.up_button, self.down_button):
            buttons.addWidget(b)
        buttons.addStretch(1)
        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addLayout(self.grid)
        lay.addWidget(self.empty)
        lay.addLayout(buttons)
        self._refresh()

    # -- rows --------------------------------------------------------------------------------
    def _new_row(self) -> StripRow:
        row = StripRow(self.project, self.polygon_layers)
        for w in row.widgets():
            w.installEventFilter(self)
        self.rows.append(row)
        return row

    def add_row(self) -> None:
        """A new row on the first polygon layer, below the others and selected."""
        if not self.polygon_layers:
            return
        row = self._new_row()
        row.show.setChecked(True)
        self.current = len(self.rows) - 1
        self._refresh()

    def remove_row(self, i: int) -> None:
        if not 0 <= i < len(self.rows):
            return
        row = self.rows.pop(i)
        for w in row.widgets():
            self.grid.removeWidget(w)
            w.hide()
            w.deleteLater()
        self.current = min(i, len(self.rows) - 1)
        self._refresh()

    def move_row(self, i: int, delta: int) -> None:
        j = i + delta
        if not (0 <= i < len(self.rows) and 0 <= j < len(self.rows)):
            return
        self.rows[i], self.rows[j] = self.rows[j], self.rows[i]
        self.current = j
        self._refresh()

    def load(self, bands: list[BandSetting]) -> None:
        for i in range(len(self.rows) - 1, -1, -1):
            self.remove_row(i)
        for band in bands:
            self._new_row().load(band)
        self.current = 0 if self.rows else -1
        self._refresh()

    def settings(self) -> list[BandSetting]:
        return [row.setting() for row in self.rows]

    def missing_count(self) -> int:
        return sum(row.is_missing() for row in self.rows)

    # -- selection and layout ----------------------------------------------------------------
    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress):
            for i, row in enumerate(self.rows):
                if obj in row.widgets():
                    if i != self.current:
                        self.current = i
                        self._refresh()
                    break
        return False

    def _refresh(self) -> None:
        for i, row in enumerate(self.rows):
            for col, w in enumerate(row.widgets()):
                self.grid.removeWidget(w)
                self.grid.addWidget(w, i + 1, col)
                w.show()
            row.number.setText(str(i + 1))
            font = row.number.font()
            font.setBold(i == self.current)
            row.number.setFont(font)
        n = len(self.rows)
        self.empty.setVisible(n == 0)
        self.add_button.setEnabled(bool(self.polygon_layers))
        self.add_button.setToolTip("" if self.polygon_layers
                                   else "This project has no polygon layers")
        self.remove_button.setEnabled(n > 0)
        self.remove_button.setToolTip("Remove the selected strip" if n
                                      else "There is no strip to remove")
        self.up_button.setEnabled(self.current > 0)
        self.up_button.setToolTip("Move the selected strip up" if self.current > 0
                                  else "The selected strip is already the top one")
        self.down_button.setEnabled(0 <= self.current < n - 1)
        self.down_button.setToolTip("Move the selected strip down" if 0 <= self.current < n - 1
                                    else "The selected strip is already the bottom one")
