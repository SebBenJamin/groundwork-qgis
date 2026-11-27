"""Layer list of the section panel: visibility, opacity and colour scale per dataset, and
a context menu to remove a dataset from its profile."""
from __future__ import annotations

from dataclasses import replace

from qgis.PyQt.QtCore import QByteArray, QEvent, QMimeData, QPoint, QSize, Qt, pyqtSignal
from qgis.PyQt.QtGui import QDrag, QPalette
from qgis.PyQt.QtWidgets import (QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QMenu,
                                 QMessageBox, QScrollArea, QSizePolicy, QSlider, QSplitter,
                                 QToolButton, QVBoxLayout, QWidget)

from ..core.dataset_types import type_label
from .data import SectionLayer, layer_name
from .readout import format_value, unit_label
from .scale_dialog import DisplayDialog, ramp_icon

MIN_WIDTH = 240
MAX_HINT_WIDTH = 300            # preferred width: full layer names, up to this (the section gets the room)
#: ... and wider, up to this, when only then the longest name fits in full (its look summary
#: at its least, the colour swatch)
MAX_FIT_WIDTH = 420
MIN_NAME_WIDTH = 60             # a long name is cut (full name in the tooltip), not the controls
#: the look summary, cut, keeps at least its colour swatch and this (the full look is in its
#: tooltip): the layer name gets the room first
MIN_SUMMARY_TEXT = "…"
REMOVE_TEXT = "Remove from profile…"
#: first entry of a layer whose reader needs a library that is not installed
INSTALL_TEXT = "Install {name}…"
INSTALL_HINT = "Right-click the layer and choose " + INSTALL_TEXT
NEEDS_LIBRARY_TIP = "Install {name} first"
#: style fields the Display dialog edits
DISPLAY_FIELDS = ("scale", "mode", "contour_step", "contour_major", "contour_minor",
                  "grid_cell", "interpolation", "fade_coverage", "coverage_threshold",
                  "fade_mode", "shown", "clip_percent", "gain", "contour_colour",
                  "contour_width")
DISPLAY_TEXT = "Display…"
MISFIT_TEXT = "Misfit summary…"
INFO_TEXT = "Dataset info…"
APPLY_ALL_TEXT = "Apply Style to All Sections"
APPLY_ALL_TIP = ("Give every other {what} of the project this model's colours, display "
                 "and contours (shown or hidden stays as it is)")
APPLY_ALL_OFF_TIP = "There is no other {what} in the project to apply this style to"
APPLY_ALL_TRACES_TIP = ("Give every other {what} of the project this section's colours, clip "
                        "and amplitude display (shown or hidden stays as it is)")
#: the drawing order: the top row is drawn on top (as in the QGIS layer tree)
MOVE_TOP_TEXT = "Move to Top"
MOVE_UP_TEXT = "Move Up"
MOVE_DOWN_TEXT = "Move Down"
MOVE_BOTTOM_TEXT = "Move to Bottom"
ON_TOP_TIP = "This layer is already drawn on top"
AT_BOTTOM_TIP = "This layer is already drawn at the bottom"
HANDLE_TIP = "Drag to change the drawing order (the top row is drawn on top)"
#: what a dragged row carries: its dataset id
ROW_MIME = "application/x-groundwork-section-layer"
SCALE_TIP = "Colour scale and display (cells, smooth, contours, coverage)"
SCALE_TRACES_TIP = "Colour scale, clip and amplitude display"


def _scale_text(layer: SectionLayer) -> str:
    scale = layer.style.scale
    if scale is None:
        return "Scale…"
    if layer.traces is not None:
        return trace_look_text(layer.style.clip_percent, layer.style.gain, scale,
                               layer.style.max_depth)
    log = " log" if scale.log else ""
    return f"{format_value(scale.vmin)}–{format_value(scale.vmax)}{log}"


def gain_word(gain) -> str:
    """"AGC" when AGC is on, "gain" for gain with time or trace balance, else "" (a swapped
    polarity is not a gain)."""
    if gain is None:
        return ""
    if gain.agc_window is not None and gain.agc_window > 0:
        return "AGC"
    if (gain.time_power is not None and gain.time_power != 0) or gain.balance_traces:
        return "gain"
    return ""


