"""Layer list of the section panel: visibility, opacity and colour scale per dataset, and
a context menu to remove a dataset from its profile."""
from __future__ import annotations

from dataclasses import replace

from qgis.PyQt.QtCore import QSize, Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QCheckBox, QFrame, QHBoxLayout, QLabel, QMenu, QMessageBox,
                                 QScrollArea, QSizePolicy, QSlider, QSplitter, QToolButton,
                                 QVBoxLayout, QWidget)

from ..core.dataset_types import type_label
from .data import SectionLayer, layer_name
from .readout import format_value, unit_label
from .scale_dialog import DisplayDialog, ramp_icon

MIN_WIDTH = 240
MAX_HINT_WIDTH = 300            # preferred width: full layer names, up to this (the section gets the room)
MIN_NAME_WIDTH = 60             # a long name is cut (full name in the tooltip), not the controls
REMOVE_TEXT = "Remove from profile…"
#: style fields the Display dialog edits
DISPLAY_FIELDS = ("scale", "mode", "contour_step", "contour_major", "contour_minor",
                  "grid_cell", "interpolation", "fade_coverage", "coverage_threshold",
                  "fade_mode", "shown")
DISPLAY_TEXT = "Display…"
MISFIT_TEXT = "Misfit summary…"
INFO_TEXT = "Dataset info…"
APPLY_ALL_TEXT = "Apply Style to All Sections"
APPLY_ALL_TIP = ("Give every other {what} of the project this model's colours, display "
                 "and contours (shown or hidden stays as it is)")
APPLY_ALL_OFF_TIP = "There is no other {what} in the project to apply this style to"


def _scale_text(layer: SectionLayer) -> str:
    scale = layer.style.scale
    if scale is None:
        return "Scale…"
    log = " log" if scale.log else ""
    return f"{format_value(scale.vmin)}–{format_value(scale.vmax)}{log}"


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


class _LayerRow(QWidget):
    def __init__(self, layer: SectionLayer, owner: "LayerList"):
        super().__init__()
        self.dataset_id = layer.dataset.id
        self._owner = owner
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
        self.scale_button = QToolButton()
        self.scale_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.scale_button.setIconSize(QSize(40, 10))
        self.scale_button.setToolTip("Colour scale and display (cells, smooth, contours, coverage)")
        self.scale_button.clicked.connect(lambda: owner.edit_scale(self.dataset_id))
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: _exec_once(owner.row_menu(self.dataset_id), self.mapToGlobal(pos)))
        for child in (self.check, self.opacity, self.scale_button):     # menu on the controls too
            child.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        row = QHBoxLayout(self)
        row.setContentsMargins(2, 1, 2, 1)
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
        self.scale_button.setText(_scale_text(layer))
        if style.scale is not None:
            self.scale_button.setIcon(ramp_icon(style.scale, 40, 10))
        d = layer.dataset
        tip = f"{layer_name(d)} (version {d.version})\n{type_label(d.kind)}\n{d.source_path}"
        self.check.setToolTip(tip if ok else f"{tip}\n\n{layer.error}")
        self.check.setStyleSheet("" if ok else "color: #c00000;")

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
        self._empty.setVisible(not ids)
        self._fit_width()

    def _fit_width(self) -> None:
        """Wide enough for every row's controls (the list never scrolls sideways)."""
        rows = list(self._rows.values())
        extra = (self.layout().contentsMargins().left() + self.layout().contentsMargins().right()
                 + self._scroll.verticalScrollBar().sizeHint().width() + 4)
        need = max([r.minimumSizeHint().width() for r in rows], default=0) + extra
        full = max([r.minimumSizeHint().width() - r.check.minimumWidth()
                    + r.check.sizeHint().width() for r in rows], default=0) + extra
        self.setMinimumWidth(max(MIN_WIDTH, need))
        self._hint_width = max(self.minimumWidth(), min(full, MAX_HINT_WIDTH))
        self.updateGeometry()
        self._grow_in_splitter()

    def _grow_in_splitter(self) -> None:
        """A splitter reads size hints only when first shown: widen this list to its hint
        by taking space from the widest neighbour. Never shrinks (the user may have
        dragged the handle)."""
        splitter = self.parentWidget()
        if not isinstance(splitter, QSplitter):
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
        menu.addAction(DISPLAY_TEXT).triggered.connect(lambda: self.edit_scale(dataset_id))
        layer = self._layers.get(dataset_id)
        readings = None if layer is None or layer.mesh is None else layer.mesh.readings
        if readings is not None and readings.has_calculated:
            menu.addAction(MISFIT_TEXT).triggered.connect(
                lambda: self.show_misfit(dataset_id))
        menu.addAction(INFO_TEXT).triggered.connect(lambda: self.edit_info(dataset_id))
        menu.addSeparator()
        self._add_apply_all(menu, dataset_id)
        menu.addSeparator()
        menu.addAction(REMOVE_TEXT).triggered.connect(lambda: self.remove_dataset(dataset_id))
        return menu

    def _add_apply_all(self, menu: QMenu, dataset_id: str) -> None:
        from ..core.dataset_types import type_label
        from .style_store import same_method
        targets = same_method(self.provider.store, dataset_id) if self.provider else []
        layer = self._layers.get(dataset_id)
        what = type_label(layer.dataset.kind) if layer is not None else "model"
        action = menu.addAction(APPLY_ALL_TEXT)
        action.setEnabled(bool(targets))
        action.setToolTip((APPLY_ALL_TIP if targets else APPLY_ALL_OFF_TIP).format(what=what))
        menu.setToolTipsVisible(True)
        action.triggered.connect(lambda: self.apply_all_requested.emit(dataset_id))

    def edit_info(self, dataset_id: str) -> None:
        """Dataset info…: method, array, spacing, inversion, reference (for provenance)."""
        from ..ui.dataset_info_dialog import DatasetInfoDialog
        if self.provider is None:
            return
        dlg = DatasetInfoDialog(self.provider.store, dataset_id, self)
        dlg.exec()
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
