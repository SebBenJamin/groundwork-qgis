"""The interpretation version bar: freeze the current version, view frozen ones, start anew
from one. Frozen versions are read-only: while one is shown the drawing tools are disabled."""
from __future__ import annotations

from qgis.PyQt.QtGui import QAction, QActionGroup, QPalette
from qgis.PyQt.QtWidgets import (QComboBox, QHBoxLayout, QInputDialog, QLabel, QMenu,
                                 QMessageBox, QWidget)

DRAW_KEYS = ("line", "polygon", "point", "edit", "undo", "redo", "types")


class VersionBar:
    """The Version combo (always visible) plus actions for the Interpretation menu:
    ``freeze_button``, ``restore_button`` and the ``compare_menu``."""

    def __init__(self, ctl):
        self.ctl = ctl
        self.widget = QWidget()
        row = QHBoxLayout(self.widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Version"))
        self.combo = QComboBox()
        self.combo.setMinimumWidth(160)
        row.addWidget(self.combo)
        self.freeze_button = QAction("Freeze…", self.widget)
        self.freeze_button.setToolTip("Keep the current interpretation as a named, read-only "
                                      "version and carry on working")
        self.restore_button = QAction("Start from this version", self.widget)
        self.restore_button.setEnabled(False)
        self.compare_menu = QMenu("Compare with", self.widget)
        self.compare_menu.setToolTipsVisible(True)
        self._compare_group = QActionGroup(self.widget)
        self._compare_group.setExclusive(True)
        self._compare_group.triggered.connect(self._compare_selected)
        self.freeze_button.triggered.connect(self.freeze)
        self.restore_button.triggered.connect(self.start_from)
        self.combo.currentIndexChanged.connect(self._selected)
        #: dialogs (tests replace them)
        self.ask_name = lambda title: _ask_name(self.widget, title)
        self.ask_restore = lambda: _ask_restore(self.widget)

    # -- compare (a checkable list in the Interpretation menu) -----------------------------
    def compare_items(self) -> list[str]:
        return [a.text() for a in self._compare_group.actions()]

    def compare_index(self) -> int:
        acts = self._compare_group.actions()
        return next((i for i, a in enumerate(acts) if a.isChecked()), 0)

    def set_compare(self, index: int) -> None:
        self._compare_group.actions()[index].trigger()

    def is_readonly(self) -> bool:
        return bool(self.combo.currentData())

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
        self._refresh_compare(store)
        self._apply_selection()

    def _refresh_compare(self, store) -> None:
        prov = self.ctl.dock.provider
        wanted = prov.interp_compare_version_id if prov is not None else None
        for act in self._compare_group.actions():
            self._compare_group.removeAction(act)
            act.deleteLater()
        self.compare_menu.clear()
        found = False
        for i in range(self.combo.count()):
            text = "(none)" if i == 0 else self.combo.itemText(i)
            vid = self.combo.itemData(i) or ""
            act = QAction(text, self.compare_menu)
            act.setCheckable(True)
            act.setData(vid)
            act.setChecked(vid == (wanted or ""))
            found = found or (bool(wanted) and vid == wanted)
            self._compare_group.addAction(act)
            self.compare_menu.addAction(act)
        if not found:
            self._compare_group.actions()[0].setChecked(True)
            if prov is not None and wanted:
                prov.interp_compare_version_id = None   # deleted or unknown: no comparison

    def _compare_selected(self, action) -> None:
        prov = self.ctl.dock.provider
        if prov is None:
            return
        prov.interp_compare_version_id = action.data() or None
        prov.notify_redraw()

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
        if frozen:                      # read-only: said by the combo itself, no extra label
            c = self.combo.palette().color(QPalette.ColorRole.Highlight)
            self.combo.setStyleSheet("QComboBox { background-color: rgba(%d, %d, %d, 70); }"
                                     % (c.red(), c.green(), c.blue()))
            self.combo.setToolTip("Viewing a frozen version, read-only. Choose \u201cCurrent\u201d "
                                  "to draw and edit.")
        else:
            self.combo.setStyleSheet("")
            self.combo.setToolTip("Interpretation version shown on the section")

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