def filter_words(gain) -> list[str]:
    """The display filters that are on, in processing order: "dewow", "band-pass",
    "background"."""
    if gain is None:
        return []
    out = ["dewow"] if gain.dewow_window is not None and gain.dewow_window > 0 else []
    out += ["band-pass"] if gain.band_on() else []
    return out + (["background"] if gain.background in ("all", "window") else [])


def trace_look_text(clip_percent, gain, scale=None, max_depth=None) -> str:
    """A trace section's look in a few words, what is on in processing order: "clip 98 %",
    "clip 98 % · band-pass · background · AGC", or the typed limits ("-500–500 · gain");
    the depth it is shown down to last ("to 8 m")."""
    if clip_percent is not None or scale is None:
        text = clip_text(98.0 if clip_percent is None else clip_percent)
    else:
        text = f"{format_value(scale.vmin)}–{format_value(scale.vmax)}"
    words = filter_words(gain) + ([gain_word(gain)] if gain_word(gain) else [])
    if max_depth is not None and max_depth > 0:
        words.append(f"to {depth_text(max_depth)} m")
    return " · ".join([text] + words)


def depth_text(metres: float) -> str:
    """"8", "2.5", "0.25": a depth limit to the centimetre without trailing zeros, in the
    QGIS locale."""
    from qgis.PyQt.QtCore import QLocale
    v = round(float(metres), 2)
    decimals = 0 if v == int(v) else 1 if round(v, 1) == v else 2
    return QLocale().toString(v, "f", decimals)


def error_line(layer: SectionLayer) -> str:
    """The panel's error line of a layer: its name and error, and for a missing library how
    to install it."""
    text = f"{layer_name(layer.dataset)}: {layer.error}"
    if layer.missing_library:
        text += " " + INSTALL_HINT.format(name=layer.missing_library)
    return text


def clip_text(percent: float) -> str:
    """"clip 98 %": a trace layer's clip, with at most one decimal, in the QGIS locale."""
    from qgis.PyQt.QtCore import QLocale
    p = round(float(percent), 1)
    return f"clip {QLocale().toString(p, 'f', 0 if p == int(p) else 1)} %"


def _exec_once(menu: QMenu, pos) -> None:
    """Show a context menu, then free it (it is parented to the list and would pile up)."""
    menu.exec(pos)
    menu.deleteLater()


class _ElidedCheck(QCheckBox):
    """A check box whose text is cut in the middle with "…" (names on one line often share
    their start; the full name is in the tooltip)."""

    def __init__(self, text: str):
        super().__init__(text)
        self._full = text

    def full_text(self) -> str:
        return self._full

    def sizeHint(self):
        hint = super().sizeHint()
        cut = self.fontMetrics().horizontalAdvance(self.text())
        full = self.fontMetrics().horizontalAdvance(self._full)
        return QSize(hint.width() - cut + full, hint.height())

    def resizeEvent(self, event):
        indicator = self.style().pixelMetric(self.style().PixelMetric.PM_IndicatorWidth) + 8
        room = max(10, self.width() - indicator)
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle,
                                                      room))
        super().resizeEvent(event)


class _SummaryButton(QToolButton):
    """The look summary beside a layer name: its text is cut at the end with "…" when the
    row is short of room (the full text leads its tooltip); the colour swatch always stays."""

    def __init__(self):
        super().__init__()
        self._full = ""
        self._tip = ""

    def full_text(self) -> str:
        return self._full

    def set_summary(self, text: str, tip: str) -> None:
        self._full, self._tip = text, tip
        super().setText(text)
        self._elide()
        self.updateGeometry()

    def _overhead(self) -> int:
        """Width of the button without its text (swatch, margins)."""
        return super().sizeHint().width() - self.fontMetrics().horizontalAdvance(self.text())

    def sizeHint(self):
        hint = super().sizeHint()
        cut = self.fontMetrics().horizontalAdvance(self.text())
        return QSize(hint.width() - cut + self.fontMetrics().horizontalAdvance(self._full),
                     hint.height())

    def minimumSizeHint(self):
        room = self.fontMetrics().horizontalAdvance(MIN_SUMMARY_TEXT)
        full = self.fontMetrics().horizontalAdvance(self._full)
        return QSize(self._overhead() + min(room, full), self.sizeHint().height())

    def _elide(self) -> None:
        if not self._full:
            self.setToolTip(self._tip)
            return
        room = max(10, self.width() - self._overhead())
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, room)
        if shown != self.text():
            super().setText(shown)
        self.setToolTip(self._tip if shown == self._full else f"{self._full}\n{self._tip}")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._elide()


