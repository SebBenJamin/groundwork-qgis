"""Section panel: a native elevation-profile canvas fed by the workbench profile source,
with a profile chooser, layer list, vertical exaggeration and a cursor readout.

Coordinates: ``open_profile`` always sets the canvas curve in the profile's own direction,
so canvas distance == forward profile chainage (what ``cursor_moved``, ``show_cursor`` and
``SectionDataProvider.identify`` use). Keep it that way, or convert (length - s) here.
"""
from __future__ import annotations

import os
from functools import partial

import numpy as np
from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsLineString, QgsPoint,
                       QgsProfilePoint, QgsProject, QgsSettings)
from qgis.gui import QgsElevationProfileCanvas, QgsPlotToolPan
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QLineF, QRectF, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor, QKeySequence, QPen, QShortcut
from qgis.PyQt.QtWidgets import (QComboBox, QDockWidget, QDoubleSpinBox, QGraphicsEllipseItem,
                                 QGraphicsLineItem,
                                 QToolTip,
                                 QHBoxLayout, QLabel, QMenu, QSizePolicy, QSplitter,
                                 QToolButton,
                                 QVBoxLayout,
                                 QWidget)

from ..core.layout import KIND_TEXT, kind_text
from ..core.numbers import fmt_trim
from ..ids import LEGACY_ID
from .data import identify_layers
from .dock_context import context_lines
from .layer_list import LayerList
from .profile_source import SOURCE_ID
from .readout import format_readout
from .topo_switch import TopoSwitch
from .view_extent import data_extent, headroom_px
from .view_fit import ViewFitter, keep_auto_text_whole

OBJECT_NAME = "GeophysicsWorkbenchSectionDock"
AUTO_VE = 0.0                   # the VE box's "Auto": the exaggeration that fills the panel
SPLITTER_KEY = f"{LEGACY_ID}/section/splitter"
IMAGE_DIR_KEY = f"{LEGACY_ID}/section/image_dir"   # where Save Section Image… saved last
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
#: the profile menu's 3D view entries
LOOK_3D_TEXT = "Look at Profile in 3D"
CUT_3D_TEXT = "Cut 3D View Along Profile"
UNCUT_3D_TEXT = "Remove 3D Cut"
SHOW_3D_TEXT = "Show in 3D…"
VIEW3D_BUTTON_TEXT = "3D"
VIEW3D_BUTTON_TIP = "The open profile in QGIS's 3D view: look at it, cut the view along it"
PREVIOUS_TIP = "Previous profile (Page Up)"
NEXT_TIP = "Next profile (Page Down)"
FIRST_TIP = "This is the first profile"
LAST_TIP = "This is the last profile"
NO_PROFILES_TIP = "No profiles yet: make one with New Profile… or Add Data…"
IMAGE_TIP = "Copy the section as a picture, or save it as a PNG file"
IMAGE_OFF_TIP = "Open a profile first; then its section can be copied or saved as a picture"
COPY_IMAGE_TEXT = "Copy Section Image"
SAVE_IMAGE_TEXT = "Save Section Image…"
ZOOM_MAP_TEXT = "Zoom Map to Profile"
READING = "Reading {name} ({done} of {total})…"
READ_CANCELLED = "Reading was cancelled. Open the profile again to read it."
REFRESH_WEB_TEXT = "Refresh Web Layers"
REFRESH_WEB_TIP = ("Fetch the strips from web layers (e.g. a survey's live geology) again: "
                   "they are remembered per profile")
