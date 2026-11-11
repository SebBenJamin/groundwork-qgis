"""Small dialog for a section layer's colour scale (colormap, min, max, log)."""
from __future__ import annotations

import numpy as np
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                                 QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                                 QLineEdit, QPushButton, QRadioButton, QVBoxLayout)

from ..core.colors import ColorScale

LIMIT = 1e12            # spin box range for linear scales
LOG_MIN = 0.001         # smallest minimum on a log scale (= the spin boxes' 3 decimals)


def ramp_icon(scale, width: int = 64, height: int = 14) -> QIcon:
    """A horizontal swatch of a ``ColorScale`` (or an old colour-map name)."""
    from dataclasses import replace
    if isinstance(scale, str):
        base = ColorScale(scale, 0.0, 1.0, False)
    else:
        base = replace(scale, vmin=0.0, vmax=1.0, log=False)
    rgba = base.rgba(np.linspace(0.0, 1.0, width))
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
        self._unit = unit
        scale = scale or ColorScale()

        # QGIS's own colour ramp button (QGIS ramps, the user's ramps, inverted, edit);
        # the scale changes to the chosen ramp only when the user picks one
        from qgis.gui import QgsColorRampButton

        from .ramps import scale_ramp
        self._scale = scale
        self.ramp_button = QgsColorRampButton()
        self.ramp_button.setShowNull(False)
        self.ramp_button.setColorRamp(scale_ramp(scale))
        self.ramp_button.setToolTip("Colour ramp: click for the QGIS ramps (and your own)")
        self._ramp_changed = False
        self.ramp_button.colorRampChanged.connect(self._ramp_picked)
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
        form.addRow("Colour ramp", self.ramp_button)
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

    def _mode_changed(self) -> None:
        group = getattr(self, "contours_group", None)
        if group is not None:
            group.setEnabled("contours" in (self.mode_combo.currentData() or ""))

    def _step_unit(self) -> None:
        if hasattr(self, "step_spin"):
            self.step_spin.setSuffix(" decades" if self.log_check.isChecked()
                                     else (f" {self._unit}" if self._unit else ""))

    def _ramp_picked(self, *_args) -> None:
        self._ramp_changed = True

    def scale(self) -> ColorScale:
        """The edited scale; raises ``ValueError`` when it is not valid."""
        from .ramps import with_ramp
        old = self._scale
        scale = ColorScale(old.cmap, self.min_spin.value(), self.max_spin.value(),
                           self.log_check.isChecked(), old.ramp, old.lut)
        if self._ramp_changed and self.ramp_button.colorRamp() is not None:
            scale = with_ramp(scale, self.ramp_button.colorRamp())
        return scale

    def auto(self) -> None:
        try:
            s = ColorScale.auto(self._values, log=self.log_check.isChecked(),
                                cmap=self._scale.cmap)
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


SHOWN_TEXT = {"misfit": "Misfit (calculated − measured) / measured",
              "measured": "Measured apparent resistivity",
              "calculated": "Calculated apparent resistivity (model response)"}
MODE_TEXT = {"points": "Points (one per reading)", "cells": "Cells (as inverted)",
             "smooth": "Smooth colour field",
             "contours": "Contours", "smooth+contours": "Smooth field + contours"}