class _DragHandle(QLabel):
    """The grip at the start of a row: dragging it moves the row (and the layer's drawing
    order)."""

    def __init__(self, row: "_LayerRow"):
        super().__init__("≡")
        self._row = row
        self._press = None
        self.setToolTip(HANDLE_TIP)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setFixedWidth(self.fontMetrics().horizontalAdvance("≡") + 4)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        if (event.position().toPoint() - self._press).manhattanLength() \
                < QApplication.startDragDistance():
            return
        self._press = None
        self._row.start_drag()

    def mouseReleaseEvent(self, event):
        self._press = None
        super().mouseReleaseEvent(event)


class _LayerRow(QWidget):
    def __init__(self, layer: SectionLayer, owner: "LayerList"):
        super().__init__()
        self.dataset_id = layer.dataset.id
        self._owner = owner
        self.handle = _DragHandle(self)
        self.check = _ElidedCheck(layer_name(layer.dataset))
        self.check.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.check.setMinimumWidth(MIN_NAME_WIDTH)
        self.check.toggled.connect(lambda on: owner.set_visible(self.dataset_id, on))
        self.opacity = QSlider(Qt.Orientation.Horizontal)
        self.opacity.setRange(0, 100)
        self.opacity.setFixedWidth(60)
        self.opacity.setToolTip("Opacity")
        self.opacity.valueChanged.connect(self._opacity_changed)
        self.opacity.sliderReleased.connect(self._opacity_changed)
        self.scale_button = _SummaryButton()
        self.scale_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.scale_button.setIconSize(QSize(40, 10))
        self._scale_tip = SCALE_TIP if layer.traces is None else SCALE_TRACES_TIP
        self.scale_button.clicked.connect(lambda: owner.edit_scale(self.dataset_id))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: _exec_once(owner.row_menu(self.dataset_id), self.mapToGlobal(pos)))
        for child in (self.check, self.opacity, self.scale_button):     # menu on the controls too
            child.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 1, 2, 1)
        row.addWidget(self.handle)
        row.addWidget(self.check, 1)
        row.addWidget(self.opacity)
        row.addWidget(self.scale_button)
        self.update_from(layer)

    def update_from(self, layer: SectionLayer) -> None:
        style = layer.style
        for widget, setter, value in ((self.check, self.check.setChecked, style.visible),
                                      (self.opacity, self.opacity.setValue,
                                       round(style.opacity * 100))):
            widget.blockSignals(True)
            setter(value)
            widget.blockSignals(False)
        ok = layer.error is None
        self.opacity.setEnabled(ok)
        self.scale_button.setEnabled(ok)
        if style.scale is not None:
            self.scale_button.setIcon(ramp_icon(style.scale, 40, 10))
        self.scale_button.set_summary(_scale_text(layer), self._scale_tip)
        d = layer.dataset
        tip = f"{layer_name(d)} (version {d.version})\n{type_label(d.kind)}\n{d.source_path}"
        self.check.setToolTip(tip if ok else f"{tip}\n\n{layer.error}")
        self.check.setStyleSheet("" if ok else "color: #c00000;")
        self._share_room()

    def _others(self) -> int:
        """Width of the row without the name and the summary: margins, the handle, the
        opacity slider and the spacing between them."""
        layout = self.layout()
        margins = layout.contentsMargins()
        shown = [w for w in (self.handle, self.check, self.opacity, self.scale_button)
                 if not w.isHidden()]
        fixed = sum(w.minimumWidth() for w in shown if w in (self.handle, self.opacity))
        gaps = max(0, layout.spacing()) * (len(shown) - 1)
        return margins.left() + margins.right() + fixed + gaps

    def widths(self) -> tuple[int, int]:
        """(least, full): the row's width with the name and the summary at their least, and
        with both in full."""
        button = self.scale_button
        return (self._others() + MIN_NAME_WIDTH + button.minimumSizeHint().width(),
                self._others() + self.check.sizeHint().width() + button.sizeHint().width())

    def name_width(self) -> int:
        """The row's width with the name in full and the summary at its least."""
        return (self._others() + self.check.sizeHint().width()
                + self.scale_button.minimumSizeHint().width())

    def _share_room(self) -> None:
        """The name gets the room first: the summary is cut (down to its least) before the
        name is; only then is the name cut too."""
        button = self.scale_button
        room = self.width() - self._others()
        full, least = button.sizeHint().width(), button.minimumSizeHint().width()
        width = max(least, min(full, room - max(MIN_NAME_WIDTH, self.check.sizeHint().width())))
        if button.minimumWidth() != width or button.maximumWidth() != width:
            button.setFixedWidth(width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._share_room()

    def start_drag(self) -> None:
        """Drag this row (the list's drop moves it; a picture of the row follows the
        mouse)."""
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(ROW_MIME, QByteArray(self.dataset_id.encode("utf-8")))
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        drag.setHotSpot(QPoint(self.handle.width() // 2, self.height() // 2))
        drag.exec(Qt.DropAction.MoveAction)

    def _opacity_changed(self, *_):
        if self.opacity.isSliderDown():          # apply once on release, not per pixel
            return
        self._owner.set_opacity(self.dataset_id, self.opacity.value() / 100.0)


class LayerList(QWidget):
    """One row per dataset of the open profile, topmost layer first."""

    style_changed = pyqtSignal(str)
    dataset_removed = pyqtSignal(str)
    #: Apply Style to All Sections chosen for a model (the panel applies it, undoably)
    apply_all_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.provider = None
        #: where an install's result is said (QGIS's message bar; None: QGIS's own)
        self.message_bar = None
        self._install_task = None
        self._layers: dict[str, SectionLayer] = {}
        self._rows: dict[str, _LayerRow] = {}
        title = QLabel("<b>Layers</b>")
        self._empty = QLabel("No datasets on this profile")
        self._empty.setStyleSheet("color: gray;")
        self._box = QWidget()
        self._box_layout = QVBoxLayout(self._box)
        self._box_layout.setContentsMargins(0, 0, 0, 0)
        self._box_layout.setSpacing(0)
        self._box_layout.addStretch(1)
        self._box.setAcceptDrops(True)
        self._box.installEventFilter(self)
        # where a dragged row will land: a line in the selection colour
        self._drop_line = QFrame(self._box)
        self._drop_line.setFrameShape(QFrame.Shape.HLine)
        self._drop_line.setFrameShadow(QFrame.Shadow.Plain)
        self._drop_line.setLineWidth(2)
        palette = self._drop_line.palette()
        palette.setColor(QPalette.ColorRole.WindowText,
                         palette.color(QPalette.ColorRole.Highlight))
        self._drop_line.setPalette(palette)
        self._drop_line.hide()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll = scroll
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._box)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(title)
        layout.addWidget(self._empty)
        layout.addWidget(scroll, 1)
        self._hint_width = MIN_WIDTH
        #: the user dragged the splitter (or a saved width was restored): the list no longer
        #: widens by itself, so a list narrowed or collapsed by hand stays that way
        self.sized_by_user = False
        self.setMinimumWidth(MIN_WIDTH)

    def dataset_ids(self) -> list[str]:
        return list(self._rows)

    def set_layers(self, provider, layers: list[SectionLayer]) -> None:
        """Show ``layers`` (drawing order, bottom first). Rows are rebuilt only when the
        set of datasets changes, otherwise updated in place."""
        self.provider = provider
        self._layers = {la.dataset.id: la for la in layers}
        ids = [la.dataset.id for la in reversed(layers)]
        if ids != list(self._rows):
            for row in self._rows.values():
                self._box_layout.removeWidget(row)
                row.deleteLater()
            self._rows = {}
            for i, dataset_id in enumerate(ids):
                row = _LayerRow(self._layers[dataset_id], self)
                self._box_layout.insertWidget(i, row)
                self._rows[dataset_id] = row
        else:
            for dataset_id, row in self._rows.items():
                row.update_from(self._layers[dataset_id])
        for row in self._rows.values():          # one layer: there is no order to change
            row.handle.setVisible(len(self._rows) > 1)
        self._empty.setVisible(not ids)
        self._fit_width()

    def _fit_width(self) -> None:
        """Wide enough for every row's controls (the list never scrolls sideways). The
        preferred width shows every name and look in full up to ``MAX_HINT_WIDTH``, and the
        longest name in full (its look cut to the swatch) up to ``MAX_FIT_WIDTH``."""
        rows = list(self._rows.values())
        extra = (self.layout().contentsMargins().left() + self.layout().contentsMargins().right()
                 + self._scroll.verticalScrollBar().sizeHint().width() + 4)
        need = max([r.widths()[0] for r in rows], default=0) + extra
        full = max([r.widths()[1] for r in rows], default=0) + extra
        names = max([r.name_width() for r in rows], default=0) + extra
        self.setMinimumWidth(max(MIN_WIDTH, need))
        self._hint_width = max(self.minimumWidth(), min(full, MAX_HINT_WIDTH),
                               min(names, MAX_FIT_WIDTH))
        self.updateGeometry()
        self._grow_in_splitter()

    def _grow_in_splitter(self) -> None:
        """A splitter reads size hints only when first shown: widen this list to its hint
        by taking space from the widest neighbour. Never shrinks, and does nothing once the
        user has sized the list (``sized_by_user``)."""
        splitter = self.parentWidget()
        if self.sized_by_user or not isinstance(splitter, QSplitter):
            return
        sizes = splitter.sizes()
        i = splitter.indexOf(self)
        if i < 0 or sum(sizes) <= 0 or sizes[i] >= self._hint_width:
            return
        j = max((k for k in range(len(sizes)) if k != i), key=lambda k: sizes[k], default=None)
        if j is None:
            return
        grow = min(self._hint_width - sizes[i], max(0, sizes[j] - 200))
        sizes[i] += grow
        sizes[j] -= grow
        splitter.setSizes(sizes)

    def sizeHint(self) -> QSize:
        hint = super().sizeHint()
        return QSize(max(hint.width(), self._hint_width), hint.height())

    def clear(self) -> None:
        self.set_layers(self.provider, [])

    # -- drawing order -----------------------------------------------------------------------
    def move_layer(self, dataset_id: str, where: str) -> None:
        """Move a row "top", "up", "down" or "bottom" (the top row is drawn on top)."""
        ids = list(self._rows)
        if dataset_id not in ids:
            return
        i = ids.index(dataset_id)
        target = {"top": 0, "up": i - 1, "down": i + 1, "bottom": len(ids) - 1}[where]
        self.move_to_row(dataset_id, min(max(target, 0), len(ids) - 1))

    def move_to_row(self, dataset_id: str, row: int) -> None:
        """Put ``dataset_id``'s row at ``row`` (0 = the top) and draw the layers in the new
        order; the order is kept with the profile."""
        ids = list(self._rows)
        if dataset_id not in ids or self.provider is None:
            return
        ids.remove(dataset_id)
        ids.insert(min(max(row, 0), len(ids)), dataset_id)
        if ids == list(self._rows):
            return
        bottom_first = ids[::-1]
        layers = [self._layers[i] for i in bottom_first]
        self.provider.set_layer_order(layers[0].dataset.profile_id, bottom_first)
        self.set_layers(self.provider, layers)

    def _drop_slot(self, y: float) -> int:
        """The row a drop at ``y`` (in the box) lands on: before the first row whose middle
        lies below it."""
        rows = list(self._rows.values())
        return sum(1 for r in rows if r.geometry().center().y() < y)

    def _show_drop_line(self, slot: int) -> None:
        rows = list(self._rows.values())
        if not rows:
            return
        y = rows[slot].geometry().top() if slot < len(rows) else rows[-1].geometry().bottom()
        self._drop_line.setGeometry(0, max(0, y - 1), self._box.width(), 3)
        self._drop_line.raise_()
        self._drop_line.show()

    def eventFilter(self, obj, event):
        if obj is self._box:
            kind = event.type()
            if kind in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
                if not event.mimeData().hasFormat(ROW_MIME):
                    return False
                y = event.position().y()
                if kind == QEvent.Type.Drop:
                    self._drop_line.hide()
                    dataset_id = bytes(event.mimeData().data(ROW_MIME)).decode("utf-8")
                    event.acceptProposedAction()
                    self.move_to_row(dataset_id, self._drop_slot(y))
                else:
                    self._show_drop_line(self._drop_slot(y))
                    event.acceptProposedAction()
                return True
            if kind == QEvent.Type.DragLeave:
                self._drop_line.hide()
        return super().eventFilter(obj, event)

    # -- style changes ---------------------------------------------------------------------
    def _update_style(self, dataset_id: str, **changes) -> None:
        if self.provider is None:
            return
        style = replace(self.provider.style(dataset_id), **changes)
        self.provider.set_style(dataset_id, style)
        layer = self._layers.get(dataset_id)
        if layer is not None:
            layer.style = style
            row = self._rows.get(dataset_id)
            if row is not None:
                row.update_from(layer)
                self._fit_width()               # the scale text may have grown
        self.style_changed.emit(dataset_id)

    def set_visible(self, dataset_id: str, visible: bool) -> None:
        self._update_style(dataset_id, visible=bool(visible))

    def set_opacity(self, dataset_id: str, opacity: float) -> None:
        self._update_style(dataset_id, opacity=min(1.0, max(0.0, float(opacity))))

    def set_scale(self, dataset_id: str, scale) -> None:
        self._update_style(dataset_id, scale=scale)

    # -- removing ----------------------------------------------------------------------------
    def row_menu(self, dataset_id: str) -> QMenu:
        """Context menu of a row (the caller shows and owns it)."""
        menu = QMenu(self)
        layer = self._layers.get(dataset_id)
        name = None if layer is None else layer.missing_library
        if name:
            action = menu.addAction(INSTALL_TEXT.format(name=name))
            action.setEnabled(self._install_task is None)
            action.triggered.connect(lambda: self.install_library(name))
            menu.addSeparator()
        display = menu.addAction(DISPLAY_TEXT)
        display.triggered.connect(lambda: self.edit_scale(dataset_id))
        if name:                                    # nothing read: nothing to display yet
            display.setEnabled(False)
            display.setToolTip(NEEDS_LIBRARY_TIP.format(name=name))
            menu.setToolTipsVisible(True)
        readings = None if layer is None or layer.mesh is None else layer.mesh.readings
        if readings is not None and readings.has_calculated:
            menu.addAction(MISFIT_TEXT).triggered.connect(
                lambda: self.show_misfit(dataset_id))
        menu.addAction(INFO_TEXT).triggered.connect(lambda: self.edit_info(dataset_id))
        menu.addSeparator()
        if len(self._rows) > 1:                     # one layer: there is no order to change
            self._add_moves(menu, dataset_id)
            menu.addSeparator()
        self._add_apply_all(menu, dataset_id)
        menu.addSeparator()
        menu.addAction(REMOVE_TEXT).triggered.connect(lambda: self.remove_dataset(dataset_id))
        return menu

    def _add_moves(self, menu: QMenu, dataset_id: str) -> None:
        """Move to Top, Move Up, Move Down, Move to Bottom (disabled where they do
        nothing, the tooltip says why)."""
        ids = list(self._rows)
        i = ids.index(dataset_id) if dataset_id in ids else -1
        on_top, at_bottom = i <= 0, i < 0 or i == len(ids) - 1
        for text, where, off, tip in ((MOVE_TOP_TEXT, "top", on_top, ON_TOP_TIP),
                                      (MOVE_UP_TEXT, "up", on_top, ON_TOP_TIP),
                                      (MOVE_DOWN_TEXT, "down", at_bottom, AT_BOTTOM_TIP),
                                      (MOVE_BOTTOM_TEXT, "bottom", at_bottom, AT_BOTTOM_TIP)):
            action = menu.addAction(text)
            action.setEnabled(not off)
            if off:
                action.setToolTip(tip)
            action.triggered.connect(lambda _=False, w=where: self.move_layer(dataset_id, w))
        menu.setToolTipsVisible(True)

    def _add_apply_all(self, menu: QMenu, dataset_id: str) -> None:
        from ..core.dataset_types import type_label
        from .style_store import same_method
        targets = same_method(self.provider.store, dataset_id) if self.provider else []
        layer = self._layers.get(dataset_id)
        what = type_label(layer.dataset.kind) if layer is not None else "model"
        action = menu.addAction(APPLY_ALL_TEXT)
        missing = None if layer is None else layer.missing_library
        action.setEnabled(bool(targets) and not missing)
        tip = APPLY_ALL_TIP if layer is None or layer.traces is None else APPLY_ALL_TRACES_TIP
        action.setToolTip(NEEDS_LIBRARY_TIP.format(name=missing) if missing else
                          (tip if targets else APPLY_ALL_OFF_TIP).format(what=what))
        menu.setToolTipsVisible(True)
        action.triggered.connect(lambda: self.apply_all_requested.emit(dataset_id))

    def install_library(self, name: str) -> None:
        """Install segyio… (a layer whose reader needs a library that is missing): ask, then
        install it in a QGIS task; the result goes to the message bar, and on success the
        sections are read again."""
        from ..ui.lib_install import ask_install, start_install
        if self._install_task is not None or not ask_install(self, name):
            return
        self._install_task = start_install(name)
        self._install_task.done.connect(lambda ok, message: self._installed(name, ok, message))

    def _installed(self, name: str, ok: bool, message: str) -> None:
        from ..ui.lib_install import show_result
        self._install_task = None
        show_result(self.message_bar, name, ok, message, self)
        if ok and self.provider is not None:
            self.provider.notify_changed()          # the failed layers are read again

    def edit_info(self, dataset_id: str) -> None:
        """Dataset info…: method, array, spacing, inversion, reference (for provenance); a
        reflection section's vertical settings (the section is drawn again when they move it)."""
        from ..ui.dataset_info_dialog import DatasetInfoDialog
        if self.provider is None:
            return
        dlg = DatasetInfoDialog(self.provider.store, dataset_id, self, provider=self.provider)
        dlg.exec()
        if dlg.moved:
            self.provider.notify_changed()
        dlg.deleteLater()

    def remove_dataset(self, dataset_id: str) -> bool:
        """Ask, then remove the dataset from its profile (store, provider; the section panel
        refreshes on the provider's change notice). The model file is not touched."""
        layer = self._layers.get(dataset_id)
        if self.provider is None or layer is None:
            return False
        answer = QMessageBox.question(
            self, "Remove from profile",
            f"Remove “{layer_name(layer.dataset)}” from this profile?\n\n"
            "The model file stays where it is; you can add it again with Add Data.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return False
        self.provider.remove_dataset(dataset_id)
        self.dataset_removed.emit(dataset_id)
        return True

    def edit_scale(self, dataset_id: str) -> None:
        layer = self._layers.get(dataset_id)
        if layer is None:
            return
        dialog = DisplayDialog(self, layer)
        dialog.applied_style.connect(lambda style: self.set_display(dataset_id, **{
            f: getattr(style, f) for f in DISPLAY_FIELDS}))
        dialog.exec()
        dialog.deleteLater()

    def show_misfit(self, dataset_id: str) -> None:
        """Open (or bring forward) the misfit summary for this layer."""
        from ..ui.misfit_panel import MisfitSummary
        layer = self._layers.get(dataset_id)
        if layer is None or layer.mesh is None or layer.mesh.readings is None:
            return
        if getattr(self, "_misfit", None) is None:
            self._misfit = MisfitSummary(self)
        self._misfit.show_layer(layer)
        self._misfit.show()
        self._misfit.raise_()

    def set_display(self, dataset_id: str, **changes) -> None:
        """Change how a layer is drawn (scale, mode, contours, coverage fade)."""
        self._update_style(dataset_id, **changes)
