"""Property panels of the plate items in QGIS's layout designer.

The colour bar's panel embeds QGIS's own colour-ramp legend settings widget (orientation,
direction, number format, prefix/suffix, fonts), plus the tick choice, title and unit."""
from __future__ import annotations

from qgis.gui import (QgsColorRampLegendNodeWidget, QgsFontButton, QgsGui,
                      QgsLayoutItemAbstractGuiMetadata, QgsLayoutItemBaseWidget)
from qgis.PyQt.QtWidgets import QFormLayout, QLabel, QLineEdit, QVBoxLayout

from .items import BOREHOLE_LEGEND_TYPE, COLOUR_BAR_TYPE

_gui_metadata: list = []


class ColourBarWidget(QgsLayoutItemBaseWidget):
    def __init__(self, parent, item):
        super().__init__(parent, item)
        self.item = item
        self.ticks = QLineEdit(item.ticks)
        self.ticks.setToolTip('"auto", "step:25" or "list:1,10,100"')
        if item.amplitude:                      # an amplitude key names its two ends only
            self.ticks.setEnabled(False)
            self.ticks.setToolTip("An amplitude key has no numbers: its ends are named")
        self.title = QLineEdit(item.title)
        self.unit = QLineEdit(item.unit)
        self.ramp = QgsColorRampLegendNodeWidget(self)
        self.ramp.setSettings(item.settings)
        form = QFormLayout()
        form.addRow("Ticks", self.ticks)
        form.addRow("Title", self.title)
        form.addRow("Unit", self.unit)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Frame {item.frame_id} · model {item.dataset_id}"))
        layout.addLayout(form)
        layout.addWidget(self.ramp)
        for edit in (self.ticks, self.title, self.unit):
            edit.editingFinished.connect(self._apply)
        self.ramp.widgetChanged.connect(self._apply)

    def _apply(self):
        item = self.item
        item.beginCommand("Colour bar")
        item.ticks = self.ticks.text().strip() or "auto"
        item.title, item.unit = self.title.text(), self.unit.text()
        item.settings = self.ramp.settings()
        item.endCommand()
        item.refresh()
        item.update()


class BoreholeLegendWidget(QgsLayoutItemBaseWidget):
    def __init__(self, parent, item):
        super().__init__(parent, item)
        self.item = item
        self.font = QgsFontButton()
        self.font.setMode(QgsFontButton.Mode.ModeTextRenderer)
        self.font.setTextFormat(item.text_format)
        self.font.changed.connect(self._apply)
        layout = QFormLayout(self)
        layout.addRow("Frames", QLabel(", ".join(item.frame_ids) or "(none)"))
        layout.addRow("Text", self.font)

    def _apply(self):
        self.item.beginCommand("Borehole legend")
        self.item.text_format = self.font.textFormat()
        self.item.endCommand()
        self.item.refresh()
        self.item.update()


class _GuiMetadata(QgsLayoutItemAbstractGuiMetadata):
    def __init__(self, type_id, name, widget_cls):
        super().__init__(type_id, name)
        self.widget_cls = widget_cls

    def flags(self):
        # made by the plugin's plate builder, not drawn with a layout tool
        return QgsLayoutItemAbstractGuiMetadata.Flag.FlagNoCreationTools

    def createItemWidget(self, item):
        return self.widget_cls(None, item)


def register_widgets() -> None:
    registry = QgsGui.layoutItemGuiRegistry()
    if registry is None or _gui_metadata:
        return
    for type_id, name, cls in ((COLOUR_BAR_TYPE, "Colour bar", ColourBarWidget),
                               (BOREHOLE_LEGEND_TYPE, "Borehole legend", BoreholeLegendWidget)):
        meta = _GuiMetadata(type_id, name, cls)
        if registry.addLayoutItemGuiMetadata(meta):
            _gui_metadata.append(meta)
