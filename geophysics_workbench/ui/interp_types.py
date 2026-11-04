"""Types dialog: the interpretation types in use, renamed (or merged) everywhere at once."""
from __future__ import annotations

from typing import Callable

from qgis.PyQt.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QInputDialog,
                                 QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)


class TypesDialog(QDialog):
    def __init__(self, parent, counts_fn: Callable[[], dict[str, int]],
                 rename: Callable[[str, str], int]):
        super().__init__(parent)
        self.setWindowTitle("Interpretation types")
        self._counts_fn, self._rename = counts_fn, rename
        #: asks for the new name of ``old``; None cancels. Tests replace it.
        self.ask_text = self._ask_text
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Type", "Features"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        rename_button = QPushButton("Rename…")
        rename_button.setToolTip("Rename this type in every feature of the current version. "
                                 "A name already in use merges the two types.")
        rename_button.clicked.connect(self.rename_selected)
        self.table.doubleClicked.connect(lambda _i: self.rename_selected())
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.table)
        lay.addWidget(rename_button)
        lay.addWidget(buttons)
        self.refresh()

    def refresh(self) -> None:
        counts = self._counts_fn()
        names = sorted(counts, key=str.lower)
        self.table.setRowCount(len(names))
        for r, name in enumerate(names):
            self.table.setItem(r, 0, QTableWidgetItem(name))
            self.table.setItem(r, 1, QTableWidgetItem(str(counts[name])))

    def row_of(self, name: str) -> int:
        return next((r for r in range(self.table.rowCount())
                     if self.table.item(r, 0).text() == name), -1)

    def rename_selected(self) -> None:
        rows = {i.row() for i in self.table.selectedIndexes()}
        if not rows:
            return
        old = self.table.item(min(rows), 0).text()
        new = self.ask_text(old)
        if new is None or not new.strip() or new.strip() == old:
            return
        self._rename(old, new.strip())
        self.refresh()

    def _ask_text(self, old: str) -> str | None:
        text, ok = QInputDialog.getText(self, "Rename type", f"New name for “{old}”:",
                                        text=old)
        return text if ok else None
