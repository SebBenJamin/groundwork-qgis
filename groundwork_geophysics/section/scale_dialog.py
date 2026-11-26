"""Small dialog for a section layer's colour scale (colormap, min, max, log)."""
from __future__ import annotations

import numpy as np
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtGui import QColor, QIcon, QPainter, QPixmap
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                                 QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                                 QLineEdit, QPushButton, QRadioButton, QVBoxLayout)

from ..core.colors import ColorScale
from ..core.trace_section import display_values

LIMIT = 1e12            # spin box range for linear scales
MAX_HEIGHT = 580        # the Display dialog on a laptop screen at 150 % (then it scrolls)
MIN_WIDTH = 420         # its groups never squeezed below this
LOG_MIN = 0.001         # smallest minimum on a log scale (= the spin boxes' 3 decimals)
AGC_MAX_MS = 200        # the AGC window starts at a quarter of the record, at most this
#: the contour lines' colour: from the colour scale (as before), or one the user picks
FROM_SCALE_TEXT = "From the colour scale"
PICKED_COLOUR_TEXT = "One colour"
LINE_COLOUR_TIP = "The colour of every contour line of this model"
LINE_WIDTH_TIP = ("Width of the labelled (major) lines; minor levels are drawn thinner by "
                  "the same ratio as before")


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
        self.ramp_button.setObjectName("colour_ramp")
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
        self._scale_form = form
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
KERNEL_TEXT = {"thin_plate_spline": "Thin-plate", "cubic": "Cubic", "quintic": "Quintic",
               "multiquadric": "Multiquadric", "gaussian": "Gaussian"}
METHOD_TIP = ("How the smooth field and contours are made from the model's cells. Linear "
              "(mesh) follows the inversion's own cells.")
METHOD_OFF_TIP = "Used by the smooth field and contours: draw as Smooth or Contours to choose it"
ANISO_TIP = ("Horizontal over vertical correlation length: larger values follow layered "
             "ground along its layers")
