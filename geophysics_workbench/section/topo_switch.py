"""The section panel's "Topography" combo: which surface depth models hang from."""
from __future__ import annotations

import weakref

from qgis.PyQt.QtWidgets import QComboBox, QLabel

ENTRIES = (("Stations", "stations"), ("DEM", "dem"))


class TopoSwitch:
    """Combo (Stations/DEM) bound to the open profile of ``dock``. The choice is saved in
    the profile by ``provider.set_topography_source``; DEM is disabled without DEM data."""

    def __init__(self, dock):
        self.dock = weakref.proxy(dock)         # no reference cycle with the dock
        self.label = QLabel("Topography")
        self.combo = QComboBox()
        for text, key in ENTRIES:
            self.combo.addItem(text, key)
        self.combo.setToolTip("Surface the depth models hang from")
        self.combo.currentIndexChanged.connect(self._changed)
        self.sync()

    def sync(self) -> None:
        """Show the open profile's saved choice; disable DEM when it has no data."""
        provider, profile = self.dock.provider, self.dock._profile
        have_dem = False
        choice = "stations"
        if provider is not None and profile is not None:
            ctx = provider.context(profile.id)
            have_dem = ctx is not None and ctx.dem is not None
            try:                                # fresh: the dock's copy may predate a switch
                choice = provider.store.profile(profile.id).metadata.get("topography", "stations")
            except KeyError:
                pass
        self.combo.blockSignals(True)
        self.combo.model().item(1).setEnabled(have_dem)
        self.combo.setCurrentIndex(max(0, self.combo.findData(choice)))
        self.combo.setEnabled(profile is not None)
        self.combo.blockSignals(False)

    def _changed(self, _index: int) -> None:
        dock = self.dock
        if dock.provider is None or dock._profile is None:
            return
        dock.provider.set_topography_source(dock._profile.id, self.combo.currentData())
