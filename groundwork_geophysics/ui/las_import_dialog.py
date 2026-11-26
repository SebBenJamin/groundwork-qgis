"""Import LAS…: a table of the chosen LAS files, each with the borehole it belongs to (guessed
from its well name, UWI or file name; changeable), and how far below the log's depth zero the
ground lies (e.g. the drill floor's height). Only files with a borehole are imported."""
from __future__ import annotations

from pathlib import Path

from qgis.gui import QgsDoubleSpinBox
from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QHeaderView, QLabel,
                                 QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..core.las_log import guess_borehole, read_las_log

READY = "Ready"
CHOOSE = "Choose a borehole"
LEAVE_OUT = "Choose a borehole…"
OFFSET_TIP = ("How far below the log's depth zero the ground is, in metres: e.g. the drill "
              "floor's height when the depths start there. 0 when they start at the ground.")
HINT = ("Each LAS file holds one well. Its curves go into one table in the Groundwork "
        "project and show in the borehole viewer, the sections and the plates.")
MAX_HEIGHT = 560


class LasImportDialog(QDialog):
    _FILE, _WELL, _BOREHOLE, _OFFSET, _CURVES, _STATUS = range(6)

    def __init__(self, paths, borehole_ids, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import LAS")
        self.ids = sorted({str(i) for i in borehole_ids})
        self.logs, self.errors = [], []
        for path in paths:
            try:
                self.logs.append(read_las_log(path))
                self.errors.append("")
            except (OSError, ValueError) as exc:
                self.logs.append(None)
                self.errors.append(str(exc))
        self.paths = [Path(p) for p in paths]
        self.table = QTableWidget(len(self.paths), 6)
        self.table.setHorizontalHeaderLabels(["File", "Well", "Borehole", "Ground below zero (m)",
                                              "Curves", "Status"])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        for row, (path, log) in enumerate(zip(self.paths, self.logs)):
            self.table.setItem(row, self._FILE, QTableWidgetItem(path.name))
            well = "" if log is None else (log.well or log.uwi)
            self.table.setItem(row, self._WELL, QTableWidgetItem(well))
            combo = QComboBox()
            combo.addItem(LEAVE_OUT, None)
            for bid in self.ids:
                combo.addItem(bid, bid)
            if log is not None:
                guess = guess_borehole(log, path.stem, self.ids)
                combo.setCurrentIndex(max(0, combo.findData(guess)) if guess else 0)
            combo.setEnabled(log is not None)
            combo.currentIndexChanged.connect(lambda _i: self._sync())
            self.table.setCellWidget(row, self._BOREHOLE, combo)
            spin = QgsDoubleSpinBox()
            spin.setRange(-1000.0, 1000.0)
            spin.setDecimals(2)
            spin.setSuffix(" m")
            spin.setClearValue(0.0)
            spin.setToolTip(OFFSET_TIP)
            spin.setEnabled(log is not None)
            self.table.setCellWidget(row, self._OFFSET, spin)
            curves = "" if log is None else ", ".join(
                f"{c.mnemonic} [{c.unit}]" if c.unit else c.mnemonic for c in log.curves)
            self.table.setItem(row, self._CURVES, QTableWidgetItem(curves))
            self.table.setItem(row, self._STATUS, QTableWidgetItem(""))
        hint = QLabel(HINT)
        hint.setWordWrap(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.import_button = buttons.addButton("Import", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.table, 1)
        layout.addWidget(buttons)
        self.resize(820, min(MAX_HEIGHT, 160 + 30 * len(self.paths)))
        self._sync()

    # -- reading what was chosen -------------------------------------------------------------
    def borehole(self, row: int) -> str | None:
        return self.table.cellWidget(row, self._BOREHOLE).currentData()

    def set_borehole(self, row: int, bid: str | None) -> None:
        combo = self.table.cellWidget(row, self._BOREHOLE)
        combo.setCurrentIndex(max(0, combo.findData(bid)))

    def set_offset(self, row: int, metres: float) -> None:
        self.table.cellWidget(row, self._OFFSET).setValue(metres)

    def status(self, row: int) -> str:
        return self.table.item(row, self._STATUS).text()

    def entries(self) -> list:
        """[(borehole id, LasLog, ground below the log's zero in m)] of the ready files."""
        return [(self.borehole(r), self.logs[r],
                 self.table.cellWidget(r, self._OFFSET).value())
                for r in range(len(self.paths))
                if self.logs[r] is not None and self.borehole(r)]

    def _sync(self) -> None:
        for row, (log, error) in enumerate(zip(self.logs, self.errors)):
            text = error if log is None else (READY if self.borehole(row) else CHOOSE)
            self.table.item(row, self._STATUS).setText(text)
            self.table.item(row, self._STATUS).setToolTip(text)
        ready = len(self.entries())
        self.import_button.setEnabled(ready > 0)
        self.import_button.setText(f"Import {ready} File(s)" if ready else "Import")
