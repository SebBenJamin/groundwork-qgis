"""Section panel: a native elevation-profile canvas fed by the workbench profile source,
with a profile chooser, layer list, vertical exaggeration and a cursor readout.

Coordinates: ``open_profile`` always sets the canvas curve in the profile's own direction,
so canvas distance == forward profile chainage (what ``cursor_moved``, ``show_cursor`` and
``SectionDataProvider.identify`` use). Keep it that way, or convert (length - s) here.
"""
from __future__ import annotations

from functools import partial

import numpy as np
from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsLineString, QgsPoint,
                       QgsProfilePoint, QgsProject, QgsSettings)
from qgis.gui import QgsElevationProfileCanvas, QgsPlotToolPan
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QLineF, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor, QKeySequence, QPen, QShortcut
from qgis.PyQt.QtWidgets import (QComboBox, QDockWidget, QDoubleSpinBox, QGraphicsLineItem,
                                 QToolTip,
                                 QHBoxLayout, QLabel, QMenu, QSizePolicy, QSplitter,
                                 QToolButton,
                                 QVBoxLayout,
                                 QWidget)

from ..core.layout import KIND_TEXT, kind_text
from ..core.numbers import fmt_trim
from ..ids import LEGACY_ID
from .data import identify_layers, layer_name
from .dock_context import context_lines
from .layer_list import LayerList
from .profile_source import SOURCE_ID
from .readout import format_readout
from .topo_switch import TopoSwitch
from .view_extent import data_extent, headroom_px
from .view_fit import ViewFitter

OBJECT_NAME = "GeophysicsWorkbenchSectionDock"
AUTO_VE = 0.0                   # the VE box's "Auto": the exaggeration that fills the panel
SPLITTER_KEY = f"{LEGACY_ID}/section/splitter"
DEFAULT_VE = AUTO_VE
HINT_NO_PROJECT = "No project open."
HINT_NO_PROFILE = "Choose a profile above, or pick one on the map."
HINT_NO_PROFILE_LINK = ('Choose a profile above, or <a href="pick">pick one on the map</a>.')
HINT_HOVER = "Move the mouse over the section to read values."
MISSING_PROFILE = "Profile not found in the Groundwork project; it may have been deleted."
SETTLED = "Interpretation on {profile} moved onto the real surface: {n} piece(s)"
SETTLE_FAILED = ("Could not move the interpretation on {profile} onto the real surface: "
                 "{error}. It is tried again when the section is refreshed.")
REFERENCE_FAILED = "Could not save the reference height: {error}. Nothing was changed."
#: after the store was written, something that follows it failed
NOT_REFRESHED = "Saved, but the view could not be refreshed: {error}"
#: what a store write raises (GDAL: RuntimeError) when the file cannot be written
STORE_ERRORS = (ValueError, OSError, RuntimeError)
HIDE_IN_SECTION = "Hide in Section"
SHOW_IN_SECTION = "Show in Section"
NO_ID_TIP = "This borehole has no id in its layer, so it cannot be hidden on its own."


def show_hidden_text(count: int) -> str:
    return f"Show Hidden Boreholes ({count})"


def _registered_source_for(provider):
    source = QgsApplication.profileSourceRegistry().findSourceById(SOURCE_ID)
    return source if getattr(source, "provider", None) is provider else None


LOCAL_INFO = "Local section: no heights yet, values are depth below the surface"


class _Readout(QLabel):
    """One line under the section. Its text never sizes the panel (a long readout over
    cores or crossings widened the panel, and the locked-scale canvas seemed to zoom in);
    what does not fit is cut off, and the tooltip shows it all."""

    def __init__(self, lines: int = 2):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(1)
        # always two lines tall: a second line (e.g. over a borehole) must not shrink the
        # canvas, which would re-fit the section while the user reads it
        self.setFixedHeight(lines * self.fontMetrics().lineSpacing() + 4)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)


