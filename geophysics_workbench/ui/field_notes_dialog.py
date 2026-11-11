"""Field notes: the form for one note and the Field Notes… list of the current profile.

Every change is saved to the workbench GeoPackage right away, the map layers are rebuilt
and the section redraws (``after_change``)."""
from __future__ import annotations

from typing import Callable

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                                 QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout,
                                 QLabel, QLineEdit, QPlainTextEdit, QPushButton, QTableWidget,
                                 QTableWidgetItem, QVBoxLayout)

from ..core.field_notes import FieldNote, clamp_to_profile, note_range, stations_to_chainage
from ..core.interpretation import new_id
from ..core.numbers import fmt

COLUMNS = ("From (m)", "To (m)", "Electrodes", "Category", "Text", "Shown")


def after_change(store, provider=None, project=None) -> None:
    """Rebuild the notes' map geometry, show the map layers, redraw the section."""
    from qgis.core import QgsProject

    from .field_note_layers import add_field_note_layers, reload_field_note_layers
    store.rebuild_field_note_geometry({p.id: p.chainage for p in store.profiles()})
    project = project or QgsProject.instance()
    from .project_actions import repaint_store_layers
    try:
        add_field_note_layers(store, project)
        reload_field_note_layers(store, project)
    except ValueError:                          # store not loadable as layers: section only
        pass
    repaint_store_layers(store, project)
    if provider is not None:
        provider.notify_redraw()


def save_note(store, note: FieldNote) -> tuple[FieldNote, bool]:
    """Save ``note`` kept within its profile; returns it and whether it was clamped."""
    length = store.profile(note.profile_id).chainage.length
    note, clamped = clamp_to_profile(note, length)
    store.save_field_note(note)
    return note, clamped


def categories(store) -> list[str]:
    return sorted({n.category for n in store.field_notes() if n.category}, key=str.lower)


