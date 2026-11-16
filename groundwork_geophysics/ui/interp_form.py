"""Attribute form for an interpretation feature: open classification, never a fixed list."""
from __future__ import annotations

import copy

from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                                 QLineEdit)

from ..core.interpretation import CONFIDENCE, InterpFeature


class InterpForm(QDialog):
    def __init__(self, parent, feature: InterpFeature, suggestions: list[str],
                 names_in_use: set[str]):
        super().__init__(parent)
        self.setWindowTitle("Interpretation")
        self._feature = feature
        self._names = {x.strip().lower() for x in names_in_use if x}
        self.type_combo = QComboBox()
        self.type_combo.setEditable(True)
        self.type_combo.addItems(suggestions)
        self.type_combo.setEditText(feature.type)
        self.type_combo.setToolTip("Any text; the list only suggests types already used")
        self.name_edit = QLineEdit(feature.name)
        self.name_edit.setPlaceholderText("e.g. Clay A")
        self.name_edit.setToolTip("Any text; drawn as the label on the section")
        self.name_warning = QLabel("This name is already used by another feature.")
        self.name_warning.setStyleSheet("color: #b06000;")
        self.name_edit.textChanged.connect(self._check_name)
        self.confidence = QComboBox()
        self.confidence.addItems(("",) + CONFIDENCE)
        self.confidence.setCurrentText(feature.confidence)
        self.note = QLineEdit(feature.note)
        form = QFormLayout(self)
        form.addRow("Type", self.type_combo)
        form.addRow("Name", self.name_edit)
        form.addRow("", self.name_warning)
        form.addRow("Confidence", self.confidence)
        form.addRow("Note", self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._check_name(feature.name)

    def _check_name(self, text: str) -> None:
        own = self._feature.name.strip().lower()
        t = text.strip().lower()
        self.name_warning.setVisible(bool(t) and t != own and t in self._names)

    def feature(self) -> InterpFeature:
        f = copy.deepcopy(self._feature)
        f.type = self.type_combo.currentText().strip()
        f.name = self.name_edit.text().strip()
        f.confidence = self.confidence.currentText()
        f.note = self.note.text().strip()
        return f


def ask_feature(parent, feature, suggestions, names_in_use) -> InterpFeature | None:
    form = InterpForm(parent, feature, suggestions, names_in_use)
    return form.feature() if form.exec() == QDialog.DialogCode.Accepted else None
