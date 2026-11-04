"""Attribute form for an interpretation feature: open classification, never a fixed list."""
from __future__ import annotations

import copy

from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                                 QLineEdit)

from ..core.interpretation import CONFIDENCE, InterpFeature


class InterpForm(QDialog):
    def __init__(self, parent, feature: InterpFeature, suggestions: list[str],
                 letters_in_use: set[str]):
        super().__init__(parent)
        self.setWindowTitle("Interpretation")
        self._feature = feature
        self._letters = {x.strip().lower() for x in letters_in_use if x}
        self.type_combo = QComboBox()
        self.type_combo.setEditable(True)
        self.type_combo.addItems(suggestions)
        self.type_combo.setEditText(feature.type)
        self.type_combo.setToolTip("Any text; the list only suggests types already used")
        self.letter = QLineEdit(feature.letter)
        self.letter.setPlaceholderText("e.g. A")
        self.letter_warning = QLabel("This letter is already used by another feature.")
        self.letter_warning.setStyleSheet("color: #b06000;")
        self.letter.textChanged.connect(self._check_letter)
        self.confidence = QComboBox()
        self.confidence.addItems(("",) + CONFIDENCE)
        self.confidence.setCurrentText(feature.confidence)
        self.note = QLineEdit(feature.note)
        form = QFormLayout(self)
        form.addRow("Type", self.type_combo)
        form.addRow("Letter", self.letter)
        form.addRow("", self.letter_warning)
        form.addRow("Confidence", self.confidence)
        form.addRow("Note", self.note)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self._check_letter(feature.letter)

    def _check_letter(self, text: str) -> None:
        own = self._feature.letter.strip().lower()
        t = text.strip().lower()
        self.letter_warning.setVisible(bool(t) and t != own and t in self._letters)

    def feature(self) -> InterpFeature:
        f = copy.deepcopy(self._feature)
        f.type = self.type_combo.currentText().strip()
        f.letter = self.letter.text().strip()
        f.confidence = self.confidence.currentText()
        f.note = self.note.text().strip()
        return f


def ask_feature(parent, feature, suggestions, letters_in_use) -> InterpFeature | None:
    form = InterpForm(parent, feature, suggestions, letters_in_use)
    return form.feature() if form.exec() == QDialog.DialogCode.Accepted else None
