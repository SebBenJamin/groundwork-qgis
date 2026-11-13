"""'Profile Properties' dialog: an existing profile's name, its surveyed positions (a positions
file or a point layer), its stated station spacing and its reference height.

Positions are optional ("Set surveyed positions" is off). They either keep the line (the
positions are projected onto it; points far off it are listed first) or move the line to the
points (field notes, the current interpretation and every station set go with it, after a
confirmation). The positions go to a chosen station set of the profile, which keeps its id,
name and method (datasets keep their link), or to a new set. Name, positions and spacing apply
on OK; the reference height applies at once. The dialog is modal: the sources used here need no
map picking.
"""
from __future__ import annotations

import math
from dataclasses import replace

from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLineEdit,
                                 QMessageBox, QPushButton, QRadioButton, QScrollArea,
                                 QVBoxLayout, QWidget)

from ..core.model import Profile, attach_positions, profile_from_positions
from ..core.numbers import fmt_trim, parse
from ..section.topography import LOCAL_KINDS
from . import profile_actions
from .dialog_size import fit_to_content
from .placement_widget import PlacementWidget
from .reference_height_dialog import ask_reference_height

NEW_SET = "New set"
METHOD = "ert"
KEEP_TEXT = "Keep the line"
MOVE_TEXT = "Move the line to the points"
REFERENCE_TEXT = "Reference Height…"
NO_REFERENCE_TIP = "Only a profile without real heights has a reference height"
SOURCES = ("positions", "layer")


