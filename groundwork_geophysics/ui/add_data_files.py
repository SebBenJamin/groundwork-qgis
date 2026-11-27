"""Add Data with several files: one row per file with the profile it goes to (guessed from
its name, ``core.file_profiles``, and changeable), the coarser cells offered for an over-fine
file, a radargram's own time zero, and whether the file is ready. The dialog's other
settings are the first file's and apply to every file."""
from __future__ import annotations

from pathlib import Path

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QGroupBox,
                                 QHBoxLayout, QHeaderView, QLabel, QTableWidget,
                                 QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.file_profiles import guess_profile

FILES_HINT = ("Format, columns and method are read from the first file and used for every "
              "file. Each file goes to the profile in its row.")
CHOOSE_PROFILE = "Choose a profile…"
NEW_PROFILE = "New profile from its coordinates"
NEW_TIP = "A new profile through the file's own map coordinates, named after the file"
READY = "Ready"
COLUMNS = ("File", "Profile", "Read as cells of", "Time zero", "Status")
MAX_TABLE_HEIGHT = 200


class FilesBox(QGroupBox):
    """The files chosen together, each with its target profile (an id, ``NEW`` or None)."""
    changed = pyqtSignal()
    NEW = "__new__"
    TIME_ZERO, STATUS = 3, 4                # columns

    def __init__(self, parent=None):
        super().__init__("Files", parent)
        self.setObjectName("files_box")
        self._paths: list[str] = []
        self._profiles: list[tuple[str, str]] = []
        self._on_map = False
        hint = QLabel(FILES_HINT)
        hint.setWordWrap(True)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setObjectName("files_table")
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.verticalHeader().hide()
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)   # fitted to
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)   # its widgets
        header.setSectionResizeMode(self.TIME_ZERO, QHeaderView.ResizeMode.ResizeToContents)
        header.setStretchLastSection(True)
        self.table.setColumnHidden(self.TIME_ZERO, True)    # radargrams only
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.table)

    # -- filling -----------------------------------------------------------------------------
    def set_files(self, paths: list[str], profiles: list[tuple[str, str]],
                  on_map: bool) -> None:
        """One row per file, its profile guessed from its name (a map file without one: a
        new profile)."""
        self._paths, self._profiles, self._on_map = [str(p) for p in paths], list(profiles), \
            on_map
        self.table.setRowCount(len(self._paths))
        for row, path in enumerate(self._paths):
            item = QTableWidgetItem(Path(path).name)
            item.setToolTip(path)
            self.table.setItem(row, 0, item)
            combo = QComboBox()
            self._fill_combo(combo, guess_profile(Path(path).stem, self._profiles))
            combo.currentIndexChanged.connect(lambda *_a: self.changed.emit())
            self.table.setCellWidget(row, 1, combo)
            self.table.setCellWidget(row, 2, self._cells_cell())
            self.table.setItem(row, self.TIME_ZERO, QTableWidgetItem(""))
            self.table.setItem(row, self.STATUS, QTableWidgetItem(""))
        self._fit()

    def _cells_cell(self) -> QWidget:
        """The "Read as cells of" cell: a ticked check box, hidden until a size is offered.
        The table shows its cell widgets again whenever it lays them out, so the box sits in
        a plain holder and only the box itself is hidden."""
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(4, 0, 4, 0)
        check = QCheckBox()
        check.setChecked(True)
        check.toggled.connect(lambda *_a: self.changed.emit())
        check.hide()
        layout.addWidget(check)
        return holder

    def _check(self, row: int) -> QCheckBox:
        return self.table.cellWidget(row, 2).findChild(QCheckBox)

    def _fit(self) -> None:
        """Columns wide enough for their combo boxes and check boxes; the table as tall as
        its rows (at most ``MAX_TABLE_HEIGHT``, then it scrolls)."""
        header = self.table.horizontalHeader()
        for column in (1, 2):
            widths = [header.sectionSizeHint(column)]
            for row in range(self.table.rowCount()):
                w = self.table.cellWidget(row, column)
                if w is not None and column == 2:
                    w = self._check(row)
                if w is not None and not w.isHidden():
                    widths.append(w.sizeHint().width() + 8)
            self.table.setColumnWidth(column, max(widths))
        rows = sum(self.table.rowHeight(r) for r in range(self.table.rowCount()))
        self.table.setFixedHeight(min(MAX_TABLE_HEIGHT, header.sizeHint().height() + rows
                                      + 2 * self.table.frameWidth() + 6))

    def _fill_combo(self, combo: QComboBox, target) -> None:
        combo.blockSignals(True)
        combo.clear()
        combo.addItem(CHOOSE_PROFILE, None)
        if self._on_map:
            combo.addItem(NEW_PROFILE, self.NEW)
            combo.setItemData(1, NEW_TIP, Qt.ItemDataRole.ToolTipRole)
        for pid, name in self._profiles:
            combo.addItem(name or pid, pid)
        if target is None and self._on_map:
            target = self.NEW
        combo.setCurrentIndex(max(0, combo.findData(target)))
        combo.blockSignals(False)

    def set_on_map(self, on_map: bool) -> None:
        """Map files may go to a new profile; files in distance along the line may not."""
        if on_map == self._on_map:
            return
        self._on_map = on_map
        for row in range(self.table.rowCount()):
            combo = self._combo(row)
            target = combo.currentData()
            self._fill_combo(combo, None if target == self.NEW else target)
        self._fit()

    # -- reading -----------------------------------------------------------------------------
    def _combo(self, row: int) -> QComboBox:
        return self.table.cellWidget(row, 1)

    def paths(self) -> list[str]:
        return list(self._paths)

    def targets(self) -> list[tuple[str, str | None]]:
        return [(path, self._combo(row).currentData()) for row, path in enumerate(self._paths)]

    def set_target(self, row: int, target) -> None:
        combo = self._combo(row)
        combo.setCurrentIndex(max(0, combo.findData(target)))

    def set_status(self, row: int, text: str) -> None:
        item = self.table.item(row, self.STATUS)
        item.setText(text)
        item.setToolTip(text)

    def status(self, row: int) -> str:
        return self.table.item(row, self.STATUS).text()

    def show_time_zero(self, shown: bool) -> None:
        """The "Time zero" column: for radargrams, each file's own."""
        self.table.setColumnHidden(self.TIME_ZERO, not shown)

    def set_time_zero(self, row: int, text: str) -> None:
        item = self.table.item(row, self.TIME_ZERO)
        if item.text() != text:
            item.setText(text)
            item.setToolTip(text)

    def time_zero_text(self, row: int) -> str:
        return self.table.item(row, self.TIME_ZERO).text()

    def set_cells(self, row: int, text: str) -> None:
        """The coarser cells offered for the file ("" when none): a ticked box with the size."""
        check = self._check(row)
        if (check.text(), not check.isHidden()) == (text, bool(text)):
            return
        check.setText(text)
        check.setToolTip("Average the file's points in blocks of this size; untick to read "
                         "every point" if text else "")
        check.setVisible(bool(text))
        self._fit()

    def cells_text(self, row: int) -> str:
        check = self._check(row)
        return "" if check.isHidden() else check.text()

    def cells_checked(self, row: int) -> bool:
        check = self._check(row)
        return not check.isHidden() and check.isChecked()
