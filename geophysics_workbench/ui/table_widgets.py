"""Widgets shared by the dialogs that read free-form text tables: the File Format group
(delimiter, skipped lines, header row, decimal comma) and the preview table whose second
header row names each column's role."""
from __future__ import annotations

from qgis.gui import QgsCollapsibleGroupBox, QgsSpinBox
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGridLayout, QLabel,
                                 QTableWidget, QTableWidgetItem)

from ..readers.texttable import TableOptions, TextTable

DELIMITER_ITEMS = (("Detect", "detect"), ("Comma", "comma"), ("Semicolon", "semicolon"),
                   ("Tab", "tab"), ("Space", "space"))
DETECT_TIP = ("With Detect, a comma is a decimal point unless it separates the columns. "
              "Choose the delimiter to set this yourself.")


class TableOptionsBox(QgsCollapsibleGroupBox):
    """How a text table is read. ``changed`` follows every edit by the user;
    ``set_options`` is silent."""

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__("File Format", parent)
        self.setSaveCollapsedState(False)
        self.delimiter_combo = QComboBox()
        for label, value in DELIMITER_ITEMS:
            self.delimiter_combo.addItem(label, value)
        self.skip_spin = QgsSpinBox()
        self.skip_spin.setRange(0, 10_000)
        self.skip_spin.setClearValue(0)
        self.skip_spin.setToolTip("Lines dropped at the top of the file before the table")
        self.header_check = QCheckBox("First row holds column names")
        self.decimal_check = QCheckBox("Decimal comma")
        grid = QGridLayout(self)
        grid.addWidget(QLabel("Delimiter"), 0, 0)
        grid.addWidget(self.delimiter_combo, 0, 1)
        grid.addWidget(QLabel("Skip lines"), 0, 2)
        grid.addWidget(self.skip_spin, 0, 3)
        grid.addWidget(self.header_check, 1, 0, 1, 2)
        grid.addWidget(self.decimal_check, 1, 2, 1, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.set_options(TableOptions())
        self.delimiter_combo.currentIndexChanged.connect(self._edited)
        self.skip_spin.valueChanged.connect(self._edited)
        self.header_check.toggled.connect(self._edited)
        self.decimal_check.toggled.connect(self._edited)

    def options(self) -> TableOptions:
        return TableOptions(delimiter=self.delimiter_combo.currentData(),
                            skip=self.skip_spin.value(), header=self.header_check.isChecked(),
                            decimal_comma=self.decimal_check.isChecked())

    def set_options(self, o: TableOptions) -> None:
        widgets = (self.delimiter_combo, self.skip_spin, self.header_check, self.decimal_check)
        for w in widgets:
            w.blockSignals(True)
        try:
            self.delimiter_combo.setCurrentIndex(max(0, self.delimiter_combo.findData(o.delimiter)))
            self.skip_spin.setValue(int(o.skip))
            self.header_check.setChecked(bool(o.header))
            self.decimal_check.setChecked(bool(o.decimal_comma))
        finally:
            for w in widgets:
                w.blockSignals(False)
        self._sync_decimal()

    def _sync_decimal(self) -> None:
        detect = self.delimiter_combo.currentData() == "detect"
        self.decimal_check.setEnabled(not detect)
        self.decimal_check.setToolTip(DETECT_TIP if detect else
                                      "Read “2,5” as two and a half")

    def _edited(self, *_args) -> None:
        self._sync_decimal()
        self.changed.emit()


class PreviewTable(QTableWidget):
    """The first rows of a text table as read, read-only; each column header shows the
    column name and, in a second line, its role. Row headers are the file's line numbers."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.setWordWrap(False)

    def show(self, table: TextTable | None = None, roles: dict[int, str] | None = None,
             max_rows: int = 20) -> None:
        """Fill the preview with ``table`` (called without a table: QWidget.show)."""
        if table is None:
            super().show()
            return
        roles = roles or {}
        rows = min(table.n_rows, max_rows)
        self.clear()
        self.setColumnCount(table.n_columns)
        self.setRowCount(rows)
        self.setHorizontalHeaderLabels([f"{name}\n{roles[i]}" if roles.get(i) else name
                                        for i, name in enumerate(table.names)])
        self.setVerticalHeaderLabels([str(n) for n in table.line_numbers[:rows]])
        for r in range(rows):
            for c, text in enumerate(table.cells[r]):
                self.setItem(r, c, QTableWidgetItem(text))
        self.resizeColumnsToContents()
