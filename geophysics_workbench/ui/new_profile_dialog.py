"""'New Profile' dialog: a name, the method and where the line runs ("Where the Line Runs",
the placement widget Add Data shares).

A selected line feature or two points give a profile without stations: no spacing is asked
and no stations are invented. A positions file or a point layer gives a profile through the
positions with a station set; only then is the method asked. The dialog is shown non-modally
(``show()``), so "Pick on Map" can use the map canvas: it hides while picking and comes back
after the second click or when another map tool takes over.
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from qgis.core import Qgis, QgsProject
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                                 QLabel, QLineEdit, QMessageBox, QScrollArea, QSizePolicy,
                                 QVBoxLayout, QWidget)

from ..section.data import matching_profiles
from ..section.profile_source import CURVE_TOLERANCE
from .dialog_size import fit_to_content
from .placement_widget import PlacementWidget
from .project_actions import create_profile

METHODS = [("ERT", "ert")]
REVERSE = "Reverse the line"
#: sources whose line can be run either way (positions follow their numbers)
LINE_SOURCES = ("line", "points")
#: sources that make a station set, and so ask for its method
POSITION_SOURCES = ("positions", "layer")


class NewProfileDialog(QDialog):
    def __init__(self, iface, store, project: QgsProject | None = None, provider=None,
                 parent=None):
        super().__init__(parent if parent is not None else iface.mainWindow())
        self.setWindowTitle("New Profile")
        self.iface, self.store, self.provider = iface, store, provider
        self.project = project if project is not None else QgsProject.instance()
        self.profile = None
        self.last_error = None
        self.last_warning = None
        self._file = ""                     # the positions file the name was taken from

        self.name_edit = QLineEdit()
        self.name_edit.setToolTip("Name of the profile")
        self.method_combo = QComboBox()
        for label, value in METHODS:
            self.method_combo.addItem(label, value)
        self.method_combo.setToolTip("Method of the station set made from the positions")
        self._form = QFormLayout()
        self._form.addRow("Name", self.name_edit)
        self._form.addRow("Method", self.method_combo)

        self.placement = PlacementWidget(iface, store, self.project, allow_existing=False)
        self.placement.setObjectName("placement")
        self.reverse_check = QCheckBox(REVERSE)
        self.reverse_check.setObjectName("reverse_check")
        self.reverse_check.setToolTip("The profile runs from the line's last vertex, or from "
                                      "the end point to the start point")

        self._page = page = QWidget()
        column = QVBoxLayout(page)
        column.addLayout(self._form)
        column.addWidget(self.placement)
        column.addWidget(self.reverse_check)
        column.addStretch(1)
        self._scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        buttons = self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(buttons)

        self.placement.changed.connect(self._sync)
        self.resize(1, 1)                   # the first fit sets the size; later ones only grow
        self._widened = False
        self._sync()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._widened:
            self._widened = True
            self._widen_for_hints()

    def _widen_for_hints(self) -> None:
        """Open wide enough for the placement's hints. They never widen the dialog
        themselves (a long layer name must not), so the content size leaves them cut."""
        self.layout().activate()
        short = 0
        for label in self.placement.findChildren(QLabel):
            if (label.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
                    and label.isVisibleTo(self) and label.text()):
                short = max(short, label.fontMetrics().horizontalAdvance(label.text())
                            - label.width())
        if short > 0:
            screen = self.screen().availableGeometry()
            self.resize(min(self.width() + short + 2, screen.width() - 40), self.height())

    # -- state -------------------------------------------------------------------------------
    def _sync(self) -> None:
        source = self.placement.source()
        self._form.setRowVisible(self.method_combo, source in POSITION_SOURCES)
        self.reverse_check.setVisible(source in LINE_SOURCES)
        path = self.placement.file_widget.filePath().strip()
        if source == "positions" and path and path != self._file:
            self._file = path               # a new file names an unnamed profile
            if not self.name_edit.text().strip():
                self.name_edit.setText(Path(path).stem)
        bar = self._scroll.verticalScrollBar().sizeHint().width()
        self._scroll.setMinimumWidth(self._page.minimumSizeHint().width() + bar
                                     + 2 * self._scroll.frameWidth())
        fit_to_content(self, self._scroll, self._buttons)

    def _placement(self):
        """The placement chosen, the line reversed when asked. ValueError when incomplete."""
        placement = self.placement.placement()
        if self.placement.source() in LINE_SOURCES and self.reverse_check.isChecked():
            placement = replace(placement, line_xy=placement.line_xy[::-1].copy())
        return placement

    # -- saving ------------------------------------------------------------------------------
    def accept(self) -> None:
        try:
            name = self.name_edit.text().strip()
            if not name:
                raise ValueError("Enter a name for the profile")
            profile = create_profile(self.store, self._placement(), name,
                                     self.method_combo.currentData(), self.project,
                                     self.provider)
        except (ValueError, OSError, RuntimeError) as exc:     # RuntimeError: GDAL write
            self._error(str(exc))
            return
        self.profile = profile
        self.last_warning = None
        twins = [p for _err, p, _rev in matching_profiles(self.store.profiles(), profile.xy,
                                                          CURVE_TOLERANCE)
                 if p.id != profile.id]
        if twins:
            self._warn_duplicate(profile, twins)
        super().accept()

    def _warn_duplicate(self, profile, twins) -> None:
        """Non-blocking: the profile is saved, but the map and section cannot tell the
        twins apart by their line (the section panel shows the profile it opened)."""
        names = ", ".join(f"“{p.name or p.id}”" for p in twins)
        self.last_warning = (f"Profile “{profile.name}” lies on the same line as {names}. "
                             "Pick Profile on Map and QGIS's own elevation profile tool "
                             "cannot tell them apart; choose it in the section panel's "
                             "Profile list.")
        bar = self.iface.messageBar() if hasattr(self.iface, "messageBar") else None
        if bar is not None:
            bar.pushMessage(self.windowTitle(), self.last_warning, Qgis.MessageLevel.Warning, 15)

    def _error(self, message: str) -> None:
        self.last_error = message
        QMessageBox.warning(self, self.windowTitle(), message)

    def done(self, result: int) -> None:
        self.placement.cancel_pick()
        self.placement.clear_overlay()
        super().done(result)
