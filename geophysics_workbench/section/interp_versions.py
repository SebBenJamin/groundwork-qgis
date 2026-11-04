"""The interpretation version bar: freeze the current version, view frozen ones, start anew
from one. Frozen versions are read-only: while one is shown the drawing tools are disabled."""
from __future__ import annotations

from qgis.PyQt.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel, QMessageBox,
                                 QPushButton, QWidget)

DRAW_KEYS = ("line", "polygon", "point", "edit", "undo", "redo")


class VersionBar:
    def __init__(self, ctl):
        self.ctl = ctl
        self.widget = QWidget()
        row = QHBoxLayout(self.widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Version"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(160)
        row.addWidget(self.combo)
        self.freeze_button = QPushButton("Freeze…")
        self.freeze_button.setToolTip("Keep the current interpretation as a named, read-only "
                                      "version and carry on working")
        self.restore_button = QPushButton("Start from this version")
        self.restore_button.setEnabled(False)
        self.readonly_label = QLabel("Viewing frozen version – read-only")
        self.readonly_label.setStyleSheet("color: grey;")
        self.readonly_label.hide()
        for w in (self.freeze_button, self.restore_button, self.readonly_label):
            row.addWidget(w)
        self.freeze_button.clicked.connect(self.freeze)
        self.restore_button.clicked.connect(self.start_from)
        self.combo.currentIndexChanged.connect(self._selected)
        #: dialogs (tests replace them)
        self.ask_name = lambda title: _ask_name(self.widget, title)
        self.ask_restore = lambda: _ask_restore(self.widget)

    def _store(self):
        prov = self.ctl.dock.provider
        return None if prov is None else prov.store

    def refresh(self, select: str | None = None) -> None:
        store = self._store()
        self.combo.blockSignals(True)
        try:
            self.combo.clear()
            self.combo.addItem("Current", "")
            if store is not None and store.has_interpretation():
                frozen = [v for v in store.versions() if v.frozen]
                for v in sorted(frozen, key=lambda v: v.created):
                    self.combo.addItem(f"{v.name} ({v.created[:10]})", v.id)
            self.combo.setCurrentIndex(max(0, self.combo.findData(select or "")))
        finally:
            self.combo.blockSignals(False)
        self._apply_selection()

    def _selected(self, _index: int) -> None:
        self.ctl.stop()
        self.ctl.undo.clear()
        self._apply_selection()
        store = self._store()
        if store is not None and store.has_interpretation():
            prov = self.ctl.dock.provider
            self.ctl.changed(prov.interp_version_id or store.current_version().id)

    def _apply_selection(self) -> None:
        prov = self.ctl.dock.provider
        vid = self.combo.currentData() or None
        if prov is not None:
            prov.interp_version_id = vid
        frozen = vid is not None
        for key in DRAW_KEYS:
            if key in self.ctl.buttons:
                self.ctl.buttons[key].setEnabled(not frozen and (
                    key not in ("undo", "redo") or getattr(self.ctl.undo.stack,
                                                           "can" + key.capitalize())()))
        self.restore_button.setEnabled(frozen)
        self.readonly_label.setVisible(frozen)

    def freeze(self) -> None:
        store = self._store()
        if store is None:
            return
        name = self.ask_name("Name for the frozen version")
        if not name:
            return
        store.ensure_interpretation()
        store.freeze_current(name)
        self.refresh(self.combo.currentData() or "")

    def start_from(self) -> None:
        store = self._store()
        vid = self.combo.currentData()
        if store is None or not vid:
            return
        choice = self.ask_restore()
        if choice is None:
            return
        if choice == "freeze":
            name = self.ask_name("Name for the current version before replacing it")
            if not name:
                return
            store.freeze_current(name)
        store.restore_from(vid)
        self.refresh("")
        self.ctl.changed(store.current_version().id)


def _ask_name(parent, title: str) -> str | None:
    text, ok = QInputDialog.getText(parent, "Interpretation version", title)
    return text.strip() if ok and text.strip() else None


def _ask_restore(parent) -> str | None:
    box = QMessageBox(parent)
    box.setWindowTitle("Start from this version")
    box.setText("The current interpretation will be replaced by a copy of this version.")
    keep = box.addButton("Freeze current first", QMessageBox.ButtonRole.AcceptRole)
    replace = box.addButton("Replace", QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    clicked = box.clickedButton()
    return "freeze" if clicked is keep else "replace" if clicked is replace else None
