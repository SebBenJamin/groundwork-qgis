"""Section panel: a native elevation-profile canvas fed by the workbench profile source,
with a profile chooser, layer list, vertical exaggeration and a cursor readout.

Coordinates: ``open_profile`` always sets the canvas curve in the profile's own direction,
so canvas distance == forward profile chainage (what ``cursor_moved``, ``show_cursor`` and
``SectionDataProvider.identify`` use). Keep it that way, or convert (length - s) here.
"""
from __future__ import annotations

import numpy as np
from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsLineString, QgsPoint,
                       QgsProfilePoint, QgsProject, QgsSettings)
from qgis.gui import QgsElevationProfileCanvas, QgsPlotToolPan
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QEvent, QLineF, Qt, QTimer, pyqtSignal
from qgis.PyQt.QtGui import QColor, QKeySequence, QPen, QShortcut
from qgis.PyQt.QtWidgets import (QComboBox, QDockWidget, QDoubleSpinBox, QGraphicsLineItem,
                                 QToolTip,
                                 QHBoxLayout, QLabel, QSizePolicy, QSplitter, QToolButton,
                                 QVBoxLayout,
                                 QWidget)

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
SPLITTER_KEY = "geophysics_workbench/section/splitter"
DEFAULT_VE = AUTO_VE
HINT_NO_PROJECT = "No project open."
HINT_NO_PROFILE = "Choose a profile above, or pick one on the map."
HINT_HOVER = "Move the mouse over the section to read values."
MISSING_PROFILE = "Profile not found in the workbench project; it may have been deleted."


def _registered_source_for(provider):
    source = QgsApplication.profileSourceRegistry().findSourceById(SOURCE_ID)
    return source if getattr(source, "provider", None) is provider else None


class _Readout(QLabel):
    """One line under the section. Its text never sizes the panel (a long readout over
    cores or crossings widened the panel, and the locked-scale canvas seemed to zoom in);
    what does not fit is cut off, and the tooltip shows it all."""

    def __init__(self):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.setMinimumWidth(1)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)


class SectionDock(QDockWidget):
    cursor_moved = pyqtSignal(float, float)     # forward chainage, elevation
    cursor_left = pyqtSignal()                  # the mouse left the section
    profile_changed = pyqtSignal(object)        # open profile id, or None when closed
    borehole_clicked = pyqtSignal(int, str)     # (borehole entry, label): open the viewer

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
        self.readout.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.readout.setMinimumHeight(self.readout.sizeHint().height())
        self.errors = QLabel()
        self.errors.setStyleSheet("color: #c00000;")
        self.errors.setWordWrap(True)
        self.errors.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.errors.hide()

        top = QHBoxLayout()
        top.addWidget(QLabel("Profile"))
        top.addWidget(self.profile_combo)
        top.addWidget(self.topo.label)
        top.addWidget(self.topo_combo)
        top.addStretch(1)
        top.addWidget(QLabel("Vertical exaggeration"))
        top.addWidget(self.ve_spin)
        top.addWidget(zoom_button)
        # an empty panel says what to do instead of showing empty axes
        self.empty_hint = QLabel(HINT_NO_PROFILE)
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
        if not np.array_equal(profile.xy, self._profile.xy):
            self._profile = profile
            self._set_curve(profile)
        self._sync_layers()
        self.canvas.refresh()

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
        self._layers = self._ctx = None
        self._fill_combo()
        self.topo.sync()
        self.canvas.setCrs(QgsCoordinateReferenceSystem(self.provider.store.crs_authid))
        self._set_curve(profile)
        if self._source is not None and not self.canvas.sources():
            self.canvas.setSources([self._source])
        self._sync_layers()
        self.canvas.refresh()
        self.zoom_full()
        self.show_cursor(None)
        self._set_hint()
        self.profile_changed.emit(profile_id)
        return True

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
        etype = event.type()
        if obj is self.canvas.viewport():
            if etype == QEvent.Type.Leave:
                self.cursor_left.emit()
            elif etype in (QEvent.Type.MouseButtonPress, QEvent.Type.Wheel):
                self.fit.user_navigated()       # the user navigates: keep their view
            if etype == QEvent.Type.MouseButtonPress and \
                    event.button() == Qt.MouseButton.LeftButton:
                self._click_pos = event.position()
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
            self.empty_hint.setText(text)
