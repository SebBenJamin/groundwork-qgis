"""Rename and delete profiles: the small dialogs (the plugin does the work and the refresh)."""
from __future__ import annotations

from qgis.PyQt.QtWidgets import QInputDialog, QLineEdit, QMessageBox

RENAME_TEXT = "Rename Profile…"
DELETE_TEXT = "Delete Profile…"


def ask_new_name(parent, current: str) -> str | None:
    """The new name, or None when cancelled."""
    name, ok = QInputDialog.getText(parent, "Rename Profile", "Profile name",
                                    QLineEdit.EchoMode.Normal, current)
    return name if ok else None


def delete_message(name: str, counts: dict) -> str:
    return (f"Delete profile “{name}”? Also removed from the workbench: "
            f"{counts.get('stations', 0)} station(s), "
            f"{counts.get('datasets', 0)} model link(s), "
            f"{counts.get('pieces', 0)} interpretation piece(s), "
            f"{counts.get('notes', 0)} field note(s). "
            "Your data files and layers are not touched.")


def confirm_delete(parent, name: str, counts: dict) -> bool:
    box = QMessageBox(QMessageBox.Icon.Warning, "Delete Profile", delete_message(name, counts),
                      QMessageBox.StandardButton.Cancel, parent)
    delete = box.addButton("Delete", QMessageBox.ButtonRole.DestructiveRole)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return box.clickedButton() is delete
