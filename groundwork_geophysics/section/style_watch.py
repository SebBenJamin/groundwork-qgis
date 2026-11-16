"""Redraw the section when the user restyles one of the workbench's own QGIS layers (the
interpretation and field-note layers). Third-party context layers are watched by the context
gatherer; these are left out there (they are the plugin's own), so without this watch a new
style showed only after the profile was reopened.

Store writes reload these layers (``dataChanged``): not watched, the writer redraws anyway."""
from __future__ import annotations

from typing import Callable

from qgis.PyQt.QtCore import QTimer

DEBOUNCE_MS = 300
_SIGNALS = ("rendererChanged", "styleChanged", "repaintRequested")


class StyleWatch:
    def __init__(self, project, layers: Callable[[], list], on_change: Callable[[], None]):
        self.project, self._layers, self._on_change = project, layers, on_change
        self._watched: list = []
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._fire)
        project.layersAdded.connect(self._rewatch)
        project.layersRemoved.connect(self._rewatch)
        self._rewatch()

    def _fire(self) -> None:
        self._on_change()

    def _changed(self, *_args) -> None:
        self._timer.start()

    def _disconnect(self) -> None:
        for layer in self._watched:
            for name in _SIGNALS:
                try:
                    getattr(layer, name).disconnect(self._changed)
                except (TypeError, RuntimeError):     # already gone or not connected
                    pass
        self._watched = []

    def _rewatch(self, *_args) -> None:
        self._disconnect()
        try:
            layers = list(self._layers())
        except Exception:                             # store gone, project closing
            layers = []
        for layer in layers:
            for name in _SIGNALS:
                getattr(layer, name).connect(self._changed)
        self._watched = layers

    def unload(self) -> None:
        for signal in (self.project.layersAdded, self.project.layersRemoved):
            try:
                signal.disconnect(self._rewatch)
            except (TypeError, RuntimeError):
                pass
        self._disconnect()
        self._timer.stop()
