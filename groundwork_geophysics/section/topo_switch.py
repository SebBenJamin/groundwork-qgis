"""The section panel's "Topography" combo: which surface depth models hang from, and the
"Reference Height…" button of a profile without heights."""
from __future__ import annotations

import weakref

from qgis.PyQt.QtWidgets import QComboBox, QLabel, QToolButton

from .topography import LOCAL_KINDS

#: "Local" is an indicator, never chosen by hand: shown (and the only entry enabled) while
#: the profile has no heights of its own (a local model's top or the flat line)
ENTRIES = (("Stations", "stations"), ("DEM", "dem"), ("Local", "local"))
LOCAL_INDEX = 2
REFERENCE_TEXT = "Reference Height…"
REFERENCE_TIP = ("Type the height of one point on this profile, which has no heights yet: the "
                 "section and its interpretation move to real elevations through it")
REFERENCE_OFF_TIP = ("Only for a profile without heights; this one has heights from its "
                     "stations, the DEM or a model")
NO_PROFILE_TIP = "Open a profile first"
LOCAL_TIP = ("This profile has no heights yet: the section is drawn in depth below its "
             "surface. Set a reference height, or add stations with heights or a DEM.")


class TopoSwitch:
    """Combo (Stations/DEM/Local) bound to the open profile of ``dock``. The choice is saved
    in the profile by ``provider.set_topography_source``; DEM is disabled without DEM data.
    "Reference Height…" sets the reference of a profile without heights (on the dock's
    undo stack)."""

    def __init__(self, dock):
        self.dock = weakref.proxy(dock)         # no reference cycle with the dock
        self.label = QLabel("Topography")
        self.combo = QComboBox()
        for text, key in ENTRIES:
            self.combo.addItem(text, key)
        self.combo.setToolTip("Surface the depth models hang from")
        self.combo.currentIndexChanged.connect(self._changed)
        self.reference_button = QToolButton()
        self.reference_button.setText(REFERENCE_TEXT)
        self.reference_button.clicked.connect(self._ask_reference)
        #: (parent, electrodes, length, current) -> (s, z), None (cancel) or False (remove);
        #: tests replace it
        from ..ui.reference_height_dialog import ask_reference_height
        self.ask_reference = ask_reference_height
        self.sync()

    def _surface_kind(self, provider, profile) -> str | None:
        try:
            surface = provider.surface(profile.id)
        except Exception:                       # a broken dataset must not break the panel
            return None
        return None if surface is None else surface.kind

    def sync(self) -> None:
        """Show the open profile's saved choice; disable DEM when it has no data. A saved
        "dem" without DEM data shows "Stations", the surface actually used (the saved
        choice is kept, so the DEM is used again once it has data). A profile without
        heights shows "Local", the only entry enabled, and enables "Reference Height…"."""
        try:
            provider, profile = self.dock.provider, self.dock._profile
        except ReferenceError:                  # the dock is gone
            return
        have_dem = False
        choice = "stations"
        local = False
        if provider is not None and profile is not None:
            have_dem = provider.has_dem(profile.id)
            try:                                # fresh: the dock's copy may predate a switch
                choice = provider.store.profile(profile.id).metadata.get("topography", "stations")
            except KeyError:
                pass
            local = self._surface_kind(provider, profile) in LOCAL_KINDS
        if choice == "dem" and not have_dem:
            choice = "stations"
        if local:
            choice = "local"
        model = self.combo.model()
        self.combo.blockSignals(True)
        model.item(0).setEnabled(not local)
        model.item(1).setEnabled(have_dem and not local)
        model.item(LOCAL_INDEX).setEnabled(local)
        self.combo.view().setRowHidden(LOCAL_INDEX, not local)
        self.combo.setCurrentIndex(max(0, self.combo.findData(choice)))
        self.combo.setEnabled(profile is not None)
        self.combo.setToolTip(LOCAL_TIP if local else "Surface the depth models hang from")
        self.combo.blockSignals(False)
        self.reference_button.setEnabled(local)
        self.reference_button.setToolTip(REFERENCE_TIP if local else
                                         NO_PROFILE_TIP if profile is None else
                                         REFERENCE_OFF_TIP)

    def _changed(self, _index: int) -> None:
        try:
            dock = self.dock
            if dock.provider is None or dock._profile is None:
                return
            source = self.combo.currentData()
            if source == "local":               # an indicator, not a choice
                return
            dock.provider.set_topography_source(dock._profile.id, source)
        except ReferenceError:                  # the dock is gone
            return

    def _ask_reference(self, *_args) -> None:
        try:
            dock = self.dock
            provider, profile = dock.provider, dock._profile
        except ReferenceError:                  # the dock is gone
            return
        if provider is None or profile is None:
            return
        from .dock import REFERENCE_FAILED, STORE_ERRORS
        try:
            fresh = provider.store.profile(profile.id)
            electrodes = provider.electrodes(profile.id)
        except KeyError:
            return
        except STORE_ERRORS as exc:             # a slot never raises
            dock.readout.setText(REFERENCE_FAILED.format(error=exc))
            return
        answer = self.ask_reference(self.reference_button.window(), electrodes,
                                    fresh.chainage.length,
                                    fresh.metadata.get("reference_height"))
        if answer is None:
            return
        if answer is False:
            dock.set_reference_height(None, None)
        else:
            dock.set_reference_height(*answer)
