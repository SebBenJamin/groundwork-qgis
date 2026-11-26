"""Curve style…: colour, line, fill and scale of each log curve (curves have no QGIS layer
style of their own, so their look is kept in the project; edited with QGIS's widgets)."""
from __future__ import annotations

from typing import Callable

from qgis.gui import QgsColorButton
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                                 QDoubleSpinBox, QFormLayout, QGroupBox, QHBoxLayout, QLineEdit,
                                 QScrollArea, QVBoxLayout, QWidget)

from ..core.borehole_curves import DASHES, FILLS, CurveStyle
from ..section.borehole_draw import qcolor
from ..section.borehole_style import curve_styles, save_curve_styles


def _hex(colour: QColor, alpha: bool = False) -> str:
    text = colour.name()
    return text + f"{colour.alpha():02x}" if alpha else text


def _number(text: str) -> float | None:
    """A finite number ("2,5" too), else ``None`` (empty: the data range)."""
    import math
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        return None
    return value if math.isfinite(value) else None


class _CurveRow(QGroupBox):
    def __init__(self, title: str, style: CurveStyle):
        super().__init__(title)
        self.colour = QgsColorButton()
        self.colour.setColor(qcolor(style.colour))
        self.width = QDoubleSpinBox()
        self.width.setRange(0.1, 3.0)
        self.width.setSingleStep(0.1)
        self.width.setSuffix(" mm")
        self.width.setValue(style.width_mm)
        self.dash = QComboBox()
        self.dash.addItems(DASHES)
        self.dash.setCurrentText(style.dash)
        self.fill = QComboBox()
        self.fill.addItems(FILLS)
        self.fill.setCurrentText(style.fill)
        self.fill_colour = QgsColorButton()
        self.fill_colour.setAllowOpacity(True)
        self.fill_colour.setColor(qcolor(style.fill_colour))
        self.log = QCheckBox("Log scale")
        self.log.setChecked(style.log)
        self.vmin, self.vmax = QLineEdit(), QLineEdit()
        for edit, value in ((self.vmin, style.vmin), (self.vmax, style.vmax)):
            edit.setPlaceholderText("data range")
            edit.setText("" if value is None else f"{value:g}")
        form = QFormLayout(self)
        line = QHBoxLayout()
        line.addWidget(self.colour)
        line.addWidget(self.width)
        line.addWidget(self.dash)
        form.addRow("Line", line)
        fill = QHBoxLayout()
        fill.addWidget(self.fill)
        fill.addWidget(self.fill_colour)
        form.addRow("Fill", fill)
        scale = QHBoxLayout()
        scale.addWidget(self.log)
        scale.addWidget(self.vmin)
        scale.addWidget(self.vmax)
        form.addRow("Scale (min, max)", scale)

    def style(self) -> CurveStyle:
        return CurveStyle(colour=_hex(self.colour.color()), width_mm=self.width.value(),
                          dash=self.dash.currentText(), fill=self.fill.currentText(),
                          fill_colour=_hex(self.fill_colour.color(), alpha=True),
                          log=self.log.isChecked(), vmin=_number(self.vmin.text()),
                          vmax=_number(self.vmax.text()))


class CurveStyleDialog(QDialog):
    """``names``: curve key -> shown name. OK saves the styles and calls ``on_saved``."""

    def __init__(self, project, names: dict, on_saved: Callable[[], None], parent=None):
        super().__init__(parent)
        self.project, self.on_saved = project, on_saved
        self.setWindowTitle("Curve style")
        from .context_dialog import read_settings
        self.styles = curve_styles(project, read_settings(project))
        content = QWidget()
        rows_layout = QVBoxLayout(content)
        self.rows = {}
        for key, name in names.items():
            row = _CurveRow(name, self.styles.get(key) or CurveStyle())
            rows_layout.addWidget(row)
            self.rows[key] = row
        scroll = QScrollArea()
        scroll.setWidget(content)
        scroll.setWidgetResizable(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(buttons)
        self.resize(520, 420)

    def accept(self):
        styles = dict(self.styles)
        styles.update({key: row.style() for key, row in self.rows.items()})
        save_curve_styles(self.project, styles)
        self.on_saved()
        super().accept()
