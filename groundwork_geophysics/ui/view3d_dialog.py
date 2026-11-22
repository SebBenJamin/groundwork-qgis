"""Show in 3D: which models stand as curtains and which profiles' boreholes as columns in
QGIS's 3D view, and how each model stands there. One tick per model and per profile's
boreholes (a profile's own tick sets all of them) and a representation per model; below,
whether the section pictures show the interpretation, a one-off restyle of the
interpretation from 2D, and the sizes of borehole columns and station spheres."""
from __future__ import annotations

from qgis.gui import QgsCollapsibleGroupBox, QgsDoubleSpinBox
from qgis.PyQt.QtCore import QLocale, Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                                 QHBoxLayout, QHeaderView, QLabel, QPushButton, QTreeWidget,
                                 QTreeWidgetItem, QVBoxLayout)

from ..core.dataset_types import type_label
from .help import add_help_button
from .view3d_layers import Choice, auto_borehole_width, auto_station_size

TITLE = "Show in 3D"
INTRO = ("Tick what to show in the 3D view and choose how each model stands there: models "
         "as curtains under their profile, boreholes as columns at their position.")
HEADERS = ("Show", "Show As")
BOREHOLES = "Boreholes"
BOREHOLES_TIP = "The boreholes this profile's section shows, at their map position"
LOCAL_TIP = ("This profile has no real heights, so it has no place in 3D. Give it a "
             "reference height in the section panel first.")
#: (representation, combo text, tooltip)
LOOK_ITEMS = (
    ("section", "As in the Section",
     "As the section panel shows the model: cells, a point cloud (smooth) or contour lines. "
     "Style them in QGIS and identify their values."),
    ("cloud", "Point Cloud",
     "A point cloud of the model's smooth field, whatever the section shows, with the "
     "section's contour lines when it shows them. Style it in QGIS and identify its values."),
    ("picture", "Section Picture",
     "A picture of the section exactly as the panel draws it, labels included; all of a "
     "profile's pictured models in one picture. No values on Identify."))
LOOK_TIP = "How this model stands in the 3D view"
INTERP_TEXT = "Section pictures show the interpretation"
INTERP_TIP = ("Paint the interpretation into each profile's section picture as the section "
              "panel draws it: fills, hatches, transparency and names")
RESTYLE_TEXT = "Restyle the interpretation from 2D"
RESTYLE_TIP = ("On OK, the interpretation's 3D style follows its 2D style (Symbology) again "
               "for every entity, also ones you restyled in the layer's 3D View")
SIZES_TITLE = "Sizes"
BOREHOLE_LABEL = "Borehole column width"
BOREHOLE_TIP = "The diameter of the borehole columns in 3D.\nAuto: {} m from the station spacing"
STATION_LABEL = "Station sphere size"
STATION_TIP = ("The diameter of the station spheres in 3D, while their 3D style is the "
               "plugin's own.\nAuto: {} m from the station spacing")
MAX_SIZE = 50.0                         # m
_KIND, _ID = Qt.ItemDataRole.UserRole, Qt.ItemDataRole.UserRole + 1


def _size_box(value: float | None, auto: float, tip: str) -> QgsDoubleSpinBox:
    """Metres, or "Auto" at the minimum (the clear button goes back to it)."""
    box = QgsDoubleSpinBox()
    box.setRange(0.0, MAX_SIZE)
    box.setDecimals(2)
    box.setSingleStep(0.05)
    box.setSuffix(" m")
    box.setSpecialValueText("Auto")
    box.setClearValueMode(QgsDoubleSpinBox.ClearValueMode.MinimumValue)
    box.setShowClearButton(True)
    box.setValue(value or 0.0)
    box.setToolTip(tip.format(QLocale().toString(float(auto), "f", 2)))
    return box


