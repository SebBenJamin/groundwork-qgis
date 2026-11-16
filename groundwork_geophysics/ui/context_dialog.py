"""'Context layers' dialog: which ordinary QGIS layers supply crossing lines,
points, boreholes with a log table, the surface geology band and the DEM on a section.

The choice is kept in the QGIS project as JSON (project entry ``context`` in the legacy scope, ids.LEGACY_ID)
because it refers to QGIS layer ids. ``read_settings`` / ``write_settings`` need no widgets."""
from __future__ import annotations

from qgis.core import QgsMapLayer, QgsProject, QgsSettings, QgsVectorLayer, QgsWkbTypes
from qgis.PyQt.QtCore import QSize, pyqtSignal
from qgis.PyQt.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                                 QDialogButtonBox, QDoubleSpinBox, QFormLayout, QGridLayout,
                                 QGroupBox, QLabel, QScrollArea, QTabWidget, QVBoxLayout,
                                 QWidget)


def initial_size(available) -> QSize:
    """The dialog's first size: at most 580 px tall (QGIS HIG) and 80 % of the screen."""
    return QSize(min(720, int(available.width() * 0.8)),
                 min(580, int(available.height() * 0.8)))

from ..core.context_settings import MAX_DISTANCE, ContextSettings, PointLayerSetting
from ..ids import LEGACY_ID
from .borehole_mapping import (MISSING, NONE, BoreholeEntries, field_of, fill_field_combo,
                               fill_layer_combo, keep_missing)
from .crossing_rows import CrossingLinesGroup
from .project_actions import SCOPE
from .strip_rows import StripRows

SIZE_KEY = f"{LEGACY_ID}/context_dialog/size"
KEY = "context"


def read_settings(project) -> ContextSettings:
    return ContextSettings.from_json(project.readEntry(SCOPE, KEY, "")[0])


def write_settings(project, settings: ContextSettings) -> None:
    project.writeEntry(SCOPE, KEY, settings.to_json())


def _geometry(layer) -> str:
    """'line', 'point', 'polygon' or 'none' (a non-spatial table)."""
    kind = layer.geometryType()
    if kind == QgsWkbTypes.GeometryType.LineGeometry:
        return "line"
    if kind == QgsWkbTypes.GeometryType.PointGeometry:
        return "point"
    if kind == QgsWkbTypes.GeometryType.PolygonGeometry:
        return "polygon"
    return "none"


class LayerRow:
    """One checkable point layer with a label-field combo and an optional numeric depth
    field (drawn as a stick down to that depth)."""

    def __init__(self, layer, grid: QGridLayout, row: int):
        self.layer_id = layer.id()
        self.check = QCheckBox(layer.name())
        self.label = QComboBox()
        fill_field_combo(self.label, layer)
        self.depth = QComboBox()
        self.depth.setToolTip("Depth field: draw the point as a stick down to this depth (m)")
        self.depth.addItem(NONE, "")
        for f in layer.fields():
            if f.isNumeric():
                self.depth.addItem(f.name(), f.name())
        grid.addWidget(self.check, row, 0)
        grid.addWidget(self.label, row, 1)
        grid.addWidget(self.depth, row, 2)

    def load(self, label_field: str, depth_field: str = ""):
        self.check.setChecked(True)
        self.label.setCurrentIndex(max(0, self.label.findData(label_field)))
        self.depth.setCurrentIndex(max(0, self.depth.findData(depth_field)))


def _spin(lo, hi, value, decimals=1) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setDecimals(decimals)
    box.setValue(value)
    return box


