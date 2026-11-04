"""Interpretation controls of the section dock: the tool bar row, drawing, saving.

Every finished piece goes through the open attribute form, is saved to the store at once,
the derived 3D/footprint layers are rebuilt and the section is redrawn.
"""
from __future__ import annotations

import weakref

from qgis.core import QgsExpressionContextUtils, QgsProject
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QToolButton

from ..core.interpretation import InterpFeature, InterpPiece, new_id, normalise, type_suggestions
from ..ui.interp_form import ask_feature
from .interp_tools import DrawTool

TOOLS = (("pan", "Pan"), ("line", "Line"), ("polygon", "Polygon"), ("point", "Point"))


def current_author() -> str:
    scope = QgsExpressionContextUtils.globalScope()
    for name in ("user_full_name", "user_account_name"):
        value = scope.variable(name)
        if value:
            return str(value)
    import getpass
    try:
        return getpass.getuser()
    except Exception:                       # no account name available
        return ""


class InterpController(QObject):
    def __init__(self, dock):
        super().__init__(dock)
        # weak: a strong back-reference makes dock <-> controller a Python cycle, so the dock's
        # wrapper outlives its C++ object and a late garbage collection deletes it twice
        self._dock = weakref.ref(dock)
        self.tool = None
        #: (feature, type suggestions, letters in use) -> edited feature or None (cancel)
        self.form_factory = lambda f, s, letters: ask_feature(self.dock, f, s, letters)
        self.bar = QHBoxLayout()
        self.bar.addWidget(QLabel("Interpretation"))
        self.buttons: dict[str, QToolButton] = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for key, text in TOOLS:
            b = QToolButton()
            b.setText(text)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.stop() if k == "pan" else self.start(k))
            self.group.addButton(b)
            self.bar.addWidget(b)
            self.buttons[key] = b
        self.bar.addStretch(1)
        self.buttons["pan"].setChecked(True)
        dock.profile_changed.connect(self._profile_changed)

    @property
    def dock(self):
        return self._dock()

    # -- tools -------------------------------------------------------------------------------
    def start(self, kind: str) -> None:
        if self.dock.provider is None or self.dock.current_profile_id() is None:
            self.stop()
            return
        self.tool = DrawTool(self.dock.canvas, kind, lambda pts, k=kind: self._finished(k, pts),
                             on_cancel=self.stop,
                             on_hover=lambda pp: self.dock._hovered(None, pp))
        self.dock.canvas.setTool(self.tool)
        self.buttons[kind].setChecked(True)
        self.dock.canvas.setFocus()

    def _profile_changed(self, *_args) -> None:
        self.stop()

    def stop(self) -> None:
        dock = self.dock
        if dock is None:
            return
        dock.canvas.setTool(dock._pan_tool)
        self.tool = None
        self.buttons["pan"].setChecked(True)

    # -- saving ------------------------------------------------------------------------------
    def _based_on(self, profile_id: str) -> tuple[str, str]:
        try:
            for layer in self.dock.provider.layers(profile_id):
                if layer.mesh is not None:
                    return layer.dataset.id, str(layer.dataset.version)
        except Exception:                   # a broken layer must not block saving
            pass
        return "", ""

    def chainages(self) -> dict:
        return {p.id: p.chainage for p in self.dock.provider.store.profiles()}

    def _finished(self, kind: str, points: list) -> None:
        store = self.dock.provider.store
        profile_id = self.dock.current_profile_id()
        if profile_id is None:
            return
        store.ensure_interpretation()
        version = store.current_version()
        dataset, dversion = self._based_on(profile_id)
        piece = normalise(InterpPiece(new_id(), version.id, "", profile_id, kind, points,
                                      based_on_dataset=dataset, based_on_version=dversion))
        feature = InterpFeature(new_id(), version.id, author=current_author())
        letters = {f.letter for f in store.features(version.id) if f.letter}
        edited = self.form_factory(feature, type_suggestions(store.used_types()), letters)
        if edited is None:
            return
        edited.author = edited.author or feature.author
        store.save_feature(edited)
        piece.feature_id = edited.id
        store.save_piece(piece)
        self.changed(version.id)

    def changed(self, version_id: str) -> None:
        """Rebuild the derived layers of ``version_id``, add them if new, redraw."""
        from ..ui.interp_layers import add_interp_layers, reload_interp_layers
        store = self.dock.provider.store
        project = QgsProject.instance()
        add_interp_layers(store, project)
        store.rebuild_derived(version_id, self.chainages())
        reload_interp_layers(store, project)
        self.dock.provider.notify_changed()