class View3dDialog(QDialog):
    """The store's profiles with their models and boreholes; ``choice()`` gives the ticks,
    representations and options. Profiles in ``local`` (no real heights) are listed greyed
    out, saying why."""

    def __init__(self, store, choice: Choice, local=(), parent=None):
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        intro = QLabel(INTRO)
        intro.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels(list(HEADERS))
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setToolTip("Tick a profile to show all of it")
        self.tree.setMinimumSize(420, 260)          # room for model names; grows with the dialog
        self._looks: dict[str, QComboBox] = {}
        for profile in store.profiles():
            top = QTreeWidgetItem([profile.name])
            top.setFlags(top.flags() | Qt.ItemFlag.ItemIsUserCheckable
                         | Qt.ItemFlag.ItemIsAutoTristate)
            self.tree.addTopLevelItem(top)
            for d in store.datasets(profile.id):
                if d.kind.endswith("_model"):
                    item = self._child(top, d.name or d.id, "model", d.id,
                                       d.id in choice.models)
                    item.setToolTip(0, f"{d.name or d.id}\n{type_label(d.kind)}")
                    self._looks[d.id] = self._look_combo(item, choice.look_of(d.id),
                                                         profile.id not in local)
            child = self._child(top, BOREHOLES, "boreholes", profile.id,
                                profile.id in choice.boreholes)
            child.setToolTip(0, BOREHOLES_TIP)
            top.setExpanded(True)
            if profile.id in local:
                top.setDisabled(True)
                top.setToolTip(0, LOCAL_TIP)
        self.interpretation = QCheckBox(INTERP_TEXT)
        self.interpretation.setToolTip(INTERP_TIP)
        self.interpretation.setChecked(choice.interpretation)
        self.restyle = QCheckBox(RESTYLE_TEXT)
        self.restyle.setToolTip(RESTYLE_TIP)
        self.sizes = QgsCollapsibleGroupBox(SIZES_TITLE)
        self.sizes.setSaveCollapsedState(False)
        self.borehole_width = _size_box(choice.borehole_width, auto_borehole_width(store),
                                        BOREHOLE_TIP)
        self.station_size = _size_box(choice.station_size, auto_station_size(store),
                                      STATION_TIP)
        form = QFormLayout(self.sizes)
        for text, box in ((BOREHOLE_LABEL, self.borehole_width),
                          (STATION_LABEL, self.station_size)):
            label = QLabel(text)
            label.setToolTip(box.toolTip())
            form.addRow(label, box)
        self.sizes.setCollapsed(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        add_help_button(buttons, "view3d")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.select_all = QPushButton("Select All")
        self.select_all.setToolTip("Tick every model and every profile's boreholes")
        self.select_all.clicked.connect(lambda: self._tick_all(True))
        self.deselect_all = QPushButton("Deselect All")
        self.deselect_all.setToolTip("Untick everything: nothing is shown in 3D")
        self.deselect_all.clicked.connect(lambda: self._tick_all(False))
        ticks = QHBoxLayout()
        ticks.addWidget(self.select_all)
        ticks.addWidget(self.deselect_all)
        ticks.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.tree, 1)
        layout.addLayout(ticks)
        layout.addWidget(self.interpretation)
        layout.addWidget(self.restyle)
        layout.addWidget(self.sizes)
        layout.addWidget(buttons)

    def _tick_all(self, ticked: bool) -> None:
        """Tick or untick every model and boreholes entry of the profiles that can be shown
        (a profile without real heights stays as it is)."""
        state = Qt.CheckState.Checked if ticked else Qt.CheckState.Unchecked
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            if top.isDisabled():
                continue
            for k in range(top.childCount()):
                top.child(k).setCheckState(0, state)

    @staticmethod
    def _child(top, text: str, kind: str, item_id: str, checked: bool) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setData(0, _KIND, kind)
        item.setData(0, _ID, item_id)
        top.addChild(item)
        item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        return item

    def _look_combo(self, item, look: str, enabled: bool) -> QComboBox:
        combo = QComboBox()
        for i, (value, text, tip) in enumerate(LOOK_ITEMS):
            combo.addItem(text, value)
            combo.setItemData(i, tip, Qt.ItemDataRole.ToolTipRole)
        combo.setCurrentIndex(max(0, combo.findData(look)))
        combo.setToolTip(LOOK_TIP)
        combo.setEnabled(enabled)
        self.tree.setItemWidget(item, 1, combo)
        return combo

    def restyle_interpretation(self) -> bool:
        """Whether OK restyles the interpretation's 3D layers from their 2D style."""
        return self.restyle.isChecked()

    def choice(self) -> Choice:
        models, boreholes = set(), set()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for k in range(top.childCount()):
                item = top.child(k)
                if item.checkState(0) != Qt.CheckState.Checked:
                    continue
                (models if item.data(0, _KIND) == "model" else boreholes).add(item.data(0, _ID))
        looks = {did: combo.currentData() for did, combo in self._looks.items()}
        return Choice(frozenset(models), frozenset(boreholes), looks,
                      self.interpretation.isChecked(),
                      self.borehole_width.value() or None, self.station_size.value() or None)