class NoteForm(QDialog):
    """Text, category (free, earlier ones offered) and the shown switch of one note."""

    def __init__(self, note: FieldNote, known_categories: list[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Field note")
        self._note = note
        lo, hi = note_range(note)
        where = f"{fmt(lo, 1)} m" if note.s_to is None else f"{fmt(lo, 1)}–{fmt(hi, 1)} m"
        self.text_edit = QPlainTextEdit(note.text)
        self.category_combo = QComboBox()
        self.category_combo.setEditable(True)
        self.category_combo.addItems(known_categories)
        self.category_combo.setEditText(note.category)
        self.shown_check = QCheckBox("Shown on the section and on plates")
        self.shown_check.setChecked(note.shown)
        form = QFormLayout(self)
        form.addRow("Position", QLabel(where + (f" (electrodes {note.stations})"
                                                if note.stations else "")))
        form.addRow("Text", self.text_edit)
        form.addRow("Category", self.category_combo)
        form.addRow("", self.shown_check)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def note(self) -> FieldNote:
        n = self._note
        n.text = self.text_edit.toPlainText().strip()
        n.category = self.category_combo.currentText().strip()
        n.shown = self.shown_check.isChecked()
        return n


def ask_note(parent, note: FieldNote, known_categories: list[str]) -> FieldNote | None:
    form = NoteForm(note, known_categories, parent)
    try:
        return form.note() if form.exec() else None
    finally:
        form.deleteLater()


class FieldNotesDialog(QDialog):
    """All field notes of one profile: add (by chainage or by electrodes), edit, switch
    on/off, delete."""

    def __init__(self, store, profile_id: str, on_change: Callable[[], None], parent=None):
        super().__init__(parent)
        self.store, self.profile_id, self.on_change = store, profile_id, on_change
        self.setWindowTitle(f"Field notes – {store.profile(profile_id).name}")
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.cellDoubleClicked.connect(lambda row, _c: self.edit_row(row))
        self.table.itemChanged.connect(self._item_changed)
        self.s_from, self.s_to = QDoubleSpinBox(), QDoubleSpinBox()
        for spin in (self.s_from, self.s_to):
            spin.setRange(-1.0, 1e6)
            spin.setDecimals(1)
            spin.setSpecialValueText("No end")      # -1 in "To": a note at one chainage
        self.s_to.setValue(-1.0)
        self.first_station, self.last_station = QLineEdit(), QLineEdit()
        self.first_station.setPlaceholderText("e.g. 23")
        self.last_station.setPlaceholderText("e.g. 28 (optional)")
        self.message = QLabel("")
        add_m, add_st = QPushButton("Add at Chainage…"), QPushButton("Add by Electrodes…")
        add_m.clicked.connect(self._add_by_chainage)
        add_st.clicked.connect(lambda: self.add_by_stations(
            self.first_station.text(), self.last_station.text() or None, "", "", ask=True))
        edit, delete = QPushButton("Edit…"), QPushButton("Delete")
        edit.clicked.connect(lambda: self.edit_row(self.table.currentRow()))
        delete.clicked.connect(lambda: self.delete_row(self.table.currentRow()))
        by_m = QHBoxLayout()
        for w in (QLabel("From"), self.s_from, QLabel("To"), self.s_to, add_m):
            by_m.addWidget(w)
        by_st = QHBoxLayout()
        for w in (QLabel("Electrodes"), self.first_station, QLabel("To"), self.last_station,
                  add_st):
            by_st.addWidget(w)
        row = QHBoxLayout()
        row.addWidget(edit)
        row.addWidget(delete)
        row.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addLayout(by_m)
        layout.addLayout(by_st)
        layout.addWidget(self.message)
        layout.addLayout(row)
        self.resize(760, 420)
        self.refresh()

    # -- content -------------------------------------------------------------------------------
    def notes(self) -> list[FieldNote]:
        return self.store.field_notes(self.profile_id)

    def refresh(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for n in self.notes():
            r = self.table.rowCount()
            self.table.insertRow(r)
            lo, hi = note_range(n)
            values = (f"{fmt(lo, 1)}", "" if n.s_to is None else f"{fmt(hi, 1)}", n.stations,
                      n.category, n.text.replace("\n", " / "))
            for c, v in enumerate(values):
                self.table.setItem(r, c, QTableWidgetItem(v))
            shown = QTableWidgetItem()
            shown.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            shown.setCheckState(Qt.CheckState.Checked if n.shown else Qt.CheckState.Unchecked)
            self.table.setItem(r, 5, shown)
        self.table.resizeColumnsToContents()
        self.table.blockSignals(False)

    def station_names(self):
        """(names, chainages) of the profile's stations (the set the section draws)."""
        from ..section.topography import topo_set
        sets = self.store.station_sets(self.profile_id)
        st = topo_set(sets) or (sets[0] if sets else None)
        if st is None:
            return [], []
        names = [str(int(v)) if float(v).is_integer() else str(v) for v in st.numbers]
        return names, [float(c) for c in st.chainage]

    # -- changes -------------------------------------------------------------------------------
    def _changed(self) -> None:
        self.refresh()
        self.on_change()

    def _save(self, note: FieldNote) -> None:
        _note, clamped = save_note(self.store, note)
        self.message.setText("The note reached past the profile and was cut to its ends."
                             if clamped else "")
        self._changed()

    def add_by_stations(self, first: str, last: str | None, text: str, category: str,
                        ask: bool = False) -> bool:
        names, chain = self.station_names()
        try:
            s0, s1 = stations_to_chainage(names, chain, first, last)
        except ValueError as exc:
            self.message.setText(str(exc))
            return False
        stations = first.strip() + (f"–{last.strip()}" if last and last.strip() else "")
        note = FieldNote(new_id(), self.profile_id, s0, s1, text, category, stations=stations)
        if ask:
            note = ask_note(self, note, categories(self.store))
            if note is None:
                return False
        self._save(note)
        return True

    def _add_by_chainage(self) -> None:
        s1 = None if self.s_to.value() < 0 else self.s_to.value()
        note = ask_note(self, FieldNote(new_id(), self.profile_id, self.s_from.value(), s1, ""),
                        categories(self.store))
        if note is not None:
            self._save(note)

    def edit_row(self, row: int) -> None:
        notes = self.notes()
        if not 0 <= row < len(notes):
            return
        note = ask_note(self, notes[row], categories(self.store))
        if note is not None:
            self._save(note)

    def set_shown(self, row: int, shown: bool) -> None:
        notes = self.notes()
        if 0 <= row < len(notes):
            notes[row].shown = shown
            self._save(notes[row])

    def _item_changed(self, item) -> None:
        if item.column() == 5:
            self.set_shown(item.row(), item.checkState() == Qt.CheckState.Checked)

    def delete_row(self, row: int) -> None:
        notes = self.notes()
        if 0 <= row < len(notes):
            self.store.delete_field_note(notes[row].id)
            self._changed()
