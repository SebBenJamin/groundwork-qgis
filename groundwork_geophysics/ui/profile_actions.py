"""Profile Properties and delete profile: the small dialogs (the plugin does the work and the refresh)."""
from __future__ import annotations

from qgis.PyQt.QtWidgets import QMessageBox

RENAME_TEXT = "Profile Properties…"
DELETE_TEXT = "Delete Profile…"


def move_message(name: str, counts: dict) -> str:
    return (f"Move the line of profile “{name}” to the surveyed points? Moved with it: "
            f"{counts.get('pieces', 0)} interpretation piece(s), "
            f"{counts.get('notes', 0)} field note(s). "
            "Delivered interpretation versions keep their old positions.")


def confirm_move(parent, name: str, counts: dict) -> bool:
    box = QMessageBox(QMessageBox.Icon.Question, "Profile Properties",
                      move_message(name, counts), QMessageBox.StandardButton.Cancel, parent)
    move = box.addButton("Move Line", QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return box.clickedButton() is move


def confirm_off_line(parent, warnings: list[str]) -> bool:
    """Some surveyed points lie far from the kept line: list them, ask whether to save."""
    shown = warnings[:8] + ([f"… and {len(warnings) - 8} more"] if len(warnings) > 8 else [])
    box = QMessageBox(QMessageBox.Icon.Question, "Profile Properties",
                      "These positions lie far from the profile's line and are projected "
                      "onto it:\n" + "\n".join(shown) + "\nSave them anyway?",
                      QMessageBox.StandardButton.Cancel, parent)
    save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(QMessageBox.StandardButton.Cancel)
    box.exec()
    return box.clickedButton() is save


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