class DisplayDialog(ColorScaleDialog):
    """Everything about how one section layer is drawn: colour scale, display mode,
    contours and coverage fade. Emits ``applied_style(LayerStyle)`` on Apply and OK."""

    applied_style = pyqtSignal(object)

    def __init__(self, parent, layer):
        from ..core.gridding import default_threshold
        from .data import DISPLAY_MODES, READINGS_MODES, layer_name
        from .readout import unit_label
        mesh = layer.mesh
        super().__init__(layer.style.scale, None if mesh is None else mesh.values,
                         unit_label(layer.dataset.unit), f"Display: {layer_name(layer.dataset)}",
                         parent)
        self._style = layer.style
        style = layer.style
        coverage = None if mesh is None else getattr(mesh, "coverage", None)

        readings = None if mesh is None else getattr(mesh, "readings", None)
        self._readings = readings
        display = QGroupBox("Display")
        form = QFormLayout(display)
        self.shown_combo = QComboBox()
        self._shown_before = None
        if readings is not None:
            for key in ("misfit", "measured", "calculated"):
                self.shown_combo.addItem(SHOWN_TEXT[key], key)
                if key != "measured" and not readings.has_calculated:
                    self.shown_combo.model().item(self.shown_combo.count() - 1).setEnabled(False)
            shown = style.shown
            if shown not in ("misfit", "measured", "calculated") or (
                    shown != "measured" and not readings.has_calculated):
                shown = "misfit" if readings.has_calculated else "measured"
            self._shown_before = shown
            self.shown_combo.setCurrentIndex(self.shown_combo.findData(shown))
        form.addRow("Show", self.shown_combo)
        if readings is None:
            form.setRowVisible(self.shown_combo, False)
        self.mode_combo = QComboBox()
        for mode in (READINGS_MODES if readings is not None else DISPLAY_MODES):
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
        if style.contour_step is not None:
            self.step_spin.setValue(style.contour_step)
        else:                       # a sensible start: 4 per decade, or about 8 steps
            from ..core.gridding import _nice
            sc = style.scale
            self.step_spin.setValue(0.25 if sc is None or sc.log
                                    else _nice((sc.vmax - sc.vmin) / 8))
        self.auto_step.setChecked(style.contour_step is None)
        self.auto_step.toggled.connect(lambda on: self.step_spin.setEnabled(
            not on and self.auto_step.isEnabled()))
        self.step_spin.setEnabled(style.contour_step is not None)
        form.addRow(self.auto_step)
        form.addRow("Spacing", self.step_spin)
        from ..core.numbers import levels_text
        tip = ("In the model's unit (e.g. Ω·m), separated by “;”. Major levels get a label. "
               "Leave both empty for automatic levels.")
        self.major_edit = QLineEdit(levels_text(style.contour_major))
        self.major_edit.setPlaceholderText("e.g. 10;30;100;300")
        self.minor_edit = QLineEdit(levels_text(style.contour_minor))
        self.minor_edit.setPlaceholderText("e.g. 20;50;200")
        for edit in (self.major_edit, self.minor_edit):
            edit.setToolTip(tip)
            edit.textChanged.connect(self._levels_typed)
        form.addRow("Major levels", self.major_edit)
        form.addRow("Minor levels", self.minor_edit)
        self._step_tip = self.step_spin.toolTip()
        self._levels_typed()
        self.contours_group = contours
        # contour settings only matter when contours are drawn; the spacing's unit follows
        # the scale (decades on a logarithmic one)
        self.mode_combo.currentIndexChanged.connect(lambda _i: self._mode_changed())
        self.log_check.toggled.connect(lambda _on: self._step_unit())
        self._mode_changed()
        self._step_unit()

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

    def _levels_typed(self, *_args) -> None:
        """Typed levels replace the spacing: switch it off (saying why) while any are typed."""
        typed = bool(self.major_edit.text().strip() or self.minor_edit.text().strip())
        self.auto_step.setEnabled(not typed)
        self.step_spin.setEnabled(not typed and not self.auto_step.isChecked())
        tip = "Not used while levels are typed." if typed else self._step_tip
        self.step_spin.setToolTip(tip)
        self.auto_step.setToolTip("Not used while levels are typed." if typed else "")

    def style(self):
        """The edited LayerStyle; raises ``ValueError`` when the scale or a typed contour
        level is not valid."""
        from dataclasses import replace

        from ..core.numbers import parse_levels
        major = parse_levels(self.major_edit.text())
        minor = parse_levels(self.minor_edit.text())
        shown = self.shown_combo.currentData() if self._readings is not None else \
            self._style.shown
        changed = self._readings is not None and shown != self._shown_before
        return replace(
            self._style, shown=shown,
            scale=None if changed else self.scale(),      # a new value: automatic scale
            mode=self.mode_combo.currentData(),
            grid_cell=None if self.auto_cell.isChecked() else self.cell_spin.value(),
            contour_step=None if self.auto_step.isChecked() else self.step_spin.value(),
            contour_major=major, contour_minor=minor,
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