ANISO_AUTO_TIP = ("Kriging: read from the model's directional variograms; the other methods: "
                  "the cells' own width over height")
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
        traces = getattr(layer, "traces", None)
        # a trace section's unit is the file's (usually none), not the dataset's default
        unit = traces.section.unit if traces is not None else layer.dataset.unit
        super().__init__(layer.style.scale, None if mesh is None else mesh.values,
                         unit_label(unit), f"Display: {layer_name(layer.dataset)}", parent)
        self._style = layer.style
        style = layer.style
        coverage = None if mesh is None else getattr(mesh, "coverage", None)

        readings = None if mesh is None else getattr(mesh, "readings", None)
        self._readings = readings
        display = QGroupBox("Display")
        display.setObjectName("display_group")
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
        self._mesh = mesh
        self._build_interpolation(form, getattr(style, "interpolation", None))

        contours = QGroupBox("Contours")
        contours.setObjectName("contours_group")
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
        self._build_line_look(form, style)
        self._step_tip = self.step_spin.toolTip()
        self._levels_typed()
        self.contours_group = contours
        # contour settings only matter when contours are drawn; the spacing's unit follows
        # the scale (decades on a logarithmic one); the interpolation when a field is drawn
        self.mode_combo.currentIndexChanged.connect(lambda _i: self._mode_changed())
        self.mode_combo.currentIndexChanged.connect(lambda _i: self._sync_interpolation())
        self.log_check.toggled.connect(lambda _on: self._step_unit())
        self._mode_changed()
        self._step_unit()

        self.coverage_group = QGroupBox("Coverage")
        self.coverage_group.setObjectName("coverage_group")
        form = QFormLayout(self.coverage_group)
        self.fade_check = QCheckBox("Fade where coverage is low")
        self.fade_check.setChecked(style.fade_coverage)
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(-1e6, 1e6)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setToolTip("In the file's coverage units (often log10)")
        threshold = style.coverage_threshold
        if threshold is None and coverage is not None:
            threshold = default_threshold(coverage, getattr(mesh, "coverage_cut", None))
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

        boxes = [display, contours, self.coverage_group]
        #: a trace layer's own controls (None for a model)
        self.amplitudes_group = self.clip_check = self.clip_spin = self.show_muted_check = None
        self._traces = getattr(layer, "traces", None)
        if self._traces is not None:
            self._layer = layer
            boxes.append(self._build_traces(style))
            for box in (display, contours, self.coverage_group):
                box.setVisible(False)           # cells, contours, coverage: models only
        from ..ui.help import add_help_button
        add_help_button(self.findChild(QDialogButtonBox),
                        "trace_display" if self._traces is not None else "display")

        # the scale and the groups scroll, the buttons stay: at most MAX_HEIGHT tall
        from qgis.PyQt.QtWidgets import QFrame, QScrollArea, QWidget
        layout = self.layout()
        self._page = QWidget()
        column = QVBoxLayout(self._page)
        column.setContentsMargins(0, 0, 0, 0)
        column.addLayout(layout.takeAt(0).layout())
        for box in boxes:
            column.addWidget(box)
        column.addStretch(1)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("display_scroll")
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setWidgetResizable(True)
        self._scroll.setWidget(self._page)
        layout.insertWidget(0, self._scroll, 1)
        self._rest = layout.sizeHint().height() - self._scroll.sizeHint().height()
        self._fit_height()

    def _build_line_look(self, form, style) -> None:
        """"Line colour" (from the colour scale, or one the user picks) and "Line width (mm)"
        of the contour lines."""
        from qgis.gui import QgsColorButton, QgsDoubleSpinBox

        from .display_render import CONTOUR_PEN_MM
        self.line_colour_combo = QComboBox()
        self.line_colour_combo.addItem(FROM_SCALE_TEXT)
        self.line_colour_combo.addItem(PICKED_COLOUR_TEXT)
        self.line_colour_button = QgsColorButton()
        self.line_colour_button.setAllowOpacity(False)
        self.line_colour_button.setColorDialogTitle("Contour line colour")
        self.line_colour_button.setToolTip(LINE_COLOUR_TIP)
        picked = getattr(style, "contour_colour", None)
        if picked:
            self.line_colour_button.setColor(QColor(picked))
        self.line_colour_combo.setCurrentIndex(1 if picked else 0)
        self.line_colour_button.setEnabled(bool(picked))
        self.line_colour_combo.currentIndexChanged.connect(
            lambda i: self.line_colour_button.setEnabled(i == 1))
        row = QHBoxLayout()
        row.addWidget(self.line_colour_combo, 1)
        row.addWidget(self.line_colour_button)
        form.addRow("Line colour", row)
        self.line_width_spin = QgsDoubleSpinBox()
        self.line_width_spin.setRange(0.05, 5.0)
        self.line_width_spin.setDecimals(2)
        self.line_width_spin.setSingleStep(0.05)
        self.line_width_spin.setClearValue(CONTOUR_PEN_MM)
        self.line_width_spin.setToolTip(LINE_WIDTH_TIP)
        width = getattr(style, "contour_width", None)
        self.line_width_spin.setValue(CONTOUR_PEN_MM if width is None else width)
        form.addRow("Line width (mm)", self.line_width_spin)

    def _line_look(self) -> tuple:
        """(contour colour or None, contour width or None) as the dialog sets them."""
        from .display_render import CONTOUR_PEN_MM
        colour = None
        if self.line_colour_combo.currentIndex() == 1:
            c = self.line_colour_button.color()
            colour = c.name() if c.isValid() else None
        width = round(self.line_width_spin.value(), 2)
        return colour, None if abs(width - CONTOUR_PEN_MM) < 1e-9 else width

    def _fit_height(self) -> None:
        """As tall as the content, at most ``MAX_HEIGHT`` (then the groups scroll)."""
        scroll = getattr(self, "_scroll", None)
        if scroll is None:
            return
        bar = scroll.verticalScrollBar().sizeHint().width()
        scroll.setMinimumWidth(max(self._page.sizeHint().width() + bar, MIN_WIDTH))
        scroll.setMinimumHeight(min(self._page.sizeHint().height(), MAX_HEIGHT - self._rest))
        self.adjustSize()

    # -- reflection sections ---------------------------------------------------------------
    def _build_traces(self, style) -> QGroupBox:
        """The clip under the colour ramp and the "Amplitudes" group (display options: the
        samples are never changed). Returns the group."""
        from dataclasses import replace

        from qgis.gui import QgsDoubleSpinBox

        from .display_render import shown_values
        section = self._traces.section
        depth = section.domain == "depth"
        self._syncing = False
        self._signed = section.signed()
        self._limits = (self._scale.vmin, self._scale.vmax)
        # values shown per gain, sampled for the limits: the drawing's when it has them
        kept = shown_values(self._layer)
        self._shown_by_gain = {} if kept is None else {replace(style.gain, show_muted=False): kept}
        self.log_check.setVisible(False)            # amplitudes: linear, clipped
        self.auto_button.setVisible(False)

        self.clip_check = QCheckBox("Clip at")
        self.clip_check.setObjectName("clip_check")
        self.clip_check.setToolTip("The limits follow the amplitudes shown: this percentile "
                                   "of their absolute values. Typing a limit turns it off.")
        self.clip_spin = QgsDoubleSpinBox()
        self.clip_spin.setObjectName("clip_spin")
        self.clip_spin.setRange(0.1, 100.0)
        self.clip_spin.setDecimals(1)
        self.clip_spin.setSingleStep(0.5)
        self.clip_spin.setSuffix(" %")
        self.clip_spin.setClearValue(98.0)
        self.clip_spin.setKeyboardTracking(False)
        self.clip_spin.setValue(98.0 if style.clip_percent is None else style.clip_percent)
        self.clip_check.setChecked(style.clip_percent is not None)
        self._scale_form.insertRow(1, self.clip_check, self.clip_spin)

        group = QGroupBox("Amplitudes")
        group.setObjectName("amplitudes_group")
        form = QFormLayout(group)
        gain = style.gain
        unit = "m" if depth else "ms"
        self.agc_check = QCheckBox("Balance along the trace (AGC)")
        self.agc_check.setToolTip("Each sample divided by the strength of the samples around "
                                  "it, so weak and strong parts of a trace look alike")
        self.agc_spin = QgsDoubleSpinBox()
        self.agc_spin.setObjectName("agc_spin")
        span = max(section.step, (section.n_samples - 1) * section.step)
        if depth:
            self.agc_spin.setDecimals(1)
            self.agc_spin.setRange(0.1, 1e5)
            default = round(span / 10, 1)
        else:                                       # a quarter of the record, at most 200 ms
            self.agc_spin.setDecimals(0)
            self.agc_spin.setRange(1.0, 1e5)
            default = float(max(1, min(AGC_MAX_MS, round(span * 1000.0 / 4))))
        self.agc_spin.setSuffix(f" {unit}")
        self.agc_spin.setClearValue(default)
        on = gain.agc_window is not None and gain.agc_window > 0
        self.agc_spin.setValue((gain.agc_window if depth else gain.agc_window * 1000.0)
                               if on else default)
        self.agc_check.setChecked(on)
        self.time_power_check = QCheckBox("Gain with depth" if depth else "Gain with time")
        self.time_power_check.setToolTip(
            f"Each sample multiplied by its {'depth' if depth else 'time'} to this power: the "
            "deep part, weakened on its way, shows")
        self.time_power_spin = QgsDoubleSpinBox()
        self.time_power_spin.setObjectName("time_power_spin")
        self.time_power_spin.setRange(0.1, 5.0)
        self.time_power_spin.setDecimals(1)
        self.time_power_spin.setSingleStep(0.5)
        self.time_power_spin.setClearValue(2.0)
        powered = gain.time_power is not None and gain.time_power != 0
        self.time_power_spin.setValue(gain.time_power if powered else 2.0)
        self.time_power_check.setChecked(powered)
        self.balance_check = QCheckBox("Balance traces against each other")
        self.balance_check.setToolTip("Each trace divided by its own strength (RMS)")
        self.balance_check.setChecked(gain.balance_traces)
        self.polarity_check = QCheckBox("Swap polarity")
        self.polarity_check.setChecked(gain.reverse_polarity)
        if not self._signed:
            self.polarity_check.setEnabled(False)
            self.polarity_check.setToolTip("The data are never negative")
        else:
            self.polarity_check.setToolTip("Positive and negative amplitudes swap colours")
        form.addRow(self.agc_check)
        form.addRow("Window", self.agc_spin)
        form.addRow(self.time_power_check)
        form.addRow("Power", self.time_power_spin)
        form.addRow(self.balance_check)
        form.addRow(self.polarity_check)
        self.show_muted_check = QCheckBox("Paint muted zones")
        self.show_muted_check.setObjectName("show_muted_check")
        self.show_muted_check.setToolTip("Samples that are zero at the top or bottom of a trace "
                                         "are left transparent unless this is ticked.")
        self.show_muted_check.setChecked(gain.show_muted)
        form.addRow(self.show_muted_check)
        self.amplitudes_note = QLabel("These change the picture only. The readout shows the "
                                      "file's amplitudes.")
        self.amplitudes_note.setObjectName("amplitudes_note")
        self.amplitudes_note.setWordWrap(True)
        form.addRow(self.amplitudes_note)
        self.amplitudes_group = group

        self.agc_check.toggled.connect(self._gain_changed)
        self.time_power_check.toggled.connect(self._gain_changed)
        for w in (self.balance_check, self.polarity_check):
            w.toggled.connect(self._gain_changed)
        for spin in (self.agc_spin, self.time_power_spin):
            spin.valueChanged.connect(self._gain_changed)
        self.clip_check.toggled.connect(self._clip_changed)
        self.clip_spin.valueChanged.connect(self._clip_percent_changed)
        self.min_spin.valueChanged.connect(lambda v: self._limit_typed(v, True))
        self.max_spin.valueChanged.connect(lambda v: self._limit_typed(v, False))
        self._sync_gain_widgets()
        if self.clip_check.isChecked():
            self._recompute()
        return group

    def gain(self):
        """The display options as chosen (a ``DisplayGain``)."""
        from ..core.trace_section import DisplayGain
        depth = self._traces.section.domain == "depth"
        window = self.agc_spin.value() if depth else self.agc_spin.value() / 1000.0
        return DisplayGain(
            agc_window=window if self.agc_check.isChecked() else None,
            time_power=self.time_power_spin.value() if self.time_power_check.isChecked()
            else None,
            balance_traces=self.balance_check.isChecked(),
            reverse_polarity=self.polarity_check.isChecked() and self.polarity_check.isEnabled(),
            show_muted=self.show_muted_check.isChecked())

    def _sync_gain_widgets(self) -> None:
        self.agc_spin.setEnabled(self.agc_check.isChecked())
        self.time_power_spin.setEnabled(self.time_power_check.isChecked())
        shown = " (as shown)" if self.gain().active() else ""     # not the file's numbers
        for spin, text in ((self.min_spin, "Minimum"), (self.max_spin, "Maximum")):
            label = self._scale_form.labelForField(spin)
            if label is not None:
                label.setText(text + shown)

    def _shown(self, gain):
        """The values shown with ``gain`` for the limits: the file's own without an option,
        else a sample of a gained copy (the drawing's when it has one; made here otherwise,
        and only the sample kept). Painting the muted zones or not changes no value."""
        from dataclasses import replace

        from ..core.trace_section import _sample
        if not gain.active():
            return self._traces.section.amplitudes
        gain = replace(gain, show_muted=False)
        hit = self._shown_by_gain.get(gain)
        if hit is None:
            hit = np.array(_sample(display_values(self._traces.section, gain)))
            self._shown_by_gain[gain] = hit
        return hit

    def _gain_changed(self, *_args) -> None:
        self._sync_gain_widgets()
        if self.clip_check.isChecked():
            self._recompute()

    def _clip_changed(self, on: bool) -> None:
        if on and not self._syncing:
            self._recompute()

    def _clip_percent_changed(self, *_args) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            self.clip_check.setChecked(True)
        finally:
            self._syncing = False
        self._recompute()

    def _recompute(self) -> None:
        """The limits of the clip on the values shown (``data.trace_limits``)."""
        from dataclasses import replace

        from .data import trace_limits
        gain = self.gain()
        style = replace(self._style, gain=gain, clip_percent=self.clip_spin.value())
        lo, hi = trace_limits(self._traces, style, values=self._shown(gain))
        self._signed = lo < 0
        self._set_limits(lo, hi)

    def _set_limits(self, lo: float, hi: float) -> None:
        import math
        c = max(abs(lo), abs(hi))
        decimals = 3 if not c > 0 else min(12, max(3, 2 - math.floor(math.log10(c))))
        if c >= 100:                                # large amplitudes: whole numbers
            decimals = 0
        self._limits = (lo, hi)
        self._syncing = True
        try:
            for spin, v in ((self.min_spin, lo), (self.max_spin, hi)):
                spin.setDecimals(decimals)
                spin.setValue(v)
        finally:
            self._syncing = False

    def _limit_typed(self, value: float, is_min: bool) -> None:
        """A typed limit: the clip is off; on signed data the other limit mirrors it."""
        if self._syncing:
            return
        self._syncing = True
        try:
            self.clip_check.setChecked(False)
            if self._signed:
                c = abs(value)
                self.min_spin.setValue(-c)
                self.max_spin.setValue(c)
        finally:
            self._syncing = False
        self._limits = (self.min_spin.value(), self.max_spin.value())

    def _trace_style(self):
        from dataclasses import replace
        clip = self.clip_spin.value() if self.clip_check.isChecked() else None
        scale = self.scale()
        if clip is not None:                        # the exact limits, not the rounded spins
            lo, hi = self._limits
            if hi > lo:
                scale = replace(scale, vmin=float(lo), vmax=float(hi))
        return replace(self._style, scale=scale, clip_percent=clip, gain=self.gain())

    # -- interpolation of the smooth field -------------------------------------------------
    def _build_interpolation(self, form, interp) -> None:
        """Interpolation, the chosen method's few settings and the anisotropy, under the
        grid cell (``core.interpolators``)."""
        from qgis.PyQt.QtWidgets import QSizePolicy, QSpinBox, QStackedWidget, QWidget

        from ..core.interpolators import (DEFAULT_NEIGHBOURS, KERNELS, METHOD_NAMES, METHODS,
                                          VARIOGRAMS, Interpolation)
        interp = interp or Interpolation()
        self._interp_form = form
        self.method_combo = QComboBox()
        self.method_combo.setObjectName("method_combo")
        for m in METHODS:
            self.method_combo.addItem(METHOD_NAMES[m], m)
        self.method_combo.setCurrentIndex(max(0, self.method_combo.findData(interp.method)))
        form.addRow("Interpolation", self.method_combo)

        def spin(low, high, decimals, value, step=None):
            s = QDoubleSpinBox()
            s.setRange(low, high)
            s.setDecimals(decimals)
            s.setValue(value)
            if step:
                s.setSingleStep(step)
            return s

        def neighbours(method):
            s = QSpinBox()
            s.setRange(1, 64)
            s.setValue(interp.neighbours if interp.method == method and interp.neighbours
                       else DEFAULT_NEIGHBOURS[method])
            s.setToolTip("How many cells around each point of the field are used")
            return s

        def page(*rows):
            w = QWidget()
            box = QVBoxLayout(w)
            box.setContentsMargins(0, 0, 0, 0)
            for items in rows:
                line = QHBoxLayout()
                for item in items:
                    line.addWidget(QLabel(item) if isinstance(item, str) else item)
                line.addStretch(1)
                box.addLayout(line)
            return w

        self.power_spin = spin(0.5, 10.0, 1, interp.power, 0.5)
        self.power_spin.setToolTip("Higher: nearer cells count more (2 is usual)")
        self.idw_neighbours = neighbours("idw")
        self.kernel_combo = QComboBox()
        for k in KERNELS:
            self.kernel_combo.addItem(KERNEL_TEXT[k], k)
        self.kernel_combo.setCurrentIndex(max(0, self.kernel_combo.findData(interp.kernel)))
        self.smooth_spin = spin(0.0, 1000.0, 2, interp.smoothing, 0.1)
        self.smooth_spin.setToolTip("0 passes exactly through the cell values; larger values "
                                    "smooth the field")
        self.variogram_combo = QComboBox()
        for v in VARIOGRAMS:
            self.variogram_combo.addItem(v.capitalize(), v)
        self.variogram_combo.setCurrentIndex(
            max(0, self.variogram_combo.findData(interp.variogram)))
        self.kriging_neighbours = neighbours("kriging")
        given = None not in (interp.range_m, interp.sill, interp.nugget)
        self.fit_check = QCheckBox("Fit to the data")
        self.fit_check.setToolTip("Range, sill and nugget fitted to the model's own variogram")
        self.fit_check.setChecked(not given)
        self.range_spin = spin(0.01, 1e6, 2, interp.range_m or 10.0)
        self.range_spin.setSuffix(" m")
        self.sill_spin = spin(0.0, 1e9, 3, interp.sill if interp.sill is not None else 1.0, 0.01)
        self.nugget_spin = spin(0.0, 1e9, 3, interp.nugget or 0.0, 0.01)
        self.fit_check.toggled.connect(self._sync_interpolation)
        self.fit_button = QPushButton("Fit Now")
        self.fit_button.setToolTip("Fit the variogram now and show what kriging would use")
        self.fit_button.clicked.connect(self.fit_variogram_now)
        self.fit_label = QLabel()              # two lines, always room for them
        self.fit_label.setMinimumHeight(2 * self.fit_label.fontMetrics().lineSpacing() + 2)
        self.method_pages = QStackedWidget()
        self.method_pages.setObjectName("method_pages")
        self._pages = {
            "linear": page(), "nearest": page(),
            "idw": page(("Power", self.power_spin, "Neighbours", self.idw_neighbours)),
            "spline": page(("Kernel", self.kernel_combo, "Smoothing", self.smooth_spin)),
            "kriging": page(("Variogram", self.variogram_combo, "Neighbours",
                             self.kriging_neighbours, self.fit_check),
                            ("Range", self.range_spin, "Sill", self.sill_spin,
                             "Nugget", self.nugget_spin),
                            (self.fit_button, self.fit_label))}
        self.fit_label.setMinimumWidth(240)
        for m in METHODS:
            self.method_pages.addWidget(self._pages[m])
        form.addRow(self.method_pages)
        shown = interp.anisotropy
        if shown is None:                       # Automatic: show what the cells give
            from ..core.gridding import cell_aspect
            shown = cell_aspect(self._mesh) if self._mesh is not None else 1.0
        self.aniso_spin = spin(0.01, 1000.0, 2, shown, 0.5)
        self.auto_aniso = QCheckBox("Automatic")
        self.auto_aniso.setChecked(interp.anisotropy is None)
        self.auto_aniso.setToolTip(ANISO_AUTO_TIP)
        self.auto_aniso.toggled.connect(self._sync_interpolation)
        self.aniso_spin.setToolTip(ANISO_TIP)
        self._aniso_row = QWidget()
        row = QHBoxLayout(self._aniso_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self.aniso_spin)
        row.addWidget(self.auto_aniso)
        row.addStretch(1)
        form.addRow("Anisotropy", self._aniso_row)
        self._ignored = QSizePolicy.Policy.Ignored
        self.method_combo.currentIndexChanged.connect(self._sync_interpolation)
        self._sync_interpolation()

    def _sync_interpolation(self, *_args) -> None:
        """The chosen method's page only (the others take no room); everything off where no
        smooth field is drawn."""
        from qgis.PyQt.QtWidgets import QSizePolicy
        method = self.method_combo.currentData()
        for m, w in self._pages.items():
            policy = QSizePolicy.Policy.Preferred if m == method else self._ignored
            w.setSizePolicy(policy, policy)
        self.method_pages.setCurrentWidget(self._pages[method])
        self.method_pages.adjustSize()
        field = "smooth" in (self.mode_combo.currentData() or "") or \
            "contours" in (self.mode_combo.currentData() or "")
        self.method_combo.setEnabled(field)
        self.method_combo.setToolTip(METHOD_TIP if field else METHOD_OFF_TIP)
        self.method_pages.setEnabled(field)
        self._interp_form.setRowVisible(self.method_pages, method not in ("linear", "nearest"))
        self._interp_form.setRowVisible(self._aniso_row, method != "linear")
        self._aniso_row.setEnabled(field)
        self.aniso_spin.setEnabled(not self.auto_aniso.isChecked())
        for s in (self.range_spin, self.sill_spin, self.nugget_spin):
            s.setEnabled(not self.fit_check.isChecked())
        self._fit_height()

    def interpolation(self):
        """The method and settings as chosen (Auto fields: None)."""
        from ..core.interpolators import DEFAULT_NEIGHBOURS, Interpolation
        method = self.method_combo.currentData()
        if method == "linear":
            return Interpolation()
        aniso = None if self.auto_aniso.isChecked() else self.aniso_spin.value()

        def k(spin):
            return None if spin.value() == DEFAULT_NEIGHBOURS[method] else spin.value()

        if method == "idw":
            return Interpolation(method, power=self.power_spin.value(),
                                 neighbours=k(self.idw_neighbours), anisotropy=aniso)
        if method == "spline":
            return Interpolation(method, kernel=self.kernel_combo.currentData(),
                                 smoothing=self.smooth_spin.value(), anisotropy=aniso)
        if method == "kriging":
            fit = self.fit_check.isChecked()
            return Interpolation(method, neighbours=k(self.kriging_neighbours),
                                 variogram=self.variogram_combo.currentData(),
                                 range_m=None if fit else self.range_spin.value(),
                                 sill=None if fit else self.sill_spin.value(),
                                 nugget=None if fit else self.nugget_spin.value(),
                                 anisotropy=aniso)
        return Interpolation(method, anisotropy=aniso)

    def fit_variogram_now(self) -> None:
        """Fit the variogram of the model's cells as kriging would, show it and put it into
        the range, sill and nugget fields (untick "Fit to the data" to tune them)."""
        from ..core.gridding import cell_centres
        from ..core.interpolators import estimate_anisotropy, fit_variogram
        from ..core.numbers import fmt_sig
        mesh = self._mesh
        if mesh is None:
            return
        values = np.asarray(mesh.values, dtype=float)
        log = self.log_check.isChecked()
        if log:
            values = np.log10(np.where(values > 0, values, np.nan))
        ok = np.isfinite(values)
        model = self.variogram_combo.currentData()
        try:
            points = cell_centres(mesh)[ok]
            aniso = (estimate_anisotropy(points, values[ok], model)
                     if self.auto_aniso.isChecked() else self.aniso_spin.value())
            fit = fit_variogram(points, values[ok], model, anisotropy=aniso)
        except (ValueError, MemoryError) as exc:
            why = "not enough memory" if isinstance(exc, MemoryError) else str(exc)
            self.fit_label.setText(f"Cannot fit: {why}")
            self.fit_label.setWordWrap(True)
            self.fit_label.setToolTip("")
            return
        unit = " (log10)" if log else ""
        text = (f"Range {fmt_sig(fit.range_m, 3)} m, sill {fmt_sig(fit.sill, 3)}, "
                f"nugget {fmt_sig(fit.nugget, 3)}{unit}\nanisotropy {fmt_sig(aniso, 3)}")
        self.fit_label.setText(text)
        self.fit_label.setToolTip(text)
        self.range_spin.setValue(fit.range_m)
        self.sill_spin.setValue(fit.sill)
        self.nugget_spin.setValue(fit.nugget)
        self.aniso_spin.setValue(aniso)
        self._fit_height()

    def _check_levels_in_scale(self, levels) -> None:
        """A typed level outside the colour scale would be dropped without a word: say so."""
        from ..core.numbers import fmt_trim
        try:
            scale = self.scale()
        except ValueError:
            return                              # the scale's own error is shown instead
        lo, hi = min(scale.vmin, scale.vmax), max(scale.vmin, scale.vmax)
        outside = [v for v in levels if not lo <= v <= hi]
        if outside:
            unit = f" {self._unit}" if self._unit else ""
            raise ValueError(f"{fmt_trim(outside[0], 6)} is outside the colour scale "
                             f"({fmt_trim(lo, 6)}–{fmt_trim(hi, 6)}{unit}).")

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
        if self._traces is not None:
            return self._trace_style()
        major = parse_levels(self.major_edit.text())
        minor = parse_levels(self.minor_edit.text())
        if major or minor:
            self._check_levels_in_scale(major + minor)
        shown = self.shown_combo.currentData() if self._readings is not None else \
            self._style.shown
        changed = self._readings is not None and shown != self._shown_before
        colour, width = self._line_look()
        return replace(
            self._style, shown=shown, contour_colour=colour, contour_width=width,
            scale=None if changed else self.scale(),      # a new value: automatic scale
            mode=self.mode_combo.currentData(),
            grid_cell=None if self.auto_cell.isChecked() else self.cell_spin.value(),
            interpolation=self.interpolation(),
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
