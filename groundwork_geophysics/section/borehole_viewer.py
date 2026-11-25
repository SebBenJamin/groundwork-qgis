"""The borehole viewer: the current profile's boreholes side by side, in a window of its own.

It shows what the section shows (the same gathered context, so the content is identical),
drawn with the same borehole drawing and the same QGIS styles. Two spacings (even, or true
distance with the ground line), elevation or depth, one vertical scale for every column,
free zoom and pan, display parts to switch on and off. Nothing links boreholes on its own:
no correlation lines, no fills between columns."""
from __future__ import annotations

import json
from dataclasses import replace
from functools import partial

import numpy as np
from qgis.core import QgsSettings, QgsTextFormat
from qgis.gui import QgsFontButton
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter, QPalette, QPen, QPolygonF
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QGroupBox,
                                 QHBoxLayout, QSpinBox,
                                 QLabel, QMenu, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..core.borehole_curves import data_range
from ..core.borehole_layout import (ViewTransform, column_depth, even_gap, extent_z, fit,
                                    layout_even,
                                    vertical_exaggeration)
from ..core.context import borehole_key, collar_height
from ..core.context_settings import COLUMN_PX_RANGE, OPACITY_RANGE
from .borehole_draw import (ColumnOptions, SymbolPool, draw_borehole, draw_flag,
                            layer_text_width, shown_curve_keys, text_font,
                            track_header_px)
from ..core.numbers import fmt
from ..ids import LEGACY_ID

SCOPE = LEGACY_ID
OPTIONS_KEY = "borehole_viewer"
GEOMETRY_KEY = f"{LEGACY_ID}/borehole_viewer/geometry"
COLUMN_PX = 28
TRACK_PX = 60
GAP_PX = 40
MIN_GAP_PX = 12              # even spacing: the gaps shrink down to this to fit the window
AUTO_VE = 0.0                # the VE box's "Auto": the exaggeration that fills the window
VE_TIP = "Vertical exaggeration (Auto: fill the window)"
AXIS_PX = 52                 # left margin for the vertical axis
LABEL_PX = 54                # room above the columns for the labels
GROUND_RGB = (90, 140, 60)
AXIS_RGB = (60, 60, 60)
SHOW = (("lithology", "Lithology", True), ("text", "Layer text", False),
        ("ticks", "Depth ticks", False), ("flags", "Height flags", True),
        ("hidden", "Hidden boreholes", True))
HIDDEN_OPACITY = 0.35        # a borehole hidden in the section, still shown here
BACKGROUND_RGB = (255, 255, 255)
HIDDEN_MARK = "hidden in section"
CLICK_PX = 4                 # a press and release closer than this is a click, not a pan
NO_BOREHOLES = ("This profile has no boreholes nearby. Add a borehole layer in "
                "Context Layers…, or open another profile in the section panel.")
ALL_HIDDEN = ("Every borehole of this profile is hidden in its section. Tick Show › Hidden "
              "boreholes to see them here.")
LABELS = (("name", "Name", True), ("elevation", "Elevation", True),
          ("distance", "Distance / offset", False))