class SectionDock(QDockWidget):
    cursor_moved = pyqtSignal(float, float)     # forward chainage, elevation
    cursor_left = pyqtSignal()                  # the mouse left the section
    profile_changed = pyqtSignal(object)        # open profile id, or None when closed
    borehole_clicked = pyqtSignal(int, str)     # (borehole entry, label): open the viewer
    rename_requested = pyqtSignal(str)          # profile id: "Profile Properties…"
    delete_requested = pyqtSignal(str)          # profile id: "Delete Profile…"

    def __init__(self, parent=None):
        super().__init__("Geophysics section", parent)
        self.setObjectName(OBJECT_NAME)
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea
                             | Qt.DockWidgetArea.TopDockWidgetArea)
        self.provider = None
        self._source = None
        self._profile = None
        self._layers = None                     # cached provider.layers() of the open profile
        self._ctx = None                        # cached (context items, station line), dock_context
        self._topo = None
        self._coverage = None                   # (min, max) station chainage, with _topo
        self._cursor_s = None
        self._click_pos = None
        self.details_popup = None               # details with an "Open in borehole viewer" link

        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(180)
        self.profile_combo.currentIndexChanged.connect(self._combo_changed)
        self.profile_combo.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.profile_combo.customContextMenuRequested.connect(self._show_profile_menu)
        self.profile_combo.setToolTip("Right-click for the profile's properties or to delete it")
        self.topo = TopoSwitch(self)
        self.topo_combo = self.topo.combo
        self.ve_spin = QDoubleSpinBox()
        self.ve_spin.setRange(AUTO_VE, 20.0)
        self.ve_spin.setDecimals(1)
        self.ve_spin.setSingleStep(0.5)
        self.ve_spin.setSpecialValueText("Auto")     # the minimum: fill the panel
        self.ve_spin.setValue(DEFAULT_VE)
        self.ve_spin.setSuffix(" ×")
        self.ve_spin.setToolTip("Vertical exaggeration (Auto: fill the panel)")
        self.ve_spin.valueChanged.connect(self._ve_changed)
        zoom_button = QToolButton()
        zoom_button.setText("Zoom Full")
        zoom_button.setToolTip("Show the whole section in the panel")
        zoom_button.clicked.connect(self.zoom_full)

        self.canvas = QgsElevationProfileCanvas()
        QgsApplication.profileSourceRegistry().profileSourceRegistered.connect(
            self._keep_own_source)
        self.canvas.setProject(QgsProject.instance())
        self.canvas.setLockAxisScales(True)
        self.canvas.setMinimumHeight(180)
        # a plot tool must be installed or canvasPointHovered never fires (ADR 0001)
        self._pan_tool = QgsPlotToolPan(self.canvas)
        self.canvas.setTool(self._pan_tool)
        self.canvas.canvasPointHovered.connect(self._hovered)
        self.fit = ViewFitter(self.canvas, self.ve_spin, self._fit_extent, self._update_guide,
                              self, self._fit_headroom)
        self.canvas.activeJobCountChanged.connect(self._jobs_changed)
        self.canvas.plotAreaChanged.connect(self._update_guide)
        self.canvas.scaleChanged.connect(self._update_guide)
        self.canvas.installEventFilter(self)
        self.canvas.viewport().installEventFilter(self)
        self.guide_line = QGraphicsLineItem()
        pen = QPen(QColor(200, 0, 0), 1.5, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.guide_line.setPen(pen)
        self.guide_line.setZValue(1000)
        self.guide_line.hide()
        self.canvas.scene().addItem(self.guide_line)

        self.layer_list = LayerList()
        self.readout = _Readout()
        self._reference_error: str | None = None     # set while a reference step applies
        self.readout.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info = _Readout(lines=1)           # which electrodes are shown, local section
        self.info.hide()
        self.errors = QLabel()
        self.errors.setStyleSheet("color: #c00000;")
        self.errors.setWordWrap(True)
        self.errors.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.errors.hide()

        top = QHBoxLayout()
        top.addWidget(QLabel("Profile"))
        top.addWidget(self.profile_combo)
        # Pick on Map next to the list (the plugin gives it its map tool action)
        self.pick_button = QToolButton()
        self.pick_button.setAutoRaise(True)
        top.addWidget(self.pick_button)
        top.addWidget(self.topo.label)
        top.addWidget(self.topo_combo)
        top.addWidget(self.topo.reference_button)
        top.addStretch(1)
        top.addWidget(QLabel("Vertical exaggeration"))
        top.addWidget(self.ve_spin)
        top.addWidget(zoom_button)
        # an empty panel says what to do instead of showing empty axes
        self.empty_hint = QLabel(HINT_NO_PROFILE)
        self.empty_hint.linkActivated.connect(self._hint_link)
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setMinimumHeight(180)
        view = QWidget()
        view_layout = QVBoxLayout(view)
        view_layout.setContentsMargins(0, 0, 0, 0)
        view_layout.addWidget(self.canvas)
        view_layout.addWidget(self.empty_hint)
        self.canvas.hide()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(view)
        splitter.addWidget(self.layer_list)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setCollapsible(0, False)
        self.splitter = splitter
        state = QgsSettings().value(SPLITTER_KEY)       # the width the user dragged to
        if state is not None:
            splitter.restoreState(state)
        splitter.splitterMoved.connect(
            lambda *_a: QgsSettings().setValue(SPLITTER_KEY, splitter.saveState()))
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addLayout(top)
        from .interp_controller import InterpController
        self.interp = InterpController(self)
        # Ctrl+Z / Ctrl+Y (and Ctrl+Shift+Z) while the panel has focus, as in QGIS
        stack = self.interp.undo.stack
        self.undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.redo_shortcut_alt = QShortcut(QKeySequence("Ctrl+Shift+Z"), self)
        for shortcut, slot in ((self.undo_shortcut, stack.undo), (self.redo_shortcut, stack.redo),
                               (self.redo_shortcut_alt, stack.redo)):
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        layout.addLayout(self.interp.bar)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.info)
        layout.addWidget(self.readout)
        layout.addWidget(self.errors)
        self.setWidget(body)

        self._refresh_timer = QTimer(self)      # coalesces bursts of provider changes
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.timeout.connect(self._refresh_now)
        self._set_hint()

    # -- provider ----------------------------------------------------------------------------
    def set_provider(self, provider, source=None) -> None:
        """Show ``provider``'s profiles (``None`` clears the panel). ``source`` is the
        registered profile source for it; when omitted the registry is searched. The old
        source is detached from the canvas first, so it can be unregistered afterwards."""
        if self.provider is not None:
            self.provider.active_profile_id = None
            if self._on_provider_changed in self.provider.on_change:
                self.provider.on_change.remove(self._on_provider_changed)
        self.canvas.setSources([])
        self._refresh_timer.stop()
        self.provider = provider
        self._source = None
        self._close_profile()
        if provider is not None:
            self._source = source if source is not None else _registered_source_for(provider)
            provider.on_change.append(self._on_provider_changed)
            if self._source is not None:
                self.canvas.setSources([self._source])
        self._fill_combo()
        self._set_hint()

    def _keep_own_source(self, *_args) -> None:
        """QGIS adds every newly registered profile source (e.g. a plate frame's) to every
        profile canvas: the panel draws its own source only."""
        if self._source is None:
            return
        own = self._source.profileSourceId()
        if [s.profileSourceId() for s in self.canvas.sources()] != [own]:
            self.canvas.setSources([self._source])

    def _on_provider_changed(self) -> None:
        if not sip.isdeleted(self):
            self._refresh_timer.start(0)

    def _refresh_now(self) -> None:
        if self.provider is None:
            return
        self._layers = self._ctx = None
        self._fill_combo()
        self.topo.sync()
        if self._profile is None:
            return
        try:
            profile = self.provider.store.profile(self._profile.id)
        except KeyError:                        # profile deleted from the project
            self._close_profile()
            self._set_hint()
            return
        settled = self._settle(profile)
        if not np.array_equal(profile.xy, self._profile.xy):
            self._profile = profile
            self._set_curve(profile)
        self._sync_layers()
        self._update_info()
        self.canvas.refresh()
        if settled:
            self.readout.setText(settled)

    # -- profiles ----------------------------------------------------------------------------
    def _fill_combo(self) -> None:
        profiles = [] if self.provider is None else self.provider.store.profiles()
        wanted = [(None, "Choose a profile…")] + [(p.id, p.name or p.id) for p in profiles]
        have = [(self.profile_combo.itemData(i), self.profile_combo.itemText(i))
                for i in range(self.profile_combo.count())]
        self.profile_combo.blockSignals(True)
        if wanted != have:
            self.profile_combo.clear()
            for pid, name in wanted:
                self.profile_combo.addItem(name, pid)
        index = self.profile_combo.findData(self.current_profile_id()) if self._profile else 0
        self.profile_combo.setCurrentIndex(max(0, index))
        self.profile_combo.blockSignals(False)

    def _combo_changed(self, index: int) -> None:
        pid = self.profile_combo.itemData(index)
        if pid and pid != self.current_profile_id():
            self.open_profile(pid)

    def current_profile_id(self) -> str | None:
        return None if self._profile is None else self._profile.id

    def current_profile(self):
        return self._profile

    def open_profile(self, profile_id: str) -> bool:
        """Show ``profile_id``: curve in the profile's own direction, CRS of the project
        store, zoomed to the full extent of the data and topography. A profile missing from
        the store shows a message and refreshes the list instead (returns False)."""
        if self.provider is None:
            raise RuntimeError("no project is open")
        try:
            profile = self.provider.store.profile(profile_id)
        except KeyError:
            self._close_profile()
            self._fill_combo()
            self.readout.setText(MISSING_PROFILE)
            return False
        self._profile = profile
        self.empty_hint.hide()
        self.canvas.show()
        self.provider.active_profile_id = profile.id    # wins over profiles on the same line
        settled = self._settle(profile)
        self._layers = self._ctx = None
        self._fill_combo()
        self.topo.sync()
        self.canvas.setCrs(QgsCoordinateReferenceSystem(self.provider.store.crs_authid))
        self._set_curve(profile)
        if self._source is not None and not self.canvas.sources():
            self.canvas.setSources([self._source])
        self._sync_layers()
        self._update_info()
        self.canvas.refresh()
        self.zoom_full()
        self.show_cursor(None)
        self._set_hint()
        self.profile_changed.emit(profile_id)
        if settled:
            self.readout.setText(settled)
        return True

    # -- reference height and the interpretation of a profile without heights ----------------
    def _settle(self, profile) -> str | None:
        """Re-hang the interpretation drawn on ``profile`` while it had no heights, once it
        has real ones (``settle_local_interpretation``); the message to show, or None. Not
        undoable: the undo stack's piece states predate the move, so it is cleared. A store
        that cannot be written gives a message instead (it is tried again on the next
        refresh); the undo stack is cleared then too, as the pieces may have moved."""
        if not profile.metadata.get("local_pieces"):     # the usual case: no store reads
            return None
        name = profile.name or profile.id
        try:
            store = self.provider.store
            version = store.current_version().id if store.has_interpretation() else None
            n = len(store.pieces(version, profile.id)) if version is not None else 0
            if not self.provider.settle_local_interpretation(profile.id):
                return None
            self.interp.undo.clear()
            self._reload_interp_layers()
        except STORE_ERRORS as exc:
            self.interp.undo.clear()
            return SETTLE_FAILED.format(profile=name, error=exc)
        return SETTLED.format(profile=name, n=n) if n else None

    def _reload_interp_layers(self) -> None:
        """The map's interpretation layers read the rebuilt derived tables again."""
        from ..ui.interp_layers import reload_interp_layers
        store = self.provider.store
        if store.has_interpretation():
            reload_interp_layers(store, QgsProject.instance())

    def set_reference_height(self, s: float | None, z: float | None) -> str | None:
        """Set the open profile's reference height (chainage ``s``, height ``z``), or remove
        it with None: one step on the panel's undo stack, the interpretation on the profile
        moving with it. The same value again is no step. Returns the message shown under
        the section when the store could not be written (nothing changed, no step), or
        None."""
        from .topography import reference_height
        profile_id = self.current_profile_id()
        if profile_id is None or self.provider is None:
            return None
        self._reference_error = None
        try:
            stored = reference_height(self.provider.store.profile(profile_id).metadata)
        except STORE_ERRORS as exc:
            return self._reference_failed(exc)
        current = None if stored is None else {"s": stored[0], "z": stored[1]}
        wanted = None if s is None or z is None else {"s": float(s), "z": float(z)}
        if wanted == current:
            return None
        text = "Remove reference height" if wanted is None else "Set reference height"
        self.interp.undo.push_with(self._apply_reference, text, (profile_id, current),
                                   (profile_id, wanted))
        return self._reference_error

    def _apply_reference(self, state, _other) -> bool:
        """Apply one side of a reference-height step and zoom the open profile to its full
        extent. False (the stack drops the step) when the store could not be written; a
        failure after the store changed (reloading the map's layers) keeps the step."""
        profile_id, ref = state
        if self.provider is None:
            return False
        try:
            if ref is None:
                self.provider.set_reference_height(profile_id, None, None)
            else:
                self.provider.set_reference_height(profile_id, ref["s"], ref["z"])
            self._reload_interp_layers()
            if profile_id == self.current_profile_id():     # the data moved: keep them in view
                self._refresh_now()
                self.zoom_full()
        except STORE_ERRORS as exc:
            saved = self._stored_reference(profile_id) == ref
            self._reference_failed(exc, saved)
            return saved
        return True

    def _stored_reference(self, profile_id: str):
        """The profile's stored reference height as a step state; False when unreadable."""
        from .topography import reference_height
        try:
            stored = reference_height(self.provider.store.profile(profile_id).metadata)
        except (*STORE_ERRORS, KeyError):
            return False
        return None if stored is None else {"s": stored[0], "z": stored[1]}

    def _reference_failed(self, exc: BaseException, saved: bool = False) -> str:
        self._reference_error = (NOT_REFRESHED if saved else REFERENCE_FAILED).format(error=exc)
        self.readout.setText(self._reference_error)
        return self._reference_error

    def _set_curve(self, profile) -> None:
        self.canvas.setProfileCurve(QgsLineString([QgsPoint(float(x), float(y))
                                                   for x, y in profile.xy]))

    def _close_profile(self) -> None:
        self.hide_details_popup()
        self._profile = None
        self.canvas.hide()
        self.empty_hint.show()
        if self.provider is not None:
            self.provider.active_profile_id = None
        self._layers = self._topo = self._coverage = self._ctx = None
        self.fit.reset()
        self.canvas.clear()
        self.layer_list.set_layers(self.provider, [])
        self._show_errors([])
        self._update_info()
        self.topo.sync()
        self.show_cursor(None)
        self.profile_changed.emit(None)

    def _current_layers(self) -> list:
        if self._layers is None:
            if self.provider is None or self._profile is None:
                return []
            self._layers = self.provider.layers(self._profile.id)
            self._topo = self.provider.topography(self._profile.id)
            self._coverage = self.provider.coverage(self._profile.id)
        return self._layers

    def _sync_layers(self) -> None:
        layers = self._current_layers()
        self.layer_list.set_layers(self.provider, layers)
        self._show_errors([f"{layer_name(la.dataset)}: {la.error}"
                           for la in layers if la.error is not None])

    def info_text(self) -> str:
        return self.info.text()

    def _update_info(self) -> None:
        """Say which electrodes the section shows and that a local section is in depth."""
        parts = []
        if self.provider is not None and self._profile is not None:
            pid = self._profile.id
            found = self.provider.electrodes(pid)
            if found is not None and found.kind in KIND_TEXT:
                spacing = self._profile.metadata.get("electrode_spacing")
                parts.append(kind_text(found.kind, self.provider.station_method(pid),
                                       "" if spacing is None else fmt_trim(float(spacing))))
            if note := self.provider.placement_note(pid):
                parts.append(note)
            if self.provider.is_local(pid):
                parts.append(LOCAL_INFO)
        text = " · ".join(parts)
        self.info.setText(text[:1].upper() + text[1:])     # a line under the section
        self.info.setVisible(bool(parts))

    def _show_errors(self, lines: list[str]) -> None:
        self.errors.setText("\n".join(lines))
        self.errors.setVisible(bool(lines))

    # -- view --------------------------------------------------------------------------------
    def _fit_extent(self):
        """Data, topography, station heights and context z (view_extent.data_extent)."""
        return None if self._profile is None else data_extent(self)

    def _fit_headroom(self) -> float:
        """Pixels the band and label rows need above the data (view_extent.headroom_px)."""
        return 0.0 if self._profile is None else headroom_px(self)

    def zoom_full(self) -> None:
        """Fit the data and topography at the current vertical exaggeration. The view keeps
        being re-fitted (after generation, resize, exaggeration changes) until the user
        presses, scrolls or types in the canvas."""
        self.fit.zoom_full()

    def _ve_changed(self, value: float) -> None:
        self.fit.ve_changed(value)

    def _jobs_changed(self, count: int) -> None:
        self.fit.jobs_changed(count)

    def is_busy(self) -> bool:
        """True while the canvas is generating the section."""
        return self.fit.is_busy()

    def eventFilter(self, obj, event):
        if "canvas" not in self.__dict__:
            return False                        # being taken apart (plugin reload): ignore
        etype = event.type()
        if obj is self.canvas.viewport():
            if etype == QEvent.Type.Leave:
                self.cursor_left.emit()
            elif etype in (QEvent.Type.MouseButtonPress, QEvent.Type.Wheel):
                self.fit.user_navigated()       # the user navigates: keep their view
            if etype == QEvent.Type.MouseButtonPress and \
                    event.button() == Qt.MouseButton.LeftButton:
                self._click_pos = event.position()
            elif etype == QEvent.Type.MouseButtonPress and \
                    event.button() == Qt.MouseButton.RightButton and \
                    self.canvas.tool() is self._pan_tool and self._right_click(event):
                return True
            elif etype == QEvent.Type.MouseButtonRelease and self._click_pos is not None:
                moved = event.position() - self._click_pos
                self._click_pos = None
                if abs(moved.x()) + abs(moved.y()) <= 4 and \
                        self.canvas.tool() is self._pan_tool:
                    self.show_details(event.position(), event.globalPosition())
        elif obj is self.canvas:
            if etype == QEvent.Type.KeyPress:
                self.fit.user_navigated()
            elif etype == QEvent.Type.Resize and self._profile is not None:
                self.fit.schedule_refit()
        return super().eventFilter(obj, event)

    def details_at(self, pos) -> list[str]:
        """Borehole and interpretation details under canvas position ``pos``."""
        if self._profile is None or self.provider is None:
            return []
        pp = self.canvas.canvasPointToPlotPoint(pos)
        if pp.isEmpty():
            return []
        from .dock_context import click_details
        return click_details(self, float(pp.distance()), float(pp.elevation()))

    def show_details(self, pos, global_pos) -> None:
        if self._profile is None or self.provider is None:
            return
        pp = self.canvas.canvasPointToPlotPoint(pos)
        if pp.isEmpty():
            return
        self.handle_click(float(pp.distance()), float(pp.elevation()), global_pos.toPoint())

    def _right_click(self, event) -> bool:
        if self._profile is None or self.provider is None:
            return False
        pp = self.canvas.canvasPointToPlotPoint(event.position())
        if pp.isEmpty():
            return False
        return self.handle_right_click(float(pp.distance()), float(pp.elevation()),
                                       event.globalPosition().toPoint())

    def handle_right_click(self, s: float, z: float, global_point) -> bool:
        """A Pan-mode right-click at (s, z): on a borehole column, a menu to hide it in this
        profile's section (and its plates). True when the menu was shown."""
        from qgis.PyQt.QtGui import QCursor

        from ..core.context import borehole_key
        from .dock_context import borehole_point
        point = borehole_point(self, s, z)
        if point is None:
            return self._show_hidden_menu(global_point)
        key = borehole_key(point)
        menu = QMenu()                          # parentless (round-1 lifetime rule)
        menu.setToolTipsVisible(True)
        action = menu.addAction(HIDE_IN_SECTION)
        if key is None:
            action.setEnabled(False)
            action.setToolTip(NO_ID_TIP)
        else:
            action.setToolTip("Leave this borehole out of this profile's section and plates; "
                              "the borehole viewer still shows it")
            action.triggered.connect(partial(self._hide_borehole, key, point.label))
        menu.exec(global_point if global_point is not None else QCursor.pos())
        return True

    def _show_hidden_menu(self, global_point) -> bool:
        """Off the columns: when boreholes are hidden in this profile, offer them back
        (the only way back when every borehole is hidden). True when the menu was shown."""
        from qgis.PyQt.QtGui import QCursor
        profile_id = self.current_profile_id()
        hidden = self.provider.hidden_keys(profile_id) if profile_id else set()
        if not hidden:
            return False
        menu = QMenu()
        action = menu.addAction(show_hidden_text(len(hidden)))
        action.triggered.connect(partial(self._set_hidden, sorted(hidden), False,
                                         f"{len(hidden)} borehole(s) shown again"))
        menu.exec(global_point if global_point is not None else QCursor.pos())
        return True

    def _hide_borehole(self, key, label: str, *_args) -> None:
        self._set_hidden([key], True, f"{label} hidden in this section – right-click the "
                                      "section to show it again")

    def _set_hidden(self, keys, hidden: bool, message: str, *_args) -> None:
        """Hide or show boreholes in this profile, on the panel's undo stack."""
        profile_id = self.current_profile_id()
        if profile_id is None or self.provider is None:
            return
        text = "Hide borehole" if hidden else "Show boreholes"
        self.interp.undo.push_with(self._apply_hidden, text,
                                   (profile_id, list(keys), not hidden),
                                   (profile_id, list(keys), hidden))
        self.readout.setText(message)

    def _apply_hidden(self, state, _other) -> None:
        profile_id, keys, hidden = state
        if self.provider is not None:
            self.provider.set_boreholes_hidden(profile_id, keys, hidden)

    def tool_hint_text(self) -> str:
        return self.readout.text()

    def handle_click(self, s: float, z: float, global_point) -> None:
        """A Pan-mode click at (s, z): on a borehole column alone it opens the borehole
        viewer; together with an interpretation piece the details show as before, with an
        "Open in borehole viewer" link; anywhere else the details tooltip as before."""
        from .dock_context import borehole_hit, click_details
        self.hide_details_popup()
        hit = borehole_hit(self, s, z)
        lines = click_details(self, s, z)
        piece = any(line.startswith("Interpretation") for line in lines)
        if hit is not None and not piece:
            self.borehole_clicked.emit(*hit)
            return
        if hit is not None:
            self._show_popup(lines, hit, global_point)
            return
        if lines and global_point is not None:
            QToolTip.showText(global_point, "\n".join(lines), self.canvas)

    def hide_details_popup(self) -> None:
        if self.details_popup is not None:
            self.details_popup.hide()

    def _show_popup(self, lines: list[str], hit, global_point) -> None:
        import html
        from qgis.PyQt.QtWidgets import QLabel
        if self.details_popup is None:
            # parented: deleted with the dock, still its own small window
            self.details_popup = QLabel(self, Qt.WindowType.ToolTip)
            self.details_popup.setTextFormat(Qt.TextFormat.RichText)
            self.details_popup.setMargin(4)
        popup = self.details_popup
        try:
            popup.linkActivated.disconnect()
        except (TypeError, RuntimeError):
            pass

        def opened(_link, hit=hit):
            popup.hide()
            self.borehole_clicked.emit(*hit)

        popup.linkActivated.connect(opened)
        body = "<br>".join(html.escape(line).replace("  ", "&nbsp;&nbsp;") for line in lines)
        popup.setText(f"{body}<br><a href='open'>Open in borehole viewer</a>")
        popup.adjustSize()
        if global_point is not None:
            popup.move(global_point)
        popup.show()

    # -- cursor ------------------------------------------------------------------------------
    def _hovered(self, _canvas_point, plot_point) -> None:
        # the arguments are const references: copy the values now (ADR 0001)
        if plot_point.isEmpty() or self._profile is None:
            self.cursor_left.emit()
            return
        s, z = float(plot_point.distance()), float(plot_point.elevation())
        self.cursor_moved.emit(s, z)            # canvas distance == forward chainage (M1)
        self._show_readout(s, z)

    def _show_readout(self, s: float, z: float | None = None) -> None:
        profile = self._profile
        inside = 0.0 <= s <= profile.chainage.length
        xy = tuple(float(v) for v in profile.chainage.to_xy(s)) if inside else None
        layers = self._current_layers()
        depth, hits, extra = None, [], []
        if z is not None:
            topo = self._topo
            if topo is not None and len(topo[0]) > 1 and topo[0][0] <= s <= topo[0][-1]:
                depth = float(np.interp(s, *topo)) - z
            hits = identify_layers(layers, s, z)
            extra = context_lines(self, s, z)
        cover = self._coverage
        beyond = cover is not None and not cover[0] <= s <= cover[1]
        self.readout.setText(format_readout(s, z, depth, xy, hits, beyond, extra))

    def show_cursor(self, s: float | None) -> None:
        """Vertical guide at forward chainage ``s``; ``None`` hides it."""
        self._cursor_s = None if s is None or self._profile is None else float(s)
        self._update_guide()
        if self._cursor_s is not None:
            self._show_readout(self._cursor_s)

    def cursor_chainage(self) -> float | None:
        return self._cursor_s

    def _update_guide(self, *_) -> None:
        s = self._cursor_s
        d = self.canvas.visibleDistanceRange()
        if s is None or not d.lower() <= s <= d.upper():
            self.guide_line.hide()
            return
        area = self.canvas.plotArea()
        e = self.canvas.visibleElevationRange()
        # a point outside the visible range maps to (0, 0): use the middle elevation
        x = self.canvas.plotPointToCanvasPoint(
            QgsProfilePoint(s, (e.lower() + e.upper()) / 2)).x()
        self.guide_line.setLine(QLineF(x, area.top(), x, area.bottom()))
        self.guide_line.show()

    def profile_menu(self):
        """Right-click menu of the profile list: rename or delete the open profile. The menu
        has no parent and its actions call bound methods (no lambda holding the dock: such a
        reference cycle lets Python free the dock while Qt still uses it)."""
        from ..ui.profile_actions import DELETE_TEXT, RENAME_TEXT
        menu = QMenu()
        enabled = self.current_profile_id() is not None
        for text, slot in ((RENAME_TEXT, self._rename_open_profile),
                           (DELETE_TEXT, self._delete_open_profile)):
            action = menu.addAction(text)
            action.setEnabled(enabled)
            action.triggered.connect(slot)
        return menu

    def set_pick_action(self, action) -> None:
        """The plugin's Pick Profile on Map action, on the button next to the profile list."""
        self.pick_button.setDefaultAction(action)          # its tooltip follows the action

    def _hint_link(self, _href: str) -> None:
        action = self.pick_button.defaultAction()
        if action is not None and action.isEnabled() and not action.isChecked():
            action.trigger()

    def _show_profile_menu(self, pos) -> None:
        menu = self.profile_menu()
        menu.exec(self.profile_combo.mapToGlobal(pos))
        menu.deleteLater()

    def _rename_open_profile(self, *_args) -> None:
        if self.current_profile_id():
            self.rename_requested.emit(self.current_profile_id())

    def _delete_open_profile(self, *_args) -> None:
        if self.current_profile_id():
            self.delete_requested.emit(self.current_profile_id())

    def set_tool_hint(self, text: str | None) -> None:
        """The active tool's one-line hint (None: back to the panel's own hint)."""
        self._tool_hint = text
        self._set_hint()

    def _set_hint(self) -> None:
        if self.provider is None:
            text = HINT_NO_PROJECT
        elif self._profile is None:
            text = HINT_NO_PROFILE
        else:
            text = getattr(self, "_tool_hint", None) or HINT_HOVER
        self.readout.setText(text)
        if self._profile is None:
            self.empty_hint.setText(HINT_NO_PROFILE_LINK if text == HINT_NO_PROFILE else text)