class ContextDialog(QDialog):
    applied = pyqtSignal()                              # settings written (Apply or OK)

    def __init__(self, iface, project: QgsProject | None = None, parent=None,
                 exclude: set[str] = frozenset(),
                 current_boreholes=lambda: ([], "")):
        super().__init__(parent if parent is not None else iface.mainWindow())
        self.setWindowTitle("Context layers")
        self.iface = iface
        self.project = project if project is not None else QgsProject.instance()
        layers = sorted(self.project.mapLayers().values(), key=lambda lyr: lyr.name().lower())
        vectors = [lyr for lyr in layers if isinstance(lyr, QgsVectorLayer)]
        by_geom = {kind: [lyr for lyr in vectors if _geometry(lyr) == kind]
                   for kind in ("point", "polygon")}
        rasters = [lyr for lyr in layers if lyr.type() == QgsMapLayer.LayerType.RasterLayer]

        self.buffer_spin = _spin(0, MAX_DISTANCE, 25.0)
        self.near_miss_spin = _spin(0, MAX_DISTANCE, 10.0)
        self.dem_tolerance_spin = _spin(0, MAX_DISTANCE, 1.0)
        self.tabs = QTabWidget()

        # Lines: crossing line layers, and how near two profiles must pass to be tied
        self.lines = CrossingLinesGroup(self.project, exclude)
        ties = QFormLayout()
        ties.addRow("Tie profiles that pass within (m)", self.near_miss_spin)
        self._add_tab("Lines", [self.lines], ties)

        # Points: point layers near the line, with column headers
        self.point_rows, box = self._layer_group(
            "Points Near the Line", [lyr for lyr in by_geom["point"] if lyr.id() not in exclude])
        self._add_tab("Points", [box])

        self.boreholes = BoreholeEntries(self.project, vectors, by_geom["point"],
                                         current_boreholes, self.applied.emit)
        self._add_tab("Boreholes", [self.boreholes])

        self.strips = StripRows(self.project, by_geom["polygon"])
        self.dem_combo = QComboBox()
        fill_layer_combo(self.dem_combo, rasters)
        dem_box = QGroupBox("DEM")
        dem_form = QFormLayout(dem_box)
        dem_form.addRow("Raster layer", self.dem_combo)
        dem_form.addRow("Warn when station and DEM heights differ by more than (m)",
                        self.dem_tolerance_spin)
        self._add_tab("Band and DEM", [self.strips, dem_box])

        # applies to points and boreholes: below the tabs
        common = QFormLayout()
        common.addRow("Search distance from the line (m)", self.buffer_spin)
        self.buffer_spin.setToolTip("Points and boreholes this close to the profile line are "
                                    "drawn on the section")

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Apply
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.clicked.connect(lambda _checked=False: self.apply())
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs, 1)
        layout.addLayout(common)
        layout.addWidget(buttons)
        saved = QgsSettings().value(SIZE_KEY)
        screen = self.screen() or QApplication.primaryScreen()
        size = initial_size(screen.availableGeometry())
        if isinstance(saved, QSize) and saved.isValid():
            size = saved.boundedTo(screen.availableGeometry().size())
        self.resize(size)
        self.note = QLabel()
        self.note.setStyleSheet("color: grey;")
        layout.insertWidget(1, self.note)
        self.stale_points = []
        self._load(read_settings(self.project))

    def _add_tab(self, title: str, widgets: list, form=None) -> None:
        """A tab whose content scrolls (never taller than the dialog)."""
        page = QWidget()
        lay = QVBoxLayout(page)
        for w in widgets:
            lay.addWidget(w)
        if form is not None:
            lay.addLayout(form)
        lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, title)

    def _layer_group(self, title, layers):
        box = QGroupBox(title)
        grid = QGridLayout(box)
        rows = {}
        if layers:
            for col, text in enumerate(("Layer", "Label field", "Depth field")):
                head = QLabel(text)
                font = head.font()
                font.setBold(True)
                head.setFont(font)
                grid.addWidget(head, 0, col)
        for i, layer in enumerate(layers):
            rows[layer.id()] = LayerRow(layer, grid, i + 1)
        if not rows:
            grid.addWidget(QLabel("No point layers in this project."), 0, 0)
        return rows, box

    @property
    def borehole(self):
        """The borehole entry being edited."""
        return self.boreholes.current()

    def select_dem(self, layer_id: str) -> None:
        self.dem_combo.setCurrentIndex(max(0, self.dem_combo.findData(layer_id)))

    def _load(self, s: ContextSettings) -> None:
        self.lines.load(s.line_layers)
        for item in s.point_layers:
            if item.layer_id in self.point_rows:
                self.point_rows[item.layer_id].load(item.label_field, item.depth_field)
        self.stale_points = [i for i in s.point_layers if i.layer_id not in self.point_rows]
        self.boreholes.load(s.boreholes)
        self.strips.load(s.bands)
        keep_missing(self.dem_combo, self.project, s.dem_layer_id)
        self.select_dem(s.dem_layer_id)
        missing = (self.lines.stale_count() + len(self.stale_points) + self.boreholes.missing_count()
                   + self.strips.missing_count() + (self.dem_combo.currentText() == MISSING))
        self.note.setText(f"{missing} saved layer(s) are not in this project; "
                          "their settings are kept." if missing else "")
        self.buffer_spin.setValue(s.buffer)
        self.near_miss_spin.setValue(s.near_miss)
        self.dem_tolerance_spin.setValue(s.dem_tolerance)

    def settings(self) -> ContextSettings:
        return ContextSettings(
            line_layers=self.lines.settings(),
            point_layers=[PointLayerSetting(r.layer_id, field_of(r.label), field_of(r.depth))
                          for r in self.point_rows.values() if r.check.isChecked()]
            + list(self.stale_points),
            boreholes=self.boreholes.entries(),
            bands=self.strips.settings(),
            dem_layer_id=self.dem_combo.currentData() or "",
            buffer=self.buffer_spin.value(), near_miss=self.near_miss_spin.value(),
            dem_tolerance=self.dem_tolerance_spin.value())

    def apply(self) -> None:
        write_settings(self.project, self.settings())
        self.applied.emit()

    def accept(self):
        self.apply()
        super().accept()

    def done(self, result):
        self.lines.detach()                             # a deleted dialog must get no signals
        QgsSettings().setValue(SIZE_KEY, self.size())    # opens at the user's size next time
        super().done(result)
