"""Reference Height: the height of one point on a profile without heights, so its section is
drawn at real elevations (the surface passes through it)."""
from __future__ import annotations

import math

import numpy as np
from qgis.PyQt.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                                 QLineEdit, QPushButton, QRadioButton, QSpinBox, QVBoxLayout,
                                 QWidget)

from ..core.numbers import fmt, fmt_trim, parse

TITLE = "Reference Height"
INTRO = ("Type the height of one point on the profile. The section, its models and the "
         "interpretation drawn on it move to real elevations through that point.")
#: where derived electrode positions come from, said next to the number
SOURCES = {"readings": "from the data file", "spacing": "from the typed spacing"}


class ReferenceHeightDialog(QDialog):
    """Position by electrode (or station) number or by distance along the profile, and the
    height there. ``electrodes`` (``core.layout.Electrodes``) may be None; guessed positions
    are not offered (a guess is never stored). ``current`` is the stored
    ``{"s": chainage, "z": height}`` or None; with one, a "Remove" button clears it."""

    def __init__(self, electrodes, length: float, current: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        self.length = max(float(length), 0.0)
        self.removed = False
        if electrodes is not None and (electrodes.kind == "guessed"
                                       or not len(electrodes.numbers)):
            electrodes = None
        self._numbers = self._chainage = None
        if electrodes is not None:
            order = np.argsort(np.asarray(electrodes.numbers), kind="stable")
            self._numbers = np.asarray(electrodes.numbers, dtype=float)[order]
            self._chainage = np.asarray(electrodes.chainage, dtype=float)[order]
        word = "Station" if electrodes is not None and electrodes.kind == "imported" \
            else "Electrode"

        intro = QLabel(INTRO)
        intro.setWordWrap(True)
        self.by_electrode = QRadioButton(word)
        self.electrode = QSpinBox()
        self.at_label = QLabel()
        self.by_distance = QRadioButton("Distance along the profile (m)")
        self.distance_label = QLabel("Distance along the profile (m)")
        self.distance_edit = QLineEdit()
        self.distance_edit.setPlaceholderText(f"0 to {fmt_trim(self.length, 1)}")
        self.height_edit = QLineEdit()
        self.height_edit.setPlaceholderText(f"e.g. {fmt(57.5, 1)}")
        self.height_edit.setToolTip("Height above sea level, in the project's height system")
        self.message = QLabel()
        self.message.setWordWrap(True)

        form = QFormLayout()
        if electrodes is None:
            # one way to give the position: a plain label, no choice to make
            for radio in (self.by_electrode, self.by_distance):
                radio.setParent(self)
                radio.hide()
            self.by_distance.setChecked(True)
            form.addRow(self.distance_label, self.distance_edit)
        else:
            self.distance_label.setParent(self)
            self.distance_label.hide()
            electrode_row = QWidget()
            row = QHBoxLayout(electrode_row)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(self.electrode)
            row.addWidget(self.at_label, 1)
            form.addRow(self.by_electrode, electrode_row)
            form.addRow(self.by_distance, self.distance_edit)
            lo, hi = int(self._numbers.min()), int(self._numbers.max())
            self.electrode.setRange(lo, hi)
            self.electrode.setValue(lo)
            source = SOURCES.get(electrodes.kind)
            if source:
                self.by_electrode.setToolTip(f"{word} positions {source}")
            self.by_electrode.setChecked(True)
        form.addRow(QLabel("Height (m)"), self.height_edit)

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                        | QDialogButtonBox.StandardButton.Cancel)
        self.remove_button = None
        if current is not None:
            # apart from OK/Cancel: it throws the reference away
            self.remove_button = QPushButton("Remove")
            self.remove_button.setToolTip("Remove the reference height: the section is drawn "
                                          "in depth below the surface again")
            self.remove_button.clicked.connect(self._remove)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addStretch(1)
        bottom = QHBoxLayout()
        if self.remove_button is not None:
            bottom.addWidget(self.remove_button)
        bottom.addStretch(1)
        bottom.addWidget(self.buttons)
        layout.addLayout(bottom)

        if current is not None:
            self._fill(current)
        for signal in (self.by_electrode.toggled, self.electrode.valueChanged,
                       self.distance_edit.textChanged, self.height_edit.textChanged):
            signal.connect(self._check)
        self._check()

    # -- values ------------------------------------------------------------------------------
    def _fill(self, current: dict) -> None:
        try:
            s, z = float(current["s"]), float(current["z"])
        except (KeyError, TypeError, ValueError):
            return
        self.height_edit.setText(fmt_trim(z, 3))
        if self._chainage is not None:
            hit = np.flatnonzero(np.abs(self._chainage - s) < 1e-6)
            if hit.size:
                self.electrode.setValue(int(self._numbers[hit[0]]))
                self.by_electrode.setChecked(True)
                return
        self.distance_edit.setText(fmt_trim(s, 3))
        self.by_distance.setChecked(True)

    def _electrode_chainage(self) -> float:
        return float(np.interp(self.electrode.value(), self._numbers, self._chainage))

    def _read(self) -> tuple[tuple[float, float] | None, str]:
        """((chainage, height), "") or (None, what to fix)."""
        if self.by_electrode.isChecked() and self._numbers is not None:
            s = self._electrode_chainage()
        else:
            try:
                s = parse(self.distance_edit.text())
            except ValueError:
                s = math.nan
            if not (math.isfinite(s) and -1e-9 <= s <= self.length + 1e-9):
                return None, (f"Type a distance between 0 and {fmt_trim(self.length, 1)} m "
                              "along the profile.")
        try:
            z = parse(self.height_edit.text())
        except ValueError:
            z = math.nan
        if not math.isfinite(z):
            return None, "Type the height in metres."
        return (min(max(float(s), 0.0), self.length), float(z)), ""

    def value(self) -> tuple[float, float] | None:
        """(chainage along the profile, height); None while the input is incomplete."""
        return self._read()[0]

    def _check(self, *_args) -> None:
        by_electrode = self.by_electrode.isChecked() and self._numbers is not None
        self.electrode.setEnabled(by_electrode)
        self.at_label.setEnabled(by_electrode)
        self.distance_edit.setEnabled(not by_electrode)
        if self._numbers is not None:
            self.at_label.setText(f"at {fmt(self._electrode_chainage(), 1)} m along the profile")
        value, problem = self._read()
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(value is not None)
        self.message.setText(problem)

    def _remove(self) -> None:
        self.removed = True
        self.accept()


def ask_reference_height(parent, electrodes, length: float, current: dict | None
                         ) -> tuple[float, float] | None | bool:
    """(chainage, height) to store, ``None`` when cancelled, ``False`` for "Remove"."""
    dlg = ReferenceHeightDialog(electrodes, length, current, parent)
    try:
        if not dlg.exec():
            return None
        return False if dlg.removed else dlg.value()
    finally:
        dlg.deleteLater()
