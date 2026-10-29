"""Small dialog for a section layer's colour scale (colormap, min, max, log)."""
from __future__ import annotations

import numpy as np
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                                 QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QPushButton,
                                 QVBoxLayout)

from ..core.colors import COLORMAPS, ColorScale

LIMIT = 1e12            # spin box range for linear scales
LOG_MIN = 0.001         # smallest minimum on a log scale (= the spin boxes' 3 decimals)


def ramp_icon(cmap: str, width: int = 64, height: int = 14) -> QIcon:
    """A horizontal swatch of ``cmap``."""
    rgba = ColorScale(cmap, 0.0, 1.0, False).rgba(np.linspace(0.0, 1.0, width))
    pix = QPixmap(width, height)
    painter = QPainter(pix)
    try:
        for x, (r, g, b, a) in enumerate(rgba.tolist()):
            painter.setPen(QColor(r, g, b, a))
            painter.drawLine(x, 0, x, height - 1)
    finally:
        painter.end()
    return QIcon(pix)


def _spin() -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setDecimals(3)
    spin.setRange(-LIMIT, LIMIT)
    spin.setKeyboardTracking(False)
    spin.setMinimumWidth(110)
    return spin


class ColorScaleDialog(QDialog):
    """Edits a ``ColorScale``; emits ``applied(ColorScale)`` on Apply and OK."""

    applied = pyqtSignal(object)

    def __init__(self, scale: ColorScale | None, values=None, unit: str = "",
                 title: str = "Colour scale", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self._values = None if values is None else np.asarray(values, dtype=float)
        scale = scale or ColorScale()

        self.cmap_combo = QComboBox()
        for name in COLORMAPS:
            self.cmap_combo.addItem(ramp_icon(name), name)
        self.cmap_combo.setCurrentText(scale.cmap)
        self.min_spin, self.max_spin = _spin(), _spin()
        if unit:
            self.min_spin.setSuffix(f" {unit}")
            self.max_spin.setSuffix(f" {unit}")
        self.log_check = QCheckBox("Logarithmic")
        self.log_check.setChecked(scale.log)
        self.log_check.toggled.connect(self._log_toggled)
        self._log_toggled(scale.log)
        self.min_spin.setValue(scale.vmin)
        self.max_spin.setValue(scale.vmax)

        self.auto_button = QPushButton("Auto")
        self.auto_button.setToolTip("2nd to 98th percentile of the layer's values")
        self.auto_button.setEnabled(self._values is not None and self._values.size > 0)
        self.auto_button.clicked.connect(self.auto)
        self.message = QLabel()
        self.message.setStyleSheet("color: #c00000;")
        self.message.hide()

        form = QFormLayout()
        form.addRow("Colour map", self.cmap_combo)
        form.addRow("Minimum", self.min_spin)
        form.addRow("Maximum", self.max_spin)
        row = QHBoxLayout()
        row.addWidget(self.log_check)
        row.addStretch(1)
        row.addWidget(self.auto_button)
        form.addRow(row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Apply
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.apply)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.message)
        layout.addWidget(buttons)

    def _log_toggled(self, log: bool) -> None:
        low = LOG_MIN if log else -LIMIT
        for spin in (self.min_spin, self.max_spin):
            spin.setMinimum(low)

    def scale(self) -> ColorScale:
        """The edited scale; raises ``ValueError`` when it is not valid."""
        return ColorScale(self.cmap_combo.currentText(), self.min_spin.value(),
                          self.max_spin.value(), self.log_check.isChecked())

    def auto(self) -> None:
        try:
            s = ColorScale.auto(self._values, log=self.log_check.isChecked(),
                                cmap=self.cmap_combo.currentText())
        except ValueError as exc:
            self._show_error(str(exc))
            return
        self.min_spin.setValue(s.vmin)
        self.max_spin.setValue(s.vmax)
        self.message.hide()

    def _show_error(self, text: str) -> None:
        self.message.setText(text)
        self.message.show()

    def apply(self) -> bool:
        try:
            scale = self.scale()
        except ValueError as exc:
            self._show_error(str(exc))
            return False
        self.message.hide()
        self.applied.emit(scale)
        return True

    def accept(self) -> None:
        if self.apply():
            super().accept()
