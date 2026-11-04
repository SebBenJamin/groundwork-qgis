"""Attribute form for an interpretation feature: open classification, never a fixed list."""
from __future__ import annotations

import copy

from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel,
                                 QLineEdit)

from ..core.interpretation import CONFIDENCE, InterpFeature


class InterpForm(QDialog):
    def __init__(self, parent, feature: InterpFeature, suggestions: list[str],
                 letters_in_use: set[str], existing=()):
        super().__init__(parent)
        self.setWindowTitle("Interpretation")
        self._new = feature
        self._feature = feature
        #: features a new piece may join instead of starting one (spans profiles)
        self._existing = sorted(existing, key=lambda f: (f.letter.lower(), f.type.lower()))
        self.feature_combo = QComboBox()
        self.feature_combo.addItem("New feature")
        from .interp_layers import entity_label
        for f in self._existing:
            self.feature_combo.addItem(entity_label(f))
        self.feature_combo.setToolTip("Add this piece to a feature already drawn, for example "
                                      "on another profile")
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
        form.addRow("Feature", self.feature_combo)
        if not self._existing:
            form.setRowVisible(self.feature_combo, False)
        self.feature_combo.currentIndexChanged.connect(self._picked)
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

    def _picked(self, index: int) -> None:
        self._feature = self._new if index <= 0 else self._existing[index - 1]
        f = self._feature
        self.type_combo.setEditText(f.type)
        self.letter.setText(f.letter)
        self.confidence.setCurrentText(f.confidence)
        self.note.setText(f.note)
        self._check_letter(f.letter)

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


def ask_feature(parent, feature, suggestions, letters_in_use,
                existing=()) -> InterpFeature | None:
    form = InterpForm(parent, feature, suggestions, letters_in_use, existing)
    return form.feature() if form.exec() == QDialog.DialogCode.Accepted else None
