"""Layer list of the section panel: visibility, opacity and colour scale per dataset."""
from __future__ import annotations

from dataclasses import replace

from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QSlider,
                                 QToolButton, QVBoxLayout, QWidget)

from .data import SectionLayer, layer_name
from .readout import format_value, unit_label
from .scale_dialog import ColorScaleDialog, ramp_icon


def _scale_text(layer: SectionLayer) -> str:
    scale = layer.style.scale
    if scale is None:
        return "Scale…"
    log = " log" if scale.log else ""
    return f"{format_value(scale.vmin)}–{format_value(scale.vmax)}{log}"


class _LayerRow(QWidget):
    def __init__(self, layer: SectionLayer, owner: "LayerList"):
        super().__init__()
        self.dataset_id = layer.dataset.id
        self._owner = owner
        self.check = QCheckBox(layer_name(layer.dataset))
        self.check.toggled.connect(lambda on: owner.set_visible(self.dataset_id, on))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setFixedWidth(80)
        self.opacity.setToolTip("Opacity")
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.opacity.sliderReleased.connect(self._opacity_changed)
        self.scale_button = QToolButton()
        self.scale_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.scale_button.setIconSize(QSize(40, 10))
        self.scale_button.setToolTip("Colour scale")
        self.scale_button.clicked.connect(lambda: owner.edit_scale(self.dataset_id))
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 1, 2, 1)
        row.addWidget(self.check, 1)
        row.addWidget(self.opacity)
        row.addWidget(self.scale_button)
        self.update_from(layer)

    def update_from(self, layer: SectionLayer) -> None:
        style = layer.style
        for widget, setter, value in ((self.check, self.check.setChecked, style.visible),
                                      (self.opacity, self.opacity.setValue,
                                       round(style.opacity * 100))):
            widget.blockSignals(True)
            setter(value)
            widget.blockSignals(False)
        ok = layer.error is None
        self.opacity.setEnabled(ok)
        self.scale_button.setEnabled(ok)
        self.scale_button.setText(_scale_text(layer))
        if style.scale is not None:
            self.scale_button.setIcon(ramp_icon(style.scale.cmap, 40, 10))
        d = layer.dataset
        tip = f"{layer_name(d)} (version {d.version})\n{d.source_path}"
        self.check.setToolTip(tip if ok else f"{tip}\n\n{layer.error}")
        self.check.setStyleSheet("" if ok else "color: #c00000;")

    def _opacity_changed(self, *_):
        if self.opacity.isSliderDown():          # apply once on release, not per pixel
            return
        self._owner.set_opacity(self.dataset_id, self.opacity.value() / 100.0)


class LayerList(QWidget):
    """One row per dataset of the open profile, topmost layer first."""

    style_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.provider = None
        self._layers: dict[str, SectionLayer] = {}
        self._rows: dict[str, _LayerRow] = {}
        title = QLabel("<b>Layers</b>")
        self._empty = QLabel("No datasets on this profile")
        self._empty.setStyleSheet("color: gray;")
        self._box = QWidget()
        self._box_layout = QVBoxLayout(self._box)
        self._box_layout.setContentsMargins(0, 0, 0, 0)
        self._box_layout.setSpacing(0)
        self._box_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._box)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(title)
        layout.addWidget(self._empty)
        layout.addWidget(scroll, 1)
        self.setMinimumWidth(300)

    def dataset_ids(self) -> list[str]:
        return list(self._rows)

    def set_layers(self, provider, layers: list[SectionLayer]) -> None:
        """Show ``layers`` (drawing order, bottom first). Rows are rebuilt only when the
        set of datasets changes, otherwise updated in place."""
        self.provider = provider
        self._layers = {la.dataset.id: la for la in layers}
        ids = [la.dataset.id for la in reversed(layers)]
        if ids != list(self._rows):
            for row in self._rows.values():
                self._box_layout.removeWidget(row)
                row.deleteLater()
            self._rows = {}
            for i, dataset_id in enumerate(ids):
                row = _LayerRow(self._layers[dataset_id], self)
                self._box_layout.insertWidget(i, row)
                self._rows[dataset_id] = row
        else:
            for dataset_id, row in self._rows.items():
                row.update_from(self._layers[dataset_id])
        self._empty.setVisible(not ids)

    def clear(self) -> None:
        self.set_layers(self.provider, [])

    # -- style changes ---------------------------------------------------------------------
    def _update_style(self, dataset_id: str, **changes) -> None:
        if self.provider is None:
            return
        style = replace(self.provider.style(dataset_id), **changes)
        self.provider.set_style(dataset_id, style)
        layer = self._layers.get(dataset_id)
        if layer is not None:
            layer.style = style
            row = self._rows.get(dataset_id)
            if row is not None:
                row.update_from(layer)
        self.style_changed.emit(dataset_id)

    def set_visible(self, dataset_id: str, visible: bool) -> None:
        self._update_style(dataset_id, visible=bool(visible))

    def set_opacity(self, dataset_id: str, opacity: float) -> None:
        self._update_style(dataset_id, opacity=min(1.0, max(0.0, float(opacity))))

    def set_scale(self, dataset_id: str, scale) -> None:
        self._update_style(dataset_id, scale=scale)

    def edit_scale(self, dataset_id: str) -> None:
        layer = self._layers.get(dataset_id)
        if layer is None:
            return
        values = None if layer.mesh is None else layer.mesh.values
        dialog = ColorScaleDialog(layer.style.scale, values, unit_label(layer.dataset.unit),
                                  f"Colour scale: {layer_name(layer.dataset)}", self)
        dialog.applied.connect(lambda scale: self.set_scale(dataset_id, scale))
        dialog.exec()
        dialog.deleteLater()