class BoreholeCanvas(QWidget):
    """Draws the columns; zoom with the wheel (Ctrl: vertical only, Shift: horizontal only),
    pan by dragging."""

    def __init__(self, viewer):
        super().__init__()
        self.viewer = viewer
        self.transform: ViewTransform | None = None
        self.column_rects: list = []          # [(ProjectedPoint, QRectF)] of the last paint
        self.dropped_labels: list[str] = []   # labels of the last paint left out for want of room
        self._drag = None
        self._press = None
        self.setMouseTracking(True)
        self.setMinimumSize(300, 240)

    # -- geometry ------------------------------------------------------------------------------
    def layer_font(self):
        """The font the layer text is drawn with (as ``borehole_draw`` picks it), for
        measuring how much room the text needs."""
        img = QImage(1, 1, QImage.Format.Format_ARGB32)
        dots = round(self.logicalDpiX() / 0.0254)
        img.setDotsPerMeterX(dots)
        img.setDotsPerMeterY(dots)
        painter = QPainter(img)
        try:
            from qgis.core import QgsRenderContext
            return text_font(painter, QgsRenderContext.fromQPainter(painter))
        finally:
            painter.end()

    def _widths(self, points) -> list[float]:
        """Each column's drawn width: the column, its curve tracks and its layer text."""
        v = self.viewer
        keys = tuple(v.chosen_curves())
        font = self.layer_font() if v.show_check["text"].isChecked() else None
        return [COLUMN_PX + len(shown_curve_keys(p, keys)) * (TRACK_PX + 4)
                + (layer_text_width(p, font) if font is not None else 0.0) for p in points]

    def _even_room(self) -> float:
        return max(1.0, self.width() - AXIS_PX - 8.0)

    def _x_layout(self, points) -> list[float]:
        """Each column's centre in layout units (px for even, metres for true distance); even
        gaps shrink so the columns fit the window."""
        if self.viewer.mode == "even":
            widths = self._widths(points)
            gap = even_gap(widths, self._even_room(), GAP_PX, MIN_GAP_PX)
            return [c.x + COLUMN_PX / 2 for c in layout_even(widths, gap)]
        return [p.s for p in points]

    def off_view(self) -> tuple[int, int]:
        """Even spacing: how many columns of the last paint lie wholly left / right of the
        window; (0, 0) in true distance."""
        if self.viewer.mode != "even":
            return 0, 0
        left = sum(1 for _p, r in self.column_rects if r.right() < AXIS_PX)
        right = sum(1 for _p, r in self.column_rects if r.left() > self.width())
        return left, right

    def _z_top(self, p) -> float | None:
        surface = self.viewer.surface_at(p.s)
        return collar_height(p.z_top, None, surface)[0]

    def drawable(self) -> list:
        if self.viewer.axis == "depth":
            return list(self.viewer.boreholes)
        return [p for p in self.viewer.boreholes if self._z_top(p) is not None]

    def fit_view(self) -> None:
        points = self.drawable()
        w, h = max(1, self.width()), max(1, self.height())
        if not points:
            self.transform = ViewTransform(0.0, 1.0, 0.0, 10.0)
            return
        if self.viewer.axis == "depth":
            ez = extent_z(points, "depth", self.viewer.surface_at)
            ez = (-ez[1], -ez[0])
        else:
            ez = extent_z(points, "elevation", self.viewer.surface_at)
        xs = self._x_layout(points)
        if self.viewer.mode == "even":
            t = fit((0.0, 1.0), ez, (w - AXIS_PX, h - LABEL_PX), None)
            total = xs[-1] - COLUMN_PX / 2 + self._widths(points)[-1]
            spare = self._even_room() - total             # < 0: start at the left edge
            t = ViewTransform(-(AXIS_PX + max(0.0, spare / 2)), 1.0,
                              t.z0 + LABEL_PX / t.z_scale, t.z_scale)
        else:
            pad = max(5.0, 0.05 * (max(xs) - min(xs)))
            extent_x, size = (min(xs) - pad, max(xs) + pad), (w - AXIS_PX, h - LABEL_PX)
            if self.viewer.is_auto_ve():                  # the exaggeration that fills both ways
                from .view_fit import AUTO_MAX, AUTO_MIN
                ve = vertical_exaggeration(fit(extent_x, ez, size, None))
                ve = min(max(ve, AUTO_MIN), AUTO_MAX)
                self.viewer.show_auto_ve(ve)
            else:
                ve = self.viewer.ve_spin.value()
                self.viewer.ve_spin.setToolTip(VE_TIP)
            t = fit(extent_x, ez, size, ve)
            t = ViewTransform(t.x0 - AXIS_PX / t.x_scale, t.x_scale,
                              t.z0 + LABEL_PX / t.z_scale, t.z_scale)
        self.transform = t

    # -- painting ------------------------------------------------------------------------------
    def render_image(self, size=None) -> QImage:
        w, h = size or (max(1, self.width()), max(1, self.height()))
        img = QImage(int(w), int(h), QImage.Format.Format_ARGB32)
        img.fill(0xFFFFFFFF)
        painter = QPainter(img)
        try:
            self._paint(painter)
        finally:
            painter.end()
        return img

    def empty_hint(self) -> str:
        """What the empty canvas says: no boreholes on this profile, or all of them hidden;
        "" when some are shown."""
        v = self.viewer
        if not v.profile_id or v.boreholes:
            return ""
        return ALL_HIDDEN if v.hidden and not v.show_check["hidden"].isChecked() else NO_BOREHOLES

    def paintEvent(self, _event):
        painter = QPainter(self)
        try:
            painter.fillRect(self.rect(), QColor(*BACKGROUND_RGB))
            hint = self.empty_hint()
            if hint:
                self.column_rects = []
                self.dropped_labels = []
                painter.setPen(QPen(QColor(*AXIS_RGB)))
                painter.drawText(self.rect().adjusted(24, 24, -24, -24),
                                 int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                                 hint)
                return
            self._paint(painter)
        finally:
            painter.end()

    def _paint(self, painter) -> None:
        from qgis.core import QgsRenderContext
        if self.transform is None:
            self.fit_view()
        t, v = self.transform, self.viewer
        rc = QgsRenderContext.fromQPainter(painter)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        points = self.drawable()
        self.column_rects = []
        if v.mode == "true" and v.axis == "elevation":
            self._ground(painter)
        keys = tuple(v.chosen_curves())
        styles = v.items.curve_styles if v.items is not None else {}
        ranges = v.curve_ranges(keys)
        xs = self._x_layout(points)
        header = track_header_px(text_font(painter, rc))   # above a borehole's curve tracks
        pending = []                      # labels, placed after all columns (no overlaps)
        with SymbolPool(rc) as pool:      # each interval symbol started once per frame
            for p, x in zip(points, xs):
                z_top = self._z_top(p) if v.axis == "elevation" else 0.0
                px = t.to_px(x, 0.0)[0]
                if v.axis == "elevation":
                    y_of = (lambda zt: lambda d: t.to_px(0.0, zt - d)[1])(z_top)
                else:
                    y_of = lambda d: t.to_px(0.0, -d)[1]
                drawn = p if v.show_check["lithology"].isChecked() else replace(
                    p, log=[], total_depth=column_depth(p))
                highlight = v.highlight is not None and (p.entry, p.label) == v.highlight
                opts = ColumnOptions(width_px=COLUMN_PX, layer_text=v.show_check["text"].isChecked(),
                                     ticks=v.show_check["ticks"].isChecked(), curve_keys=keys,
                                     track_px=TRACK_PX, highlight=highlight,
                                     track_backdrop=BACKGROUND_RGB)
                area = draw_borehole(painter, rc, px, y_of, drawn, opts, styles, ranges,
                                         pool)
                if v.is_hidden(p):                # still shown here, faded: a wash of the
                    wash = QColor(*BACKGROUND_RGB)    # background (symbols ignore opacity)
                    wash.setAlphaF(1.0 - HIDDEN_OPACITY)
                    painter.fillRect(area.adjusted(-1, -1, 1, 1), wash)
                col = QRectF(px - COLUMN_PX / 2, area.top(), COLUMN_PX, area.height())
                if borehole_key(p) in v.selected:
                    painter.save()
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Highlight), 2))
                    painter.drawRect(col.adjusted(-3, -3, 3, 3))
                    painter.restore()
                self.column_rects.append((p, col))
                if v.show_check["flags"].isChecked() and p.flagged:
                    draw_flag(painter, px, col.top(), 5.0)
                label_y = col.top() - (header if shown_curve_keys(p, keys) else 0.0)
                pending.append((p, px, label_y, z_top, highlight))
        self._draw_labels(painter, pending)
        self._axis(painter)
        if v.mode == "true":
            painter.setPen(QPen(QColor(*AXIS_RGB)))
            painter.drawText(QPointF(AXIS_PX + 4, painter.device().height() - 6),
                             f"VE {fmt(vertical_exaggeration(t), 1)}×")
        v.update_notes()

    def _ground(self, painter) -> None:
        topo = self.viewer.topo
        if topo is None or len(topo[0]) < 2:
            return
        t = self.transform
        pts = [QPointF(*t.to_px(float(s), float(z))) for s, z in zip(*topo) if np.isfinite(z)]
        if len(pts) > 1:
            painter.setPen(QPen(QColor(*GROUND_RGB), 1.5))
            painter.drawPolyline(QPolygonF(pts))

    def _label_lines(self, p, z_top) -> list[str]:
        v = self.viewer
        lines = []
        if v.label_check["name"].isChecked():
            lines.append(p.label)
        if v.label_check["elevation"].isChecked() and v.axis == "elevation" and z_top is not None:
            lines.append(f"{fmt(z_top, 1)} m")
        if v.label_check["distance"].isChecked():
            lines.append(f"{fmt(p.s, 0)} m, {fmt(p.offset, 0, sign=True)} m")
        if v.is_hidden(p):
            lines.append(HIDDEN_MARK)
        return lines

    def _draw_labels(self, painter, pending) -> None:
        """The columns' labels, in rows so they never overlap (the clicked borehole's
        first); only when the room above the columns is full is a label left out."""
        v = self.viewer
        fmt = v.font_button.textFormat()
        painter.save()
        painter.setFont(fmt.toQFont())
        painter.setPen(QPen(fmt.color()))
        fm = painter.fontMetrics()
        blocks = [(self._label_lines(p, z_top), x, y_top) for p, x, y_top, z_top, _h in pending]
        spans = [(x - w / 2 - 3, x + w / 2 + 3) for lines, x, _y in blocks
                 for w in [max((fm.horizontalAdvance(t) for t in lines), default=0)]]
        highlight = next((i for i, item in enumerate(pending) if item[4]), None)
        block = max((len(lines) for lines, _x, _y in blocks), default=1) * fm.height()
        rows = max(1, int((LABEL_PX - 10) // max(block, 1)))
        self.dropped_labels = []
        for (lines, x, y_top), row, item in zip(blocks, choose_viewer_labels(spans, highlight, rows),
                                                pending):
            if row is None and lines:
                self.dropped_labels.append(item[0].label)
            if row is None or not lines:
                continue
            y = y_top - 10 - row * block
            for text in reversed(lines):
                painter.drawText(QPointF(x - fm.horizontalAdvance(text) / 2, y), text)
                y -= fm.height()
        painter.restore()

    def _axis(self, painter) -> None:
        t, v = self.transform, self.viewer
        h = painter.device().height()
        top_z, bottom_z = t.from_px(0, LABEL_PX)[1], t.from_px(0, h)[1]
        span = max(top_z - bottom_z, 1e-6)
        step = next((s for s in (0.1, 0.2, 0.5, 1, 2, 5, 10, 20, 50, 100, 200, 500)
                     if s * t.z_scale >= 28), 1000)
        painter.save()
        painter.setPen(QPen(QColor(*AXIS_RGB)))
        font = QFont(painter.font())
        font.setPixelSize(10)
        painter.setFont(font)
        painter.drawLine(QPointF(AXIS_PX - 4, LABEL_PX), QPointF(AXIS_PX - 4, h))
        z = np.floor(top_z / step) * step
        while z >= bottom_z - 1e-9 and span > 0:
            y = t.to_px(0, z)[1]
            if y >= LABEL_PX:
                painter.drawLine(QPointF(AXIS_PX - 8, y), QPointF(AXIS_PX - 4, y))
                value = -z if v.axis == "depth" else z
                painter.drawText(QPointF(2, y + 4), tick_text(value))
            z -= step
        painter.drawText(QPointF(2, LABEL_PX - 6),
                         "Depth (m)" if v.axis == "depth" else "Elevation (m)")
        painter.restore()

    # -- readout -------------------------------------------------------------------------------
    def readout_text(self, px: float, py: float) -> list[str]:
        from .context_readout import curve_lines
        if self.transform is None:
            return []
        for p, rect in self.column_rects:
            if not rect.left() - 2 <= px <= rect.right() + 2:
                continue
            z = self.transform.from_px(px, py)[1]
            if self.viewer.axis == "depth":
                depth, elevation = -z, None
            else:
                elevation = z
                depth = self._z_top(p) - z
            if depth < -0.05 or depth > column_depth(p) + 0.05:
                continue
            head = f"{p.label} · depth {fmt(depth, 2)} m"
            if elevation is not None:
                head += f" · elevation {fmt(elevation, 2)} m"
            lines = [head]
            lines += [f"{fmt(iv.top, 2)}–{fmt(iv.bottom, 2)} m {iv.text}" for iv in p.log
                      if iv.top <= depth <= iv.bottom]
            return lines + curve_lines(p, depth)
        return []

    # -- interaction ---------------------------------------------------------------------------
    def wheelEvent(self, event):
        if self.transform is None:
            return
        f = 1.2 ** (event.angleDelta().y() / 120.0)
        mods = event.modifiers()
        fx = 1.0 if mods & Qt.KeyboardModifier.ControlModifier else f
        fz = 1.0 if mods & Qt.KeyboardModifier.ShiftModifier else f
        pos = event.position()
        self.transform = self.transform.zoom_at(pos.x(), pos.y(), fx, fz)
        self.viewer.view_changed()
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = self._press = event.position()

    def mouseReleaseEvent(self, event):
        press, self._drag, self._press = self._press, None, None
        if press is not None and event.button() == Qt.MouseButton.LeftButton:
            moved = event.position() - press
            if abs(moved.x()) + abs(moved.y()) <= CLICK_PX:
                ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
                self.click_at(event.position(), ctrl)

    def column_at(self, pos):
        """The borehole whose column (with its label room) is under ``pos``, or ``None``."""
        for p, rect in self.column_rects:
            if rect.left() - 3 <= pos.x() <= rect.right() + 3 and \
                    rect.top() - LABEL_PX <= pos.y() <= rect.bottom() + 3:
                return p
        return None

    def click_at(self, pos, ctrl: bool) -> None:
        """Select the column under ``pos`` (Ctrl: add or remove it); empty space clears."""
        v = self.viewer
        key = borehole_key(self.column_at(pos)) if self.column_at(pos) is not None else None
        if key is None:
            if not ctrl:
                v.selected.clear()
        elif ctrl:
            v.selected ^= {key}
        else:
            v.selected = {key}
        self.update()

    def column_menu(self, pos):
        """Hide in Section / Show in Section for the selection when the column under ``pos``
        is part of it, else for that column alone; ``None`` off the columns."""
        from .dock import HIDE_IN_SECTION, NO_ID_TIP, SHOW_IN_SECTION
        v = self.viewer
        point = self.column_at(pos)
        if point is None:
            return None
        key = borehole_key(point)
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        if key is None:
            action = menu.addAction(HIDE_IN_SECTION)
            action.setEnabled(False)
            action.setToolTip(NO_ID_TIP)
            return menu
        keys = set(v.selected) if key in v.selected else {key}
        hidden = v.dock.provider.hidden_keys(v.profile_id) if v.profile_id else set()
        if keys - hidden:
            menu.addAction(HIDE_IN_SECTION).triggered.connect(
                partial(v.set_hidden, sorted(keys - hidden), True))
        if keys & hidden:
            menu.addAction(SHOW_IN_SECTION).triggered.connect(
                partial(v.set_hidden, sorted(keys & hidden), False))
        return menu

    def contextMenuEvent(self, event):
        menu = self.column_menu(QPointF(event.pos()))
        if menu is not None:
            menu.exec(event.globalPos())
            menu.deleteLater()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self._drag is not None and self.transform is not None:
            d = pos - self._drag
            self._drag = pos
            self.transform = self.transform.panned(d.x(), d.y())
            self.update()
            return
        self.viewer.show_readout(self.readout_text(pos.x(), pos.y()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_view()


class BoreholeViewer(QWidget):
    def __init__(self, dock, project, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.dock, self.project = dock, project
        self.profile_id: str | None = None
        self.profile_name = ""
        self.highlight: tuple | None = None
        self.selected: set = set()          # (layer id, borehole id) of selected columns
        self.hidden: set = set()            # ... of the boreholes hidden in the section
        self.items = None
        self.boreholes: list = []
        self.topo = None
        self.mode, self.axis = "true", "elevation"
        self._curve_checks: dict[str, QCheckBox] = {}

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("True distance", "true")
        self.mode_combo.addItem("Even", "even")
        self.axis_combo = QComboBox()
        self.axis_combo.addItem("Elevation", "elevation")
        self.axis_combo.addItem("Depth", "depth")
        self.ve_spin = QDoubleSpinBox()
        self.ve_spin.setRange(AUTO_VE, 100.0)
        self.ve_spin.setSpecialValueText("Auto")     # the minimum: fill the window
        self.ve_spin.setValue(AUTO_VE)
        self.ve_spin.setToolTip(VE_TIP)
        self.ve_spin.setPrefix("VE ")
        self.ve_spin.setSuffix("×")
        from .view_fit import keep_auto_text_whole
        keep_auto_text_whole(self.ve_spin)
        fit_btn = QPushButton("Fit")
        style_btn = QPushButton("Borehole Style…")
        curve_btn = QPushButton("Curve Style…")
        bar = QHBoxLayout()
        for w in (QLabel("Spacing"), self.mode_combo, QLabel("Axis"), self.axis_combo,
                  self.ve_spin, fit_btn):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(style_btn)
        bar.addWidget(curve_btn)

        panel = QWidget()
        side = QVBoxLayout(panel)
        show_box = QGroupBox("Show")
        show_layout = QVBoxLayout(show_box)
        self.show_check = {}
        for key, text, default in SHOW:
            box = QCheckBox(text)
            box.setChecked(default)
            box.toggled.connect(lambda _c: self._redraw(refit=False))
            show_layout.addWidget(box)
            self.show_check[key] = box
        self.show_check["hidden"].setToolTip(
            "Boreholes hidden in this profile's section, drawn faded here. Right-click a "
            "column to hide or show it; Ctrl+click selects several")
        self.show_check["hidden"].toggled.connect(lambda _c: self.refresh())
        side.addWidget(show_box)
        self.curves_box = QGroupBox("Curves")
        self.curves_layout = QVBoxLayout(self.curves_box)
        side.addWidget(self.curves_box)
        label_box = QGroupBox("Labels")
        label_layout = QVBoxLayout(label_box)
        self.label_check = {}
        for key, text, default in LABELS:
            box = QCheckBox(text)
            box.setChecked(default)
            box.toggled.connect(lambda _c: self._redraw(refit=False))
            label_layout.addWidget(box)
            self.label_check[key] = box
        self.font_button = QgsFontButton()
        self.font_button.setMode(QgsFontButton.Mode.ModeTextRenderer)
        fmt = QgsTextFormat()
        fmt.setSize(9)
        self.font_button.setTextFormat(fmt)
        self.font_button.changed.connect(lambda: self._redraw(refit=False))
        font_row = QHBoxLayout()
        font_label = QLabel("Font")
        font_label.setBuddy(self.font_button)
        font_row.addWidget(font_label)
        font_row.addWidget(self.font_button, 1)
        label_layout.addLayout(font_row)
        side.addWidget(label_box)
        # how the section draws the columns: written to the borehole entries, so the
        # section follows (with layer text and the curves ticked above)
        section_box = QGroupBox("On the section")
        section_box.setToolTip("Applies to every borehole entry; layer text and ticked curves "
                               "are drawn on the section too")
        section_form = QFormLayout(section_box)
        self.column_spin = QSpinBox()
        self.column_spin.setRange(*COLUMN_PX_RANGE)
        self.column_spin.setSuffix(" px")
        self.column_spin.setValue(16)
        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setRange(*OPACITY_RANGE)
        self.opacity_spin.setSingleStep(0.1)
        self.opacity_spin.setDecimals(2)
        self.opacity_spin.setValue(1.0)
        section_form.addRow("Column", self.column_spin)
        section_form.addRow("Opacity", self.opacity_spin)
        side.addWidget(section_box)
        side.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        # as wide as its content needs (never cut off, no sideways scrolling); it scrolls
        # only up and down
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(panel.minimumSizeHint().width()
                               + scroll.verticalScrollBar().sizeHint().width() + 4)

        self.canvas = BoreholeCanvas(self)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        middle = QHBoxLayout()
        middle.addWidget(scroll)
        middle.addWidget(self.canvas, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addLayout(middle, 1)
        layout.addWidget(self.status)

        self.load_options()
        self._syncing = False
        self._detached = False
        self._saved_options = json.dumps(self.options())
        self._sync_look()
        self.show_check["text"].toggled.connect(lambda _c: self._look_changed())
        self.column_spin.valueChanged.connect(lambda _v: self._look_changed())
        self.opacity_spin.valueChanged.connect(lambda _v: self._look_changed())
        self.mode_combo.currentIndexChanged.connect(
            lambda _i: self.set_mode(self.mode_combo.currentData()))
        self.axis_combo.currentIndexChanged.connect(
            lambda _i: self.set_axis(self.axis_combo.currentData()))
        self.ve_spin.valueChanged.connect(lambda _v: self._redraw())
        fit_btn.clicked.connect(lambda: self._redraw())
        style_btn.clicked.connect(self._style_menu)
        curve_btn.clicked.connect(self._curve_style)
        dock.profile_changed.connect(self._profile_changed)
        dock.provider.on_change.append(self.refresh)
        geometry = QgsSettings().value(GEOMETRY_KEY)
        if geometry is not None:
            self.restoreGeometry(geometry)
        else:
            self.resize(1000, 640)

    # -- content -------------------------------------------------------------------------------
    def surface_at(self, s: float) -> float | None:
        if self.topo is None or len(self.topo[0]) == 0:
            return None
        return float(np.interp(s, *self.topo))

    def show_profile(self, profile_id: str | None, highlight: tuple | None = None) -> None:
        self.profile_id, self.highlight = profile_id, highlight
        profile = self.dock.current_profile()
        self.profile_name = profile.name if profile is not None and \
            profile.id == profile_id else (profile_id or "")
        self._pull()
        self.setWindowTitle(f"Boreholes – {self.profile_name}")
        self._redraw()

    def refresh(self) -> None:
        """The section's data changed (a restyle, an edit, Context layers Apply)."""
        if self.profile_id is not None:
            self._pull()
            self._redraw(refit=False)

    def _pull(self) -> None:
        provider = self.dock.provider
        show_hidden = self.show_check["hidden"].isChecked()
        self.items = provider.context(self.profile_id, include_hidden=show_hidden) \
            if self.profile_id else None
        self.hidden = provider.hidden_keys(self.profile_id) if self.profile_id else set()
        # a local section's surface is no height: boreholes without a collar stay unhung
        self.topo = provider.topography(self.profile_id) \
            if self.profile_id and not provider.is_local(self.profile_id) else None
        self.boreholes = sorted((p for p in (self.items.points if self.items else [])
                                 if p.kind == "borehole"), key=lambda p: p.s)
        self.canvas.column_rects = []         # the last paint was of other data: its
        self.canvas.dropped_labels = []       # notes go with it
        self._sync_look()

    def is_hidden(self, point) -> bool:
        return borehole_key(point) in self.hidden

    def set_hidden(self, keys, hidden: bool, *_args) -> None:
        """Hide or show boreholes in this profile's section, on the panel's undo stack (as
        the section's right-click); the viewer follows (refresh)."""
        if self.profile_id is not None:
            keys = list(keys)
            message = (f"{len(keys)} borehole(s) hidden in this section" if hidden
                       else f"{len(keys)} borehole(s) shown again")
            self.dock._set_hidden(keys, hidden, message)

    # -- the look shared with the section (kept in the borehole entries) ------------------
    def _entries(self):
        from ..ui.context_dialog import read_settings
        return read_settings(self.project)

    def _sync_look(self) -> None:
        """Switches from the borehole entries (the section's settings)."""
        settings = self._entries()
        self._syncing = True
        try:
            entries = settings.boreholes
            self.show_check["text"].setChecked(any(b.layer_text for b in entries))
            if entries:
                self.column_spin.setValue(int(entries[0].column_px))
                self.opacity_spin.setValue(float(entries[0].opacity))
            self._rebuild_curves({k for b in entries for k in b.section_curves})
        finally:
            self._syncing = False

    def _look_changed(self) -> None:
        """Layer text, curves, width or opacity changed here: the section follows."""
        if self._syncing:
            self._redraw(refit=False)
            return
        from ..ui.context_dialog import write_settings
        settings = self._entries()
        from .context_layers import borehole_views
        chosen = self.chosen_curves()
        shown = set(self._curve_checks)           # curves of this profile (others are kept)
        for b in settings.boreholes:
            prefixes = tuple(f"{t.layer_id}:" for t in b.curve_tables)
            b.layer_text = self.show_check["text"].isChecked()
            b.column_px = self.column_spin.value()
            b.opacity = round(self.opacity_spin.value(), 2)
            b.section_curves = [k for k in b.section_curves if k not in shown] + [
                k for k in chosen if k.startswith(prefixes)]
        write_settings(self.project, settings)
        self.dock.provider.set_borehole_views(borehole_views(settings))
        self._redraw(refit=False)

    def curve_check(self, key: str):
        return self._curve_checks.get(key)

    def _rebuild_curves(self, keep: set) -> None:
        for box in self._curve_checks.values():
            self.curves_layout.removeWidget(box)
            box.deleteLater()
        self._curve_checks = {}
        seen = {}
        for p in self.boreholes:
            for c in p.curves:
                seen.setdefault(c.key, f"{c.name} {c.unit}".strip())
        for key, text in seen.items():
            box = QCheckBox(text)
            box.setChecked(key in keep)
            box.toggled.connect(lambda _c: self._look_changed())
            self.curves_layout.addWidget(box)
            self._curve_checks[key] = box
        self.curves_box.setVisible(bool(seen))

    def chosen_curves(self) -> list[str]:
        return [k for k, box in self._curve_checks.items() if box.isChecked()]

    def curve_ranges(self, keys) -> dict:
        styles = self.items.curve_styles if self.items is not None else {}
        out = {}
        for key in keys:
            style = styles.get(key)
            rng = data_range([c for p in self.boreholes for c in p.curves if c.key == key],
                             bool(style and style.log))
            if rng is not None:
                out[key] = rng
        return out

    def _profile_changed(self, profile_id) -> None:
        if profile_id:
            self.show_profile(profile_id, None)

    # -- modes ---------------------------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        self.mode = mode
        self.mode_combo.blockSignals(True)
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(mode)))
        self.mode_combo.blockSignals(False)
        self.ve_spin.setEnabled(mode == "true")
        self._redraw()

    def set_axis(self, axis: str) -> None:
        self.axis = axis
        self.axis_combo.blockSignals(True)
        self.axis_combo.setCurrentIndex(max(0, self.axis_combo.findData(axis)))
        self.axis_combo.blockSignals(False)
        self._redraw()

    def is_auto_ve(self) -> bool:
        return self.ve_spin.value() <= self.ve_spin.minimum()

    def show_auto_ve(self, ve: float) -> None:
        """The box itself says what Auto chose."""
        from ..core.numbers import fmt_trim
        self.ve_spin.setSpecialValueText(f"Auto ({fmt_trim(ve, 1)}×)")
        self.ve_spin.setToolTip(f"Vertical exaggeration: Auto, now {fmt_trim(ve, 1)}× (fills "
                                "the window)")

    def view_changed(self) -> None:
        """A zoom: a typed VE follows it; Auto stays Auto (the corner shows the VE now)."""
        if self.mode == "true" and self.canvas.transform is not None and not self.is_auto_ve():
            self.ve_spin.blockSignals(True)
            self.ve_spin.setValue(vertical_exaggeration(self.canvas.transform))
            self.ve_spin.blockSignals(False)

    def _redraw(self, refit: bool = True) -> None:
        self._save_if_changed()
        if refit or self.canvas.transform is None:
            self.canvas.fit_view()
        self.show_readout([])
        self.canvas.update()

    def notes(self) -> list[str]:
        """What the status line says besides the hover readout: boreholes without a height,
        columns out of view (even spacing), labels left out for want of room."""
        out = []
        missing = [p.label for p in self.boreholes
                   if self.axis == "elevation" and self.canvas._z_top(p) is None]
        if missing:
            out.append(f"No height: {', '.join(missing)} (shown in depth mode)")
        left, right = self.canvas.off_view()
        if right:
            out.append("1 more borehole to the right (drag to see it)" if right == 1 else
                       f"{right} more boreholes to the right (drag to see them)")
        if left:
            out.append("1 more borehole to the left" if left == 1 else
                       f"{left} more boreholes to the left")
        if self.canvas.dropped_labels:
            out.append(f"Labels left out: {', '.join(self.canvas.dropped_labels)}")
        return out

    def show_readout(self, lines: list[str]) -> None:
        self._readout = list(lines)
        self.update_notes()

    def update_notes(self) -> None:
        """The status line: the hover readout, then the notes (set only when it changed)."""
        parts = ([" · ".join(self._readout)] if getattr(self, "_readout", None) else [])
        text = "    ".join(parts + self.notes())
        if self.status.text() != text:
            self.status.setText(text)

    # -- styles --------------------------------------------------------------------------------
    def _style_menu(self) -> None:
        from ..ui.context_dialog import read_settings
        entries = [(i, b) for i, b in enumerate(read_settings(self.project).boreholes)
                   if b.log_layer_id]
        if not entries:
            self.status.setText("No borehole entry has an interval table (Context Layers…).")
            return
        if len(entries) == 1:
            self.open_style(*entries[0])
            return
        menu = QMenu(self)
        for i, b in entries:
            layer = self.project.mapLayer(b.log_layer_id)
            menu.addAction(layer.name() if layer else b.log_layer_id,
                           lambda i=i, b=b: self.open_style(i, b))
        menu.exec(self.cursor().pos())

    def open_style(self, index: int, entry) -> None:
        from ..ui.borehole_style_dialog import BoreholeStyleDialog
        ids = [p.label for p in self.boreholes if p.entry == index]
        try:
            dlg = BoreholeStyleDialog(self.project, entry, ids, self.dock.provider.notify_changed,
                                      self, self.profile_name)
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        dlg.exec()
        dlg.deleteLater()

    def _curve_style(self) -> None:
        from ..ui.curve_style_dialog import CurveStyleDialog
        names = {}
        for p in self.boreholes:
            for c in p.curves:
                names.setdefault(c.key, f"{c.name} {c.unit}".strip())
        if not names:
            self.status.setText("No curves for these boreholes (Context Layers…).")
            return
        dlg = CurveStyleDialog(self.project, names, self.dock.provider.notify_changed, self)
        dlg.exec()
        dlg.deleteLater()

    # -- options -------------------------------------------------------------------------------
    def options(self) -> dict:
        return {"mode": self.mode, "axis": self.axis, "ve": self.ve_spin.value(),
                "show": {k: b.isChecked() for k, b in self.show_check.items()},
                "labels": {k: b.isChecked() for k, b in self.label_check.items()},
                "font": self.font_button.textFormat().toQFont().toString(),
                "font_size": self.font_button.textFormat().size(),
                "font_colour": self.font_button.textFormat().color().name()}

    def save_options(self) -> None:
        text = json.dumps(self.options())
        self.project.writeEntry(SCOPE, OPTIONS_KEY, text)
        self._saved_options = text

    def _save_if_changed(self) -> None:
        """Options go into the project when they change (not on close: by then the project
        may already be cleared or another one loaded)."""
        if getattr(self, "_detached", True) or not hasattr(self, "_saved_options"):
            return
        if json.dumps(self.options()) != self._saved_options:
            self.save_options()

    def load_options(self) -> None:
        text, ok = self.project.readEntry(SCOPE, OPTIONS_KEY, "")
        try:
            data = json.loads(text) if ok and text else {}
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        mode = data.get("mode") if data.get("mode") in ("true", "even") else "true"
        axis = data.get("axis") if data.get("axis") in ("elevation", "depth") else "elevation"
        self.mode, self.axis = mode, axis
        self.mode_combo.setCurrentIndex(max(0, self.mode_combo.findData(mode)))
        self.axis_combo.setCurrentIndex(max(0, self.axis_combo.findData(axis)))
        self.ve_spin.setEnabled(mode == "true")
        if isinstance(data.get("ve"), (int, float)):
            self.ve_spin.setValue(float(data["ve"]))
        for group, checks in (("show", self.show_check), ("labels", self.label_check)):
            for key, value in (data.get(group) or {}).items():
                if key in checks and isinstance(value, bool):
                    checks[key].setChecked(value)
        if isinstance(data.get("font"), str):
            fmt = self.font_button.textFormat()
            font = QFont()
            if font.fromString(data["font"]):
                fmt.setFont(font)
            if isinstance(data.get("font_size"), (int, float)):
                fmt.setSize(float(data["font_size"]))
            if isinstance(data.get("font_colour"), str):
                fmt.setColor(QColor(data["font_colour"]))
            self.font_button.setTextFormat(fmt)

    def closeEvent(self, event):
        QgsSettings().setValue(GEOMETRY_KEY, self.saveGeometry())
        super().closeEvent(event)

    def detach(self) -> None:
        """Stop following the section (the plugin unloads or the project changes)."""
        self._detached = True
        try:
            self.dock.profile_changed.disconnect(self._profile_changed)
        except (TypeError, RuntimeError):
            pass
        if self.refresh in self.dock.provider.on_change:
            self.dock.provider.on_change.remove(self.refresh)


def choose_viewer_labels(spans, highlight=None, rows: int = 1) -> list:
    """Row (0 = nearest the columns) of each column label, or None when there is no room:
    ``spans`` are their (x0, x1); the clicked column first, then left to right
    (``context_render.place_labels``)."""
    from .context_render import place_labels
    return place_labels([(a, b, 0 if i == highlight else 1)
                         for i, (a, b) in enumerate(spans)], rows)


def tick_text(value: float) -> str:
    """An axis tick in QGIS's locale ("0,5", "180")."""
    from ..core.numbers import fmt_trim
    return fmt_trim(value, 3)