class ProfilePropertiesDialog(QDialog):
    def __init__(self, iface, store, profile_id: str, provider,
                 project: QgsProject | None = None, parent=None, dock=None):
        super().__init__(parent if parent is not None else iface.mainWindow())
        self.setWindowTitle("Profile Properties")
        self.iface, self.store, self.provider, self.dock = iface, store, provider, dock
        self.profile_id = profile_id
        self.project = project if project is not None else QgsProject.instance()
        self.last_error = None
        #: (parent, electrodes, length, current) -> (s, z), None (cancel) or False (remove);
        #: tests replace it
        self.ask_reference = ask_reference_height
        profile = store.profile(profile_id)

        self.name_edit = QLineEdit(profile.name)
        self.name_edit.setToolTip("Name of the profile")
        self.spacing_edit = QLineEdit()
        self.spacing_edit.setObjectName("spacing_edit")
        self.spacing_edit.setToolTip("The stated distance between neighbouring stations. "
                                     "Empty: no spacing stated.")
        stated = profile.metadata.get("electrode_spacing")
        if stated is not None:
            self.spacing_edit.setText(fmt_trim(float(stated), 3))
        self.reference_button = QPushButton(REFERENCE_TEXT)
        self.reference_button.clicked.connect(self._ask_reference)
        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Station spacing (m)", self.spacing_edit)
        form.addRow("Height", self.reference_button)

        self.placement = PlacementWidget(iface, store, self.project, allow_existing=False,
                                         sources=SOURCES, show_spacing=False)
        self.placement.setObjectName("placement")
        self.placement.setTitle("Surveyed Positions")
        self.set_positions = QCheckBox("Set surveyed positions")
        self.set_positions.setToolTip("Read the stations' coordinates from a file or a point "
                                      "layer; nothing changes while this is off")
        self.set_combo = QComboBox()
        self.set_combo.setToolTip("The station set the positions replace; datasets on it keep "
                                  "their link")
        sets = store.station_sets(profile_id)
        for station_set in sets:
            self.set_combo.addItem(station_set.name or station_set.id, station_set.id)
        self.set_combo.addItem(NEW_SET, None)
        self.set_combo.setCurrentIndex(0 if len(sets) == 1 else self.set_combo.count() - 1)
        self.keep_line = QRadioButton(KEEP_TEXT)
        self.keep_line.setToolTip("Project the positions onto the line the profile has")
        self.keep_line.setChecked(True)
        self.move_line = QRadioButton(MOVE_TEXT)
        self.move_line.setToolTip("Draw the line through the positions; field notes and the "
                                  "current interpretation move with it")
        extra = QFormLayout()
        extra.addRow("Station set", self.set_combo)
        extra.addRow(self.keep_line)
        extra.addRow(self.move_line)
        self._positions_page = QWidget()
        below = QVBoxLayout(self._positions_page)
        below.setContentsMargins(0, 0, 0, 0)
        below.addWidget(self.placement)
        below.addLayout(extra)
        self._positions_page.setVisible(False)

        self._page = page = QWidget()
        column = QVBoxLayout(page)
        column.addLayout(form)
        column.addWidget(self.set_positions)
        column.addWidget(self._positions_page)
        column.addStretch(1)
        self._scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self._buttons = buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(buttons)

        self.spacing_edit.textChanged.connect(self.placement.spacing_edit.setText)
        self.placement.changed.connect(self._sync)
        self.set_positions.toggled.connect(self._positions_page.setVisible)
        self.set_positions.toggled.connect(self._sync)
        self.resize(1, 1)                   # the first fit sets the size; later ones only grow
        self._sync_reference()
        self._sync()

    # -- state -------------------------------------------------------------------------------
    def _is_local(self) -> bool:
        try:
            surface = self.provider.surface(self.profile_id)
        except Exception:                   # a broken dataset must not break the dialog
            return False
        return surface is not None and surface.kind in LOCAL_KINDS

    def _sync_reference(self) -> None:
        local = self._is_local()
        self.reference_button.setEnabled(local)
        self.reference_button.setToolTip(
            "Set the height of one point on the profile, so its section is drawn at real "
            "elevations. Applies at once." if local else NO_REFERENCE_TIP)

    def _sync(self, *_args) -> None:
        bar = self._scroll.verticalScrollBar().sizeHint().width()
        self._scroll.setMinimumWidth(self._page.minimumSizeHint().width() + bar
                                     + 2 * self._scroll.frameWidth())
        fit_to_content(self, self._scroll, self._buttons)

    # -- reference height --------------------------------------------------------------------
    def _ask_reference(self) -> None:
        profile = self.store.profile(self.profile_id)
        result = self.ask_reference(self, self.provider.electrodes(self.profile_id),
                                    profile.chainage.length,
                                    profile.metadata.get("reference_height"))
        if result is None:
            return
        s, z = (None, None) if result is False else result
        if self.dock is not None and self.dock.current_profile_id() == self.profile_id:
            self.dock.set_reference_height(s, z)        # one step on the panel's undo stack
        else:
            self.provider.set_reference_height(self.profile_id, s, z)
        self._sync_reference()

    # -- reading the form --------------------------------------------------------------------
    def _spacing(self) -> float | None:
        text = self.spacing_edit.text().strip()
        if not text:
            return None
        try:
            value = parse(text)
        except ValueError:
            raise ValueError("Type the station spacing as a number, for example "
                             f"{fmt_trim(2.5)}") from None
        if not (math.isfinite(value) and value > 0):
            raise ValueError("The station spacing must be greater than 0 m")
        return value

    def _new_set(self, profile: Profile, positions):
        """The station set the positions make on ``profile``'s line: in the chosen set's place
        (its id, name and method) or as a new set named like the profile."""
        chosen = self.set_combo.currentData()
        old = next((s for s in self.store.station_sets(profile.id) if s.id == chosen), None)
        made = attach_positions(profile, profile.name, METHOD, positions)
        return made if old is None else replace(made, id=old.id, name=old.name,
                                                method=old.method)

    # -- saving ------------------------------------------------------------------------------
    def accept(self) -> None:
        try:
            done = self._apply()
        except (ValueError, OSError, RuntimeError, KeyError) as exc:   # RuntimeError: GDAL
            self._error(str(exc))
            return
        if done:
            super().accept()

    def _apply(self) -> bool:
        """Apply the form; False when the user cancelled a confirmation (nothing changed)."""
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("Enter a name for the profile")
        spacing = self._spacing()
        old = self.store.profile(self.profile_id)
        positions = self.placement.placement().positions if self.set_positions.isChecked() else None
        move = positions is not None and self.move_line.isChecked()
        made, line = None, old.xy
        if positions is not None:
            if move:
                line = profile_from_positions(name, self.store.crs_authid, positions)[0].xy
            target = Profile(old.id, name, line, old.crs_authid, dict(old.metadata))
            made = self._new_set(target, positions)
            if move:
                counts = self.store.profile_contents(old.id)
                if not profile_actions.confirm_move(self, old.name, counts):
                    return False
            elif made.warnings and not profile_actions.confirm_off_line(self, made.warnings):
                return False
        if name != old.name:
            self.store.rename_profile(self.profile_id, name)    # checks empty and duplicates
        metadata = dict(old.metadata)
        if spacing is None:
            metadata.pop("electrode_spacing", None)
        else:
            metadata["electrode_spacing"] = float(spacing)
        if move:
            self.store.move_profile_line(self.profile_id, line, made, metadata)
            self._after_move()
        elif made is not None or metadata != old.metadata:
            kept = self.store.profile(self.profile_id)
            kept.metadata = metadata
            self.store.save_import(kept, made, None)
        if name != old.name or move or made is not None or metadata != old.metadata:
            self._refresh()
        return True

    def _after_move(self) -> None:
        """The line changed: the derived layers, the notes on the map and the panel's undo
        steps (they predate the move) follow."""
        from .field_notes_dialog import after_change
        store = self.store
        if self.dock is not None:
            self.dock.interp.undo.clear()
        if self.dock is not None and store.has_interpretation():
            self.dock.interp.changed()                # rebuilds the current version's layers
        elif store.has_interpretation():
            store.rebuild_derived(store.current_version().id,
                                  {p.id: p.chainage for p in store.profiles()})
        if store.has_field_notes():
            after_change(store, None, self.project)   # rebuilds the notes' map geometry

    def _refresh(self) -> None:
        from .project_actions import refresh_layers
        refresh_layers(self.store, self.project)
        self.provider.notify_changed()
        if self.dock is not None:
            self.dock._fill_combo()

    def _error(self, message: str) -> None:
        self.last_error = message
        QMessageBox.warning(self, self.windowTitle(), message)

    def done(self, result: int) -> None:
        self.placement.cancel_pick()
        self.placement.clear_overlay()
        super().done(result)
