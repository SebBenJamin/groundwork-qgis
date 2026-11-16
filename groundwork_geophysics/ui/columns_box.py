"""'What the Columns Are': the group of the Add Data dialog that says which column of a text
table is the position (distance along the line, or easting and northing with their CRS), the
vertical and the value, with the vertical meaning and the quantity. Only numeric columns are
offered: a text column (comments, point codes) is never a position, vertical or value.

``set_columns`` is silent; ``changed`` follows every choice of the user (typed names and
units on ``editingFinished`` only, so typing reads nothing)."""
from __future__ import annotations

from qgis.gui import QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QGridLayout, QGroupBox,
                                 QHBoxLayout, QLabel, QLineEdit, QRadioButton, QSizePolicy,
                                 QWidget)

from ..core.roles import QUANTITIES, VERTICAL_KINDS, WGS84, ModelColumns
from .positions_source import crs_of

GUESSED_HINT = "Guessed from the column names and the numbers. Change any of them."
REMEMBERED_HINT = "As for the last file with these columns. Change any of them."
DEGREES_HINT = " The coordinates look like degrees: EPSG:4326 is chosen."
#: role words under the column names in the preview
VERTICAL_WORDS = {"elevation": "elevation", "depth": "depth", "local": "local height"}
NOT_USED = "not used"


def _row(*widgets, stretch_last: bool = False) -> QWidget:
    row = QWidget()
    box = QHBoxLayout(row)
    box.setContentsMargins(0, 0, 0, 0)
    for w in widgets:
        box.addWidget(w, 1 if stretch_last and w is widgets[-1] else 0)
    if not stretch_last:
        box.addStretch(1)
    return row


