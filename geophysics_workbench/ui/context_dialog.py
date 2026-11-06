"""'Context layers' dialog: which ordinary QGIS layers supply crossing lines,
points, boreholes with a log table, the surface geology band and the DEM on a section.

The choice is kept in the QGIS project as JSON (entry ``geophysics_workbench/context``)
because it refers to QGIS layer ids. ``read_settings`` / ``write_settings`` need no widgets."""
from __future__ import annotations

from qgis.core import QgsMapLayer, QgsProject, QgsVectorLayer, QgsWkbTypes
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                                 QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QLabel,
                                 QScrollArea, QVBoxLayout, QWidget)

from ..core.context_settings import (MAX_DISTANCE, BandSetting, ContextSettings,
                                     PointLayerSetting)
from .borehole_mapping import (MISSING, NONE, BoreholeEntries, field_of, fill_field_combo,
                               fill_layer_combo, keep_missing)
from .crossing_rows import CrossingLinesGroup
from .project_actions import SCOPE

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

        content = QWidget()
        outer = QVBoxLayout(content)
        self.lines = CrossingLinesGroup(self.project, exclude)
        outer.addWidget(self.lines)
        self.point_rows, box = self._layer_group(
            "Points near the line", [lyr for lyr in by_geom["point"] if lyr.id() not in exclude])
        outer.addWidget(box)
        self.boreholes = BoreholeEntries(self.project, vectors, by_geom["point"],
                                         current_boreholes, self.applied.emit)
        borehole_box = QGroupBox("Boreholes")
        QVBoxLayout(borehole_box).addWidget(self.boreholes)
        outer.addWidget(borehole_box)

        self.band_combo, self.band_label = QComboBox(), QComboBox()
        fill_layer_combo(self.band_combo, by_geom["polygon"])
        self.band_combo.currentIndexChanged.connect(lambda _i: self._band_layer_changed())
        band_box = QGroupBox("Surface geology band")
        form = QFormLayout(band_box)
        form.addRow("Polygon layer", self.band_combo)
        form.addRow("Label field", self.band_label)
        outer.addWidget(band_box)
        self._band_layer_changed()

        self.dem_combo = QComboBox()
        fill_layer_combo(self.dem_combo, rasters)
        dem_box = QGroupBox("DEM")
        QFormLayout(dem_box).addRow("Raster layer", self.dem_combo)
        outer.addWidget(dem_box)

        self.buffer_spin = _spin(0, MAX_DISTANCE, 25.0)
        self.near_miss_spin = _spin(0, MAX_DISTANCE, 10.0)
        self.dem_tolerance_spin = _spin(0, MAX_DISTANCE, 1.0)
        values = QFormLayout()
        values.addRow("Buffer (m)", self.buffer_spin)
        values.addRow("Near-miss ties within (m)", self.near_miss_spin)
        values.addRow("DEM vs station height tolerance (m)", self.dem_tolerance_spin)
        outer.addLayout(values)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Apply
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.apply_button.clicked.connect(lambda _checked=False: self.apply())
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(buttons)
        self.resize(640, 720)
        self.note = QLabel()
        self.note.setStyleSheet("color: grey;")
        layout.insertWidget(1, self.note)
        self.stale_points, self.loaded_band = [], None
        self._load(read_settings(self.project))

    def _layer_group(self, title, layers):
        box = QGroupBox(title)
        grid = QGridLayout(box)
        rows = {}
        for i, layer in enumerate(layers):
            rows[layer.id()] = LayerRow(layer, grid, i)
        if not rows:
            grid.addWidget(QLabel("No matching layers in this project."), 0, 0)
        return rows, box

    def _band_layer_changed(self):
        layer = self.project.mapLayer(self.band_combo.currentData() or "")
        fill_field_combo(self.band_label, layer)

    # -- selection (also used by tests) ----------------------------------------------------
    def select_band(self, layer_id: str, label_field: str = "") -> None:
        self.band_combo.setCurrentIndex(max(0, self.band_combo.findData(layer_id)))
        self.band_label.setCurrentIndex(max(0, self.band_label.findData(label_field)))

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
        self.loaded_band = s.band
        if s.band is not None:
            keep_missing(self.band_combo, self.project, s.band.layer_id)
            self.select_band(s.band.layer_id, s.band.label_field)
        keep_missing(self.dem_combo, self.project, s.dem_layer_id)
        self.select_dem(s.dem_layer_id)
        missing = (self.lines.stale_count() + len(self.stale_points) + self.boreholes.missing_count()
                   + sum(c.currentText() == MISSING for c in (self.band_combo, self.dem_combo)))
        self.note.setText(f"{missing} saved layer(s) are not in this project; "
                          "their settings are kept." if missing else "")
        self.buffer_spin.setValue(s.buffer)
        self.near_miss_spin.setValue(s.near_miss)
        self.dem_tolerance_spin.setValue(s.dem_tolerance)

    def settings(self) -> ContextSettings:
        band_id = self.band_combo.currentData() or ""
        band_label = field_of(self.band_label)
        old = self.loaded_band
        if (old is not None and old.layer_id == band_id
                and self.project.mapLayer(band_id) is None):
            band_label = old.label_field                # layer missing: keep its saved label
        return ContextSettings(
            line_layers=self.lines.settings(),
            point_layers=[PointLayerSetting(r.layer_id, field_of(r.label), field_of(r.depth))
                          for r in self.point_rows.values() if r.check.isChecked()]
            + list(self.stale_points),
            boreholes=self.boreholes.entries(),
            band=BandSetting(band_id, band_label) if band_id else None,
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
        super().done(result)
