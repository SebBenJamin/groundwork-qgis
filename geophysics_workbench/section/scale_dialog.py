"""Small dialog for a section layer's colour scale (colormap, min, max, log)."""
from __future__ import annotations

import numpy as np
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                                 QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                                 QPushButton, QRadioButton, QVBoxLayout)

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


MODE_TEXT = {"cells": "Cells (as inverted)", "smooth": "Smooth colour field",
             "contours": "Contours", "smooth+contours": "Smooth field + contours"}


class DisplayDialog(ColorScaleDialog):
    """Everything about how one section layer is drawn: colour scale, display mode,
    contours and coverage fade. Emits ``applied_style(LayerStyle)`` on Apply and OK."""

    applied_style = pyqtSignal(object)

    def __init__(self, parent, layer):
        from ..core.gridding import default_threshold
        from .data import DISPLAY_MODES, layer_name
        from .readout import unit_label
        mesh = layer.mesh
        super().__init__(layer.style.scale, None if mesh is None else mesh.values,
                         unit_label(layer.dataset.unit), f"Display: {layer_name(layer.dataset)}",
                         parent)
        self._style = layer.style
        style = layer.style
        coverage = None if mesh is None else getattr(mesh, "coverage", None)

        display = QGroupBox("Display")
        form = QFormLayout(display)
        self.mode_combo = QComboBox()
        for mode in DISPLAY_MODES:
            self.mode_combo.addItem(MODE_TEXT[mode], mode)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(style.mode)))
        form.addRow("Draw as", self.mode_combo)
        self.auto_cell = QCheckBox("Automatic")
        self.cell_spin = QDoubleSpinBox()
        self.cell_spin.setRange(0.01, 1000.0)
        self.cell_spin.setDecimals(2)
        self.cell_spin.setSuffix(" m")
        self.cell_spin.setValue(style.grid_cell or 0.5)
        self.auto_cell.setChecked(style.grid_cell is None)
        self.auto_cell.toggled.connect(lambda on: self.cell_spin.setEnabled(not on))
        self.cell_spin.setEnabled(style.grid_cell is not None)
        row = QHBoxLayout()
        row.addWidget(self.cell_spin)
        row.addWidget(self.auto_cell)
        form.addRow("Grid cell", row)

        contours = QGroupBox("Contours")
        form = QFormLayout(contours)
        self.auto_step = QCheckBox("Automatic (1-2-5 per decade, or nice steps)")
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.001, 1e6)
        self.step_spin.setDecimals(3)
        self.step_spin.setToolTip("On a logarithmic scale in decades (0.25 = four lines per "
                                  "decade), otherwise in the layer's unit")
        self.step_spin.setValue(style.contour_step or 0.25)
        self.auto_step.setChecked(style.contour_step is None)
        self.auto_step.toggled.connect(lambda on: self.step_spin.setEnabled(not on))
        self.step_spin.setEnabled(style.contour_step is not None)
        form.addRow(self.auto_step)
        form.addRow("Spacing", self.step_spin)

        self.coverage_group = QGroupBox("Coverage")
        form = QFormLayout(self.coverage_group)
        self.fade_check = QCheckBox("Fade where coverage is low")
        self.fade_check.setChecked(style.fade_coverage)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(-1e6, 1e6)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setToolTip("In the file's coverage units (often log10)")
        threshold = style.coverage_threshold
        if threshold is None and coverage is not None:
            threshold = default_threshold(coverage)
        self.threshold_spin.setValue(0.0 if threshold is None else threshold)
        self.fade_radio = QRadioButton("Fade")
        self.blank_radio = QRadioButton("Blank")
        (self.blank_radio if style.fade_mode == "blank" else self.fade_radio).setChecked(True)
        row = QHBoxLayout()
        row.addWidget(self.fade_radio)
        row.addWidget(self.blank_radio)
        row.addStretch(1)
        form.addRow(self.fade_check)
        form.addRow("Below", self.threshold_spin)
        form.addRow(row)
        if coverage is None:
            self.coverage_group.setEnabled(False)
            self.coverage_group.setToolTip("This model file has no coverage or sensitivity")

        layout = self.layout()
        for i, box in enumerate((display, contours, self.coverage_group)):
            layout.insertWidget(1 + i, box)

    def style(self):
        """The edited LayerStyle; raises ``ValueError`` when the scale is not valid."""
        from dataclasses import replace
        return replace(
            self._style, scale=self.scale(), mode=self.mode_combo.currentData(),
            grid_cell=None if self.auto_cell.isChecked() else self.cell_spin.value(),
            contour_step=None if self.auto_step.isChecked() else self.step_spin.value(),
            fade_coverage=self.fade_check.isChecked() and self.coverage_group.isEnabled(),
            coverage_threshold=(self.threshold_spin.value() if self.coverage_group.isEnabled()
                                else self._style.coverage_threshold),
            fade_mode="blank" if self.blank_radio.isChecked() else "fade")

    def apply(self) -> bool:
        try:
            style = self.style()
        except ValueError as exc:
            self._show_error(str(exc))
            return False
        self.message.hide()
        self.applied.emit(style.scale)
        self.applied_style.emit(style)
        return True