class ModelColumnsBox(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, store_crs: str, parent=None):
        super().__init__("What the Columns Are", parent)
        self.store_crs = store_crs
        self._busy = False
        self.position_distance = QRadioButton("Distance along the line")
        self.position_map = QRadioButton("Map coordinates")
        self._position = QButtonGroup(self)
        for radio in (self.position_distance, self.position_map):
            self._position.addButton(radio)
        self.position_distance.setChecked(True)

        def combo(name: str, tip: str = "") -> QComboBox:
            box = QComboBox()
            box.setObjectName(name)
            box.setToolTip(tip)
            box.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
            return box

        self.distance_combo = combo("distance_combo", "Distance along the line, in metres")
        self.easting_combo = combo("easting_combo")
        self.northing_combo = combo("northing_combo")
        self.crs_widget = QgsProjectionSelectionWidget()
        self.crs_widget.setObjectName("columns_crs")
        self.crs_widget.setToolTip("Coordinate reference system of the easting and northing")
        self.crs_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.vertical_combo = combo("vertical_combo")
        self.vertical_kind_combo = combo("vertical_kind_combo", "What the vertical column means")
        self.vertical_kind_combo.addItem("Choose…", "")
        for text, value in VERTICAL_KINDS:
            self.vertical_kind_combo.addItem(text, value)
        self.value_combo = combo("value_combo")
        self.quantity_combo = combo("quantity_combo")
        for text, value, _unit in QUANTITIES:
            self.quantity_combo.addItem(text, value)
        self.quantity_name = QLineEdit()
        self.quantity_name.setPlaceholderText("Name")
        self.quantity_name.setToolTip("Name of the quantity, for example Chargeability")
        self.unit_edit = QLineEdit()
        self.unit_edit.setPlaceholderText("Unit")
        self.unit_edit.setToolTip("Unit of the values, for example mV/V")
        self.log10_check = QCheckBox("Values are log10")
        self.hint_label = QLabel(GUESSED_HINT)
        self.hint_label.setWordWrap(True)

        self._distance_row = _row(self.distance_combo)
        self._map_row = _row(QLabel("Easting"), self.easting_combo, QLabel("Northing"),
                             self.northing_combo)
        self._crs_row = _row(self.crs_widget, stretch_last=True)
        self._other_row = _row(self.quantity_name, self.unit_edit)
        grid = QGridLayout(self)
        grid.setColumnStretch(1, 1)
        rows = (("Position", _row(self.position_distance, self.position_map)),
                ("Distance", self._distance_row), ("Coordinates", self._map_row),
                ("CRS", self._crs_row),
                ("Vertical", _row(self.vertical_combo, self.vertical_kind_combo)),
                ("Value", _row(self.value_combo, self.quantity_combo, self.log10_check)),
                ("", self._other_row))
        self._labels: dict[QWidget, QLabel] = {}
        for r, (text, widget) in enumerate(rows):
            label = QLabel(text)
            self._labels[widget] = label
            grid.addWidget(label, r, 0)
            grid.addWidget(widget, r, 1)
        grid.addWidget(self.hint_label, len(rows), 0, 1, 2)

        for radio in (self.position_distance, self.position_map):
            radio.toggled.connect(lambda on: on and self._edited())
        for box in (self.distance_combo, self.easting_combo, self.northing_combo,
                    self.vertical_combo, self.vertical_kind_combo, self.value_combo,
                    self.quantity_combo):
            box.currentIndexChanged.connect(self._edited)
        self.crs_widget.crsChanged.connect(self._edited)
        self.log10_check.toggled.connect(self._edited)
        self.quantity_name.editingFinished.connect(self._edited)
        self.unit_edit.editingFinished.connect(self._edited)
        self._sync()

    # -- in and out --------------------------------------------------------------------------
    def set_columns(self, table, columns: ModelColumns, hint: str | None = GUESSED_HINT) -> None:
        """Offer ``table``'s numeric columns and show ``columns`` with ``hint`` (None keeps
        the hint shown); silent."""
        self._busy = True
        try:
            numeric = [c for c in range(table.n_columns) if table.is_numeric(c)]
            for box, chosen in ((self.distance_combo, columns.distance),
                                (self.easting_combo, columns.easting),
                                (self.northing_combo, columns.northing),
                                (self.vertical_combo, columns.vertical),
                                (self.value_combo, columns.value)):
                box.clear()
                box.addItem("(none)", None)
                for c in numeric:
                    box.addItem(table.names[c], c)
                box.setCurrentIndex(max(0, box.findData(chosen)))
            (self.position_map if columns.position == "map" else
             self.position_distance).setChecked(True)
            self.crs_widget.setCrs(crs_of(columns.crs, self.store_crs))
            self.vertical_kind_combo.setCurrentIndex(
                max(0, self.vertical_kind_combo.findData(columns.vertical_kind)))
            other = columns.quantity != "resistivity"
            self.quantity_combo.setCurrentIndex(self.quantity_combo.findData("" if other
                                                                             else "resistivity"))
            self.quantity_name.setText(columns.quantity if other else "")
            self.unit_edit.setText(columns.unit if other else "")
            self.log10_check.setChecked(columns.log10)
            if hint is not None:
                if columns.position == "map" and columns.crs == WGS84:
                    hint += DEGREES_HINT
                self.hint_label.setText(hint)
        finally:
            self._busy = False
        self._sync()

    def columns(self) -> ModelColumns:
        crs = self.crs_widget.crs()
        crs_text = "" if crs.authid() == self.store_crs else \
            (crs.authid() or ("WKT:" + crs.toWkt() if crs.isValid() else ""))
        resistivity = self.quantity_combo.currentData() == "resistivity"
        return ModelColumns(
            position="map" if self.position_map.isChecked() else "distance",
            distance=self.distance_combo.currentData(),
            easting=self.easting_combo.currentData(),
            northing=self.northing_combo.currentData(), crs=crs_text,
            vertical=self.vertical_combo.currentData(),
            vertical_kind=self.vertical_kind_combo.currentData() or "",
            value=self.value_combo.currentData(),
            quantity="resistivity" if resistivity else self.quantity_name.text().strip(),
            unit="ohm.m" if resistivity else self.unit_edit.text().strip(),
            log10=self.log10_check.isChecked())

    def roles(self) -> dict[int, str]:
        """Role word per assigned column, for the preview's second header line."""
        c = self.columns()
        value = "resistivity" if c.quantity == "resistivity" else (c.quantity or "value")
        pairs = ([("easting", c.easting), ("northing", c.northing)] if c.position == "map"
                 else [("distance", c.distance)])
        pairs += [(VERTICAL_WORDS.get(c.vertical_kind, "vertical"), c.vertical),
                  (value + (" (log10)" if c.log10 else ""), c.value)]
        out: dict[int, str] = {}
        for word, col in pairs:
            if col is not None:
                out[col] = f"{out[col]}, {word}" if col in out else word
        return out

    def roles_for(self, n_columns: int) -> dict[int, str]:
        """``roles()`` with "not used" for every other column."""
        roles = self.roles()
        return {i: roles.get(i, NOT_USED) for i in range(n_columns)}

    # -- state -------------------------------------------------------------------------------
    def _sync(self) -> None:
        on_map = self.position_map.isChecked()
        other = self.quantity_combo.currentData() != "resistivity"
        for widget, shown in ((self._distance_row, not on_map), (self._map_row, on_map),
                              (self._crs_row, on_map), (self._other_row, other)):
            widget.setVisible(shown)
            self._labels[widget].setVisible(shown)

    def _edited(self, *_args) -> None:
        if self._busy:
            return
        self._sync()
        self.changed.emit()
