"""Show in 3D: which models stand as curtains and which profiles' boreholes as columns in
QGIS's 3D view. One tick per model and per profile's boreholes; a profile's own tick sets
all of them."""
from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QTreeWidget,
                                 QTreeWidgetItem, QVBoxLayout)

from ..core.dataset_types import type_label
from .help import add_help_button
from .view3d_layers import Choice

TITLE = "Show in 3D"
INTRO = ("Tick what to show in the 3D view: models stand as curtains under their profile, "
         "boreholes as columns at their position. Open a 3D map view with View → 3D Map "
         "Views → New 3D Map View.")
BOREHOLES = "Boreholes"
BOREHOLES_TIP = "The boreholes this profile's section shows, at their map position"
_KIND, _ID = Qt.ItemDataRole.UserRole, Qt.ItemDataRole.UserRole + 1


class View3dDialog(QDialog):
    """The store's profiles with their models and boreholes; ``choice()`` gives the ticks."""

    def __init__(self, store, choice: Choice, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TITLE)
        intro = QLabel(INTRO)
        intro.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setToolTip("Tick a profile to show all of it")
        self.tree.setMinimumSize(400, 260)          # room for model names; grows with the dialog
        for profile in store.profiles():
            top = QTreeWidgetItem([profile.name])
            top.setFlags(top.flags() | Qt.ItemFlag.ItemIsUserCheckable
                         | Qt.ItemFlag.ItemIsAutoTristate)
            for d in store.datasets(profile.id):
                if d.kind.endswith("_model"):
                    item = self._child(top, d.name or d.id, "model", d.id,
                                       d.id in choice.models)
                    item.setToolTip(0, f"{d.name or d.id}\n{type_label(d.kind)}")
            child = self._child(top, BOREHOLES, "boreholes", profile.id,
                                profile.id in choice.boreholes)
            child.setToolTip(0, BOREHOLES_TIP)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        add_help_button(buttons, "view3d")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.tree, 1)
        layout.addWidget(buttons)

    @staticmethod
    def _child(top, text: str, kind: str, item_id: str, checked: bool) -> QTreeWidgetItem:
        item = QTreeWidgetItem([text])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setData(0, _KIND, kind)
        item.setData(0, _ID, item_id)
        top.addChild(item)
        item.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        return item

    def choice(self) -> Choice:
        models, boreholes = set(), set()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            for k in range(top.childCount()):
                item = top.child(k)
                if item.checkState(0) != Qt.CheckState.Checked:
                    continue
                (models if item.data(0, _KIND) == "model" else boreholes).add(item.data(0, _ID))
        return Choice(frozenset(models), frozenset(boreholes))
