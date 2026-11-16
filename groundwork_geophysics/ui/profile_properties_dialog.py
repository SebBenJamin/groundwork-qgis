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

from qgis.core import Qgis, QgsProject
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                                 QLabel, QLineEdit, QMessageBox, QPushButton, QRadioButton,
                                 QScrollArea, QVBoxLayout, QWidget)

from .help import add_help_button
from ..core.model import Profile, attach_positions, profile_from_positions
from ..core.numbers import fmt_trim, parse
from ..core.placement import fit_report
from ..section.data import is_map_dataset
from ..section.dock import NOT_REFRESHED, REFERENCE_FAILED, STORE_ERRORS
from ..section.placement_resolve import resolve
from ..section.topography import LOCAL_KINDS
from . import profile_actions
from .dialog_size import fit_to_content
from .fit_line import fit_line, show_fit
from .placement_widget import PlacementWidget
from .project_actions import NotRefreshed, after_save
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
        self.last_error = self.last_warning = None
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
        #: how the profile's model would sit on the known points with the spacing and
        #: positions as edited (the same report as Add Data's)
        self.fit_label = QLabel()
        self.fit_label.setObjectName("fit_label")
        self.fit_label.setWordWrap(True)
        self.reference_button = QPushButton(REFERENCE_TEXT)
        self.reference_button.clicked.connect(self._ask_reference)
        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Station spacing (m)", self.spacing_edit)
        form.addRow(self.fit_label)
        form.addRow("Height", self.reference_button)
        self._form = form

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
        add_help_button(buttons, "profile_properties")
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(buttons)

        self.spacing_edit.textChanged.connect(self.placement.spacing_edit.setText)
        self.placement.changed.connect(self._sync)
        self.set_positions.toggled.connect(self._positions_page.setVisible)
        self.set_positions.toggled.connect(self._sync)
        for signal in (self.spacing_edit.textChanged, self.set_combo.currentIndexChanged,
                       self.keep_line.toggled):
            signal.connect(self._sync)
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
        try:
            text, warn = self._fit()
        except Exception:                   # noqa: BLE001 - feedback only; OK says what is wrong
            text, warn = "", False
        show_fit(self.fit_label, text, warn)
        self._form.setRowVisible(self.fit_label, bool(text))
        bar = self._scroll.verticalScrollBar().sizeHint().width()
        self._scroll.setMinimumWidth(self._page.minimumSizeHint().width() + bar
                                     + 2 * self._scroll.frameWidth())
        fit_to_content(self, self._scroll, self._buttons)

    def _fit(self) -> tuple[str, bool]:
        """The fit line for the spacing and positions as edited (nothing saved): the known
        points of the positions when they give two, else the pins of the profile's first
        pinned dataset, resolved as the section would."""
        try:
            spacing = self._spacing()
        except ValueError:
            return "", False                # a half-typed number: said on OK
        old = self.store.profile(self.profile_id)
        metadata = dict(old.metadata)
        metadata.pop("electrode_spacing", None)
        if spacing is not None:
            metadata["electrode_spacing"] = spacing
        line, sets, known = old.xy, self.store.station_sets(self.profile_id), None
        positions = None
        if self.set_positions.isChecked():
            try:
                positions = self.placement.placement().positions
            except ValueError:
                positions = None
        if positions is not None:
            if self.move_line.isChecked():
                line = profile_from_positions(old.name, self.store.crs_authid, positions)[0].xy
            made = self._new_set(Profile(old.id, old.name, line, old.crs_authid, metadata),
                                 positions)
            others = [s for s in sets if s.id != made.id]
            if self.move_line.isChecked():          # the move projects them onto the line
                chainage = Profile(old.id, old.name, line, old.crs_authid).chainage
                others = [replace(s, chainage=chainage.project(s.xyz[:, :2])[0])
                          for s in others]
            sets = [made] + others
            known = self.placement.known_points()
        if known is not None:
            return fit_line(fit_report(*known))
        profile = Profile(old.id, old.name, line, old.crs_authid, metadata)
        layout = self.provider.layout(self.profile_id)
        layout.spacing = spacing
        for d in self.store.datasets(self.profile_id):
            if is_map_dataset(d):
                continue
            try:
                r = resolve(profile, sets, d, layout)
            except Exception:               # noqa: BLE001 - its layer shows the error
                continue
            if r.fit is not None or r.note:
                return fit_line(r.fit, r.source == "guessed", r.note)
        return "", False

    # -- reference height --------------------------------------------------------------------
    def _ask_reference(self) -> None:
        try:
            profile = self.store.profile(self.profile_id)
            electrodes = self.provider.electrodes(self.profile_id)
        except STORE_ERRORS as exc:             # a slot never raises
            self._error(REFERENCE_FAILED.format(error=exc))
            return
        result = self.ask_reference(self, electrodes, profile.chainage.length,
                                    profile.metadata.get("reference_height"))
        if result is None:
            return
        s, z = (None, None) if result is False else result
        if self.dock is not None and self.dock.current_profile_id() == self.profile_id:
            failed = self.dock.set_reference_height(s, z)   # one step on the panel's undo stack
        else:
            failed = self._set_reference(s, z)
        if failed:
            self._error(failed)
        self._sync_reference()

    def _set_reference(self, s, z) -> str | None:
        """The reference height of a profile the panel does not show (no undo step); the
        message when it could not be saved, else None."""
        try:
            self.provider.set_reference_height(self.profile_id, s, z)
        except STORE_ERRORS as exc:
            if self._stored_reference() == (None if s is None else {"s": s, "z": z}):
                return NOT_REFRESHED.format(error=exc)     # saved; what follows failed
            return REFERENCE_FAILED.format(error=exc)
        try:
            if self.store.has_interpretation():
                from .interp_layers import reload_interp_layers
                reload_interp_layers(self.store, self.project)    # pieces moved with it
        except STORE_ERRORS as exc:
            return NOT_REFRESHED.format(error=exc)
        return None

    def _stored_reference(self):
        try:
            return self.store.profile(self.profile_id).metadata.get("reference_height")
        except (*STORE_ERRORS, KeyError):
            return False                        # unknown: never equal to a value

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
        name = self.store.checked_name(self.profile_id, name)   # a duplicate: before any write
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
        metadata = dict(old.metadata)
        if spacing is None:
            metadata.pop("electrode_spacing", None)
        else:
            metadata["electrode_spacing"] = float(spacing)
        if move:
            self.store.move_profile_line(self.profile_id, line, made, metadata, name)
        elif made is not None or metadata != old.metadata or name != old.name:
            kept = self.store.profile(self.profile_id)
            kept.name, kept.metadata = name, metadata
            self.store.save_import(kept, made, None)
        steps = [self._after_move] if move else []
        if name != old.name or move or made is not None or metadata != old.metadata:
            steps.append(self._refresh)
        try:                                    # saved: what follows never fails the dialog
            after_save(None, *steps)
        except NotRefreshed as exc:
            self._warn(str(exc))
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

    def _warn(self, message: str) -> None:
        """Non-blocking, for after the dialog closes: on the message bar."""
        self.last_warning = message
        bar = self.iface.messageBar() if hasattr(self.iface, "messageBar") else None
        if bar is not None:
            bar.pushMessage(self.windowTitle(), message, Qgis.MessageLevel.Warning, 15)

    def done(self, result: int) -> None:
        self.placement.cancel_pick()
        self.placement.clear_overlay()
        super().done(result)