ZOOM_MAP_TIP = "Zoom the map to the open profile's line"
ZOOM_MAP_OFF_TIP = "Open a profile first; then this zooms the map to its line"
HIDE_IN_SECTION = "Hide in Section"
SHOW_IN_SECTION = "Show in Section"
APPLIED_ALL = ("Style applied to {n} other {what}(s) of the project. Ctrl+Z in the "
               "panel takes it back.")
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
    _reader = None                              # a ModelReader: models read in the background
    _wanted = None                              # (profile id, name, token) read before it opens
    _refresh_token = None                       # the read a refresh waits for
    cursor_moved = pyqtSignal(float, float)     # forward chainage, elevation
    cursor_left = pyqtSignal()                  # the mouse left the section
    profile_changed = pyqtSignal(object)        # open profile id, or None when closed
    borehole_clicked = pyqtSignal(int, str)     # (borehole entry, label): open the viewer
    rename_requested = pyqtSignal(str)          # profile id: "Profile Properties…"
    delete_requested = pyqtSignal(str)          # profile id: "Delete Profile…"
    #: (profile id, "look" | "cut" | "uncut" | "dialog"): the 3D button's and profile
    #: menu's entries
    view3d_requested = pyqtSignal(str, str)
    zoom_map_requested = pyqtSignal(str)        # profile id: "Zoom Map to Profile"

    def __init__(self, parent=None):
        super().__init__("Geophysics section", parent)
        self.setObjectName(OBJECT_NAME)
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea
                             | Qt.DockWidgetArea.TopDockWidgetArea)
        self.provider = None
        self._source = None
        self._profile = None
        self._typed_ve: dict[str, float] = {}   # profile id -> exaggeration typed for it
        self._layers = None                     # cached provider.layers() of the open profile
        self._ctx = None                        # cached (context items, station line), dock_context
        self._topo = None
        self._coverage = None                   # (min, max) station chainage, with _topo
        self._cursor_s = None
        self._cursor_z = None                   # elevation of a cursor from the 3D view
        self._click_pos = None
        self.details_popup = None               # details with an "Open in borehole viewer" link
        #: set by the plugin: () -> whether a 3D view is cut along a profile, or None in a
        #: QGIS without 3D views; unset or None leaves the 3D entries out of the profile menu
        self.view3d_cut_active = None

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
        keep_auto_text_whole(self.ve_spin)
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
        # where the 3D view's mouse points: a small ring on the guide, in its pen
        self.cursor_marker = QGraphicsEllipseItem(-5.0, -5.0, 10.0, 10.0)
        ring = QPen(pen)
        ring.setStyle(Qt.PenStyle.SolidLine)
        self.cursor_marker.setPen(ring)
        self.cursor_marker.setZValue(1001)
        self.cursor_marker.hide()
        self.canvas.scene().addItem(self.cursor_marker)
        self._pin_scene_rect()

        self.layer_list = LayerList()
        self.layer_list.apply_all_requested.connect(self.apply_style_to_all)
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
        # step through the profiles in list order: arrows beside the list, Page Up / Down
        self.previous_button, self.next_button = QToolButton(), QToolButton()
        self.previous_button.setArrowType(Qt.ArrowType.LeftArrow)
        self.next_button.setArrowType(Qt.ArrowType.RightArrow)
        for button, step in ((self.previous_button, -1), (self.next_button, 1)):
            button.setAutoRaise(True)
            button.clicked.connect(self._step_previous if step < 0 else self._step_next)
        self.previous_shortcut = QShortcut(QKeySequence("PgUp"), self)
        self.next_shortcut = QShortcut(QKeySequence("PgDown"), self)
        for shortcut, slot in ((self.previous_shortcut, self._step_previous),
                               (self.next_shortcut, self._step_next)):
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            shortcut.activated.connect(slot)
        top.addWidget(self.previous_button)
        top.addWidget(self.profile_combo)
        top.addWidget(self.next_button)
        # Pick on Map next to the list (the plugin gives it its map tool action)
        self.pick_button = QToolButton()
        self.pick_button.setAutoRaise(True)
        top.addWidget(self.pick_button)
        # the map follows the panel: zoom it to the open profile's line
        self.zoom_map_button = QToolButton()
        self.zoom_map_button.setAutoRaise(True)
        self.zoom_map_button.setIcon(QgsApplication.getThemeIcon("/mActionZoomToSelected.svg"))
        self.zoom_map_button.setText(ZOOM_MAP_TEXT)
        self.zoom_map_button.clicked.connect(self._zoom_map)
        self.profile_changed.connect(self._sync_zoom_map)
        self.profile_changed.connect(self._sync_steps)
        self._sync_zoom_map()
        self._sync_steps()
        top.addWidget(self.zoom_map_button)
        # the open profile in QGIS's 3D view: a drop-down, filled when it opens
        self.view3d_button = QToolButton()
        self.view3d_button.setText(VIEW3D_BUTTON_TEXT)
        self.view3d_button.setToolTip(VIEW3D_BUTTON_TIP)
        self.view3d_button.setAutoRaise(True)
        self.view3d_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.view3d_menu = QMenu(self.view3d_button)
        self.view3d_menu.aboutToShow.connect(self._fill_view3d_menu)
        self.view3d_button.setMenu(self.view3d_menu)
        self.view3d_button.hide()               # shown by the plugin where QGIS has 3D views
        top.addWidget(self.view3d_button)
        top.addWidget(self.topo.label)
        top.addWidget(self.topo_combo)
        top.addWidget(self.topo.reference_button)
        top.addStretch(1)
        top.addWidget(QLabel("Vertical exaggeration"))
        top.addWidget(self.ve_spin)
        top.addWidget(zoom_button)
        # the section as a picture: for an e-mail or a report, without making a plate
        self.image_button = QToolButton()
        self.image_button.setAutoRaise(True)
        self.image_button.setIcon(QgsApplication.getThemeIcon("/mActionSaveMapAsImage.svg"))
        self.image_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        image_menu = QMenu(self.image_button)
        image_menu.addAction(COPY_IMAGE_TEXT).triggered.connect(self.copy_image)
        image_menu.addAction(SAVE_IMAGE_TEXT).triggered.connect(self._save_image_clicked)
        self.image_button.setMenu(image_menu)
        self.profile_changed.connect(self._sync_image)
        self._sync_image()
        top.addWidget(self.image_button)
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
        if state is not None and splitter.restoreState(state):
            self.layer_list.sized_by_user = True
        splitter.splitterMoved.connect(self._splitter_moved)
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
        self._typed_ve.clear()                  # another project's profiles
        self._source = None
        self.set_reader(None)
        self._close_profile()
        if provider is not None:
            self._source = source if source is not None else _registered_source_for(provider)
            provider.on_change.append(self._on_provider_changed)
            if self._source is not None:
                self.canvas.setSources([self._source])
        self._fill_combo()
        self._set_hint()

    def _splitter_moved(self, *_args) -> None:
        """The user dragged the handle beside the Layers list: keep that width (also for
        the next session), and stop the list widening by itself."""
        self.layer_list.sized_by_user = True
        QgsSettings().setValue(SPLITTER_KEY, self.splitter.saveState())

    def set_reader(self, reader) -> None:
        """Read models in the background with ``reader`` (a ``ModelReader`` of this panel's
        provider); None: read them on the main thread, as tests and plates do."""
        old = getattr(self, "_reader", None)
        if old is not None:
            try:
                old.progress.disconnect(self._reading_progress)
            except (TypeError, RuntimeError):
                pass
        self._reader = reader
        self._wanted = None                     # the profile being read before it opens
        if reader is not None:
            reader.progress.connect(self._reading_progress)

    @property
    def reader(self):
        return getattr(self, "_reader", None)

    @reader.setter
    def reader(self, value) -> None:
        self.set_reader(value)

    def _reading_progress(self, done: int, total: int, _name: str) -> None:
        if sip.isdeleted(self):                 # the panel went while a task read
            return
        if self._wanted is not None:
            self.readout.setText(READING.format(name=self._wanted[1], done=done, total=total))

    def _read_first(self, profile, then) -> int | None:
        """Read ``profile``'s models in the background and call ``then(ok)`` on the main
        thread (perhaps at once); the number of reads, or None when there is nothing to read
        (or no reader)."""
        if self.reader is None:
            return None
        total = len(self.provider.unread([profile.id]))
        if not self.reader.request([profile.id], then):
            return None
        return total

    def _opened_after_read(self, profile_id: str, token, after, ok: bool) -> None:
        if sip.isdeleted(self):                 # the panel went while a task read
            return
        if self._wanted is None or self._wanted[2] is not token:
            return                              # another profile was chosen meanwhile
        self._wanted = None
        if ok and self.provider is not None:
            self.open_profile(profile_id, after)
            return
        self.readout.setText(READ_CANCELLED)
        self._fill_combo()                      # the list shows what is open again

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
        if self._profile is None or self._wanted is not None:
            return                              # nothing open, or another one opens soon
        try:
            profile = self.provider.store.profile(self._profile.id)
        except KeyError:                        # profile deleted from the project
            self._close_profile()
            self._set_hint()
            return
        token = self._refresh_token = object()
        if self._read_first(profile, partial(self._refreshed_after_read, token)) is not None:
            return                              # drawn again when the new data are read
        self._refresh_token = None
        settled = self._settle(profile)
        if not np.array_equal(profile.xy, self._profile.xy):
            self._profile = profile
            self._set_curve(profile)
        self._sync_layers()
        self._update_info()
        self.canvas.refresh()
        if settled:
            self.readout.setText(settled)

    def _refreshed_after_read(self, token, ok: bool) -> None:
        if sip.isdeleted(self) or token is not self._refresh_token:
            return                              # the panel went, or a newer read is on
        self._refresh_token = None
        if ok:
            self._refresh_now()
        elif self._wanted is None:
            self.readout.setText(READ_CANCELLED)

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
        shown = self._wanted[0] if self._wanted is not None else (
            self.current_profile_id() if self._profile else None)
        index = self.profile_combo.findData(shown) if shown is not None else 0
        self.profile_combo.setCurrentIndex(max(0, index))
        self.profile_combo.blockSignals(False)
        self._sync_steps()

    def _step_index(self, step: int) -> int | None:
        """The list index ``step`` profiles away from the open one (nothing open: Next is
        the first profile, Previous the last), or None past either end."""
        last = self.profile_combo.count() - 1       # index 0 is "Choose a profile…"
        if last < 1:
            return None
        here = self.profile_combo.findData(self.current_profile_id()) if self._profile else -1
        if here < 1:
            return 1 if step > 0 else last
        there = here + step
        return there if 1 <= there <= last else None

    def _step(self, step: int) -> None:
        index = self._step_index(step)
        if index is not None:
            self.open_profile(self.profile_combo.itemData(index))

    def _step_previous(self, *_args) -> None:
        self._step(-1)

    def _step_next(self, *_args) -> None:
        self._step(1)

    def _sync_steps(self, *_args) -> None:
        for button, step, tip, end in ((self.previous_button, -1, PREVIOUS_TIP, FIRST_TIP),
                                       (self.next_button, 1, NEXT_TIP, LAST_TIP)):
            on = self._step_index(step) is not None
            button.setEnabled(on)
            button.setToolTip(tip if on else end if self.profile_combo.count() > 1
                              else NO_PROFILES_TIP)

    def _combo_changed(self, index: int) -> None:
        pid = self.profile_combo.itemData(index)
        if pid and pid != self.current_profile_id():
            self.open_profile(pid)

    def current_profile_id(self) -> str | None:
        return None if self._profile is None else self._profile.id

    def current_profile(self):
        return self._profile

    def open_profile(self, profile_id: str, after=None) -> bool:
        """Show ``profile_id``: curve in the profile's own direction, CRS of the project
        store, zoomed to the full extent of the data and topography. A profile missing from
        the store shows a message and refreshes the list instead (returns False). Models
        not read yet are read in the background first; ``after()`` is called once the
        profile is open (at once when nothing had to be read), never when another profile
        was chosen meanwhile or the reading was cancelled."""
        if self.provider is None:
            raise RuntimeError("no project is open")
        try:
            profile = self.provider.store.profile(profile_id)
        except KeyError:
            self._close_profile()
            self._fill_combo()
            self.readout.setText(MISSING_PROFILE)
            return False
        token = object()
        name = profile.name or profile.id
        self._wanted = (profile.id, name, token)
        total = self._read_first(profile, partial(self._opened_after_read, profile.id, token,
                                                  after))
        if total is not None:
            if self._wanted is not None and self._wanted[2] is token:   # still reading
                self.readout.setText(READING.format(name=name, done=0, total=total))
                self.profile_combo.blockSignals(True)
                self.profile_combo.setCurrentIndex(
                    max(0, self.profile_combo.findData(profile.id)))
                self.profile_combo.blockSignals(False)
            return True
        self._wanted = None
        if self._profile is not None and self._profile.id != profile.id:
            self._take_ve(profile.id)
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
        if after is not None:
            after()
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
        from .layer_list import error_line
        self._show_errors([error_line(la) for la in layers if la.error is not None])

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
        if self._profile is not None:
            if value <= self.ve_spin.minimum():
                self._typed_ve.pop(self._profile.id, None)
            else:
                self._typed_ve[self._profile.id] = value
        self.fit.ve_changed(value)

    def _take_ve(self, profile_id: str) -> None:
        """Another profile opens at the exaggeration typed for it in this session, else at
        Auto: one typed for a long, shallow line would squeeze a short, deep one into a
        sliver of the panel (the view fits the whole section at the exaggeration). Silent;
        the zoom that follows fits the view."""
        self.ve_spin.blockSignals(True)
        self.ve_spin.setValue(self._typed_ve.get(profile_id, AUTO_VE))
        self.ve_spin.blockSignals(False)

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
            if etype == QEvent.Type.Resize:
                self._pin_scene_rect(event.size())
            elif etype == QEvent.Type.Leave:
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

    def _pin_scene_rect(self, size=None) -> None:
        """Keep the view's scene rect at the viewport, so the view never scrolls and viewport
        pixels (mouse positions) stay scene pixels (overlay items, canvasPointToPlotPoint).
        Unpinned, the scene grows to every item, also hidden ones and those reaching outside
        the plot, and the view scrolls by a few pixels or more: drawing lands beside the
        cursor. Items outside are clipped."""
        size = self.canvas.viewport().size() if size is None else size
        self.canvas.setSceneRect(QRectF(0.0, 0.0, size.width(), size.height()))
        self.canvas.horizontalScrollBar().setValue(0)
        self.canvas.verticalScrollBar().setValue(0)

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

    def apply_style_to_all(self, dataset_id: str) -> None:
        """Give every other model of the same method (type, quantity and unit), on every
        profile, ``dataset_id``'s style; whether each is shown stays. One step on the
        panel's undo stack."""
        from ..core.dataset_types import type_label
        from .style_store import applied, same_method
        if self.provider is None:
            return
        targets = same_method(self.provider.store, dataset_id)
        if not targets:
            return
        source = self.provider.style(dataset_id)
        before = {d.id: self.provider.style(d.id) for d in targets}
        after = {i: applied(source, s) for i, s in before.items()}
        self.interp.undo.push_with(self._apply_styles, "Apply style to all sections",
                                   before, after)
        self.readout.setText(APPLIED_ALL.format(n=len(targets),
                                                what=type_label(targets[0].kind)))

    def _apply_styles(self, styles, _other) -> None:
        if self.provider is not None:
            self.provider.set_styles(styles)

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

    def show_cursor(self, s: float | None, z: float | None = None) -> None:
        """Vertical guide at forward chainage ``s``, with a marker at elevation ``z`` when
        given (the 3D view's mouse); ``None`` hides it."""
        self._cursor_s = None if s is None or self._profile is None else float(s)
        self._cursor_z = None if self._cursor_s is None or z is None else float(z)
        self._update_guide()
        if self._cursor_s is not None:
            self._show_readout(self._cursor_s, self._cursor_z)

    def cursor_chainage(self) -> float | None:
        return self._cursor_s

    def _update_guide(self, *_) -> None:
        s = self._cursor_s
        d = self.canvas.visibleDistanceRange()
        if s is None or not d.lower() <= s <= d.upper():
            self.guide_line.hide()
            self.cursor_marker.hide()
            return
        area = self.canvas.plotArea()
        e = self.canvas.visibleElevationRange()
        # a point outside the visible range maps to (0, 0): use the middle elevation
        x = self.canvas.plotPointToCanvasPoint(
            QgsProfilePoint(s, (e.lower() + e.upper()) / 2)).x()
        self.guide_line.setLine(QLineF(x, area.top(), x, area.bottom()))
        self.guide_line.show()
        z = self._cursor_z
        if z is None or not e.lower() <= z <= e.upper():
            self.cursor_marker.hide()
            return
        at = self.canvas.plotPointToCanvasPoint(QgsProfilePoint(s, z))
        self.cursor_marker.setPos(at.x(), at.y())
        self.cursor_marker.show()

    def profile_menu(self):
        """Right-click menu of the profile list: rename or delete the open profile. The menu
        has no parent and its actions call bound methods (no lambda holding the dock: such a
        reference cycle lets Python free the dock while Qt still uses it)."""
        from ..ui.profile_actions import DELETE_TEXT, RENAME_TEXT
        menu = QMenu()
        enabled = self.current_profile_id() is not None
        for text, slot in ((RENAME_TEXT, self._rename_open_profile),
                           (DELETE_TEXT, self._delete_open_profile),
                           (None, None),
                           (ZOOM_MAP_TEXT, self._zoom_map)):
            if text is None:
                menu.addSeparator()
                continue
            action = menu.addAction(text)
            action.setEnabled(enabled)
            action.triggered.connect(slot)
        if self._web_context():
            action = menu.addAction(REFRESH_WEB_TEXT)
            action.setToolTip(REFRESH_WEB_TIP)
            menu.setToolTipsVisible(True)
            action.triggered.connect(self._refresh_web)
        cut = self._cut_state()
        if cut is not None:
            menu.addSeparator()
            self._add_3d_entries(menu, cut)
        return menu

    def _web_context(self) -> bool:
        provider = self.provider
        if provider is None or provider.refresh_web_layers is None:
            return False
        try:
            return provider.has_web_layers is None or bool(provider.has_web_layers())
        except Exception:                       # settings being rewritten: offer nothing
            return False

    def _refresh_web(self) -> None:
        if self.provider is not None and self.provider.refresh_web_layers is not None:
            self.provider.refresh_web_layers()

    def _cut_state(self) -> bool | None:
        """Whether a 3D view is cut along a profile; None without 3D views."""
        try:
            return None if self.view3d_cut_active is None else self.view3d_cut_active()
        except Exception:                       # a 3D view going away: offer the cut
            return False

    def _add_3d_entries(self, menu, cut: bool) -> None:
        """Look at the open profile in 3D, and cut the 3D view along it or remove the cut."""
        enabled = self.current_profile_id() is not None
        entries = [(LOOK_3D_TEXT, self._look_3d, enabled)]
        entries.append((UNCUT_3D_TEXT, self._uncut_3d, True) if cut
                       else (CUT_3D_TEXT, self._cut_3d, enabled))
        for text, slot, on in entries:
            action = menu.addAction(text)
            action.setEnabled(on)
            action.triggered.connect(slot)

    def _fill_view3d_menu(self) -> None:
        """The 3D button's drop-down, as things are when it opens: the open profile's 3D
        entries and Show in 3D…."""
        menu = self.view3d_menu
        menu.clear()
        self._add_3d_entries(menu, bool(self._cut_state()))
        menu.addSeparator()
        action = menu.addAction(SHOW_3D_TEXT)
        action.setEnabled(self.provider is not None)
        action.triggered.connect(self._show_3d_dialog)

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

    def _zoom_map(self, *_args) -> None:
        if self.current_profile_id():
            self.zoom_map_requested.emit(self.current_profile_id())

    def _sync_image(self, *_args) -> None:
        on = self.current_profile_id() is not None
        self.image_button.setEnabled(on)
        self.image_button.setToolTip(IMAGE_TIP if on else IMAGE_OFF_TIP)

    def section_image(self):
        """The section as shown (axes, models, context, interpretation), without the
        mouse's guide line."""
        shown = [item for item in (self.guide_line, self.cursor_marker) if item.isVisible()]
        for item in shown:
            item.hide()
        try:
            return self.canvas.grab()
        finally:
            for item in shown:
                item.show()

    def copy_image(self, *_args) -> None:
        if self._profile is None:
            return
        from qgis.PyQt.QtWidgets import QApplication
        QApplication.clipboard().setPixmap(self.section_image())
        self.readout.setText(f"{self._profile.name}: section image copied to the clipboard")

    def _save_image_clicked(self, *_args) -> None:
        if self._profile is None:
            return
        from qgis.PyQt.QtWidgets import QFileDialog
        folder = QgsSettings().value(IMAGE_DIR_KEY, "") or QgsProject.instance().homePath()
        name = "".join(c if c.isalnum() or c in " -_." else "_" for c in self._profile.name)
        path, _ = QFileDialog.getSaveFileName(self, SAVE_IMAGE_TEXT,
                                              os.path.join(folder, f"{name}.png"),
                                              "PNG image (*.png)")
        if path:
            QgsSettings().setValue(IMAGE_DIR_KEY, os.path.dirname(path))
            self.save_image(path)

    def save_image(self, path: str) -> None:
        if self._profile is None:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        if self.section_image().save(path, "PNG"):
            self.readout.setText(f"{self._profile.name}: section image saved as {path}")
        else:
            self.readout.setText(f"Could not write {path}. Check that the folder exists and "
                                 f"you may write to it.")

    def _sync_zoom_map(self, *_args) -> None:
        on = self.current_profile_id() is not None
        self.zoom_map_button.setEnabled(on)
        self.zoom_map_button.setToolTip(ZOOM_MAP_TIP if on else ZOOM_MAP_OFF_TIP)

    def _look_3d(self, *_args) -> None:
        if self.current_profile_id():
            self.view3d_requested.emit(self.current_profile_id(), "look")

    def _cut_3d(self, *_args) -> None:
        if self.current_profile_id():
            self.view3d_requested.emit(self.current_profile_id(), "cut")

    def _uncut_3d(self, *_args) -> None:
        self.view3d_requested.emit(self.current_profile_id() or "", "uncut")

    def _show_3d_dialog(self, *_args) -> None:
        self.view3d_requested.emit(self.current_profile_id() or "", "dialog")

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
