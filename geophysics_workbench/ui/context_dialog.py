"""'Context layers' dialog: which ordinary QGIS layers supply crossing lines (powerline),
points, boreholes with a log table, the surface geology band and the DEM on a section.

The choice is kept in the QGIS project as JSON (entry ``geophysics_workbench/context``)
because it refers to QGIS layer ids. ``read_settings`` / ``write_settings`` need no widgets."""
from __future__ import annotations

from qgis.core import QgsMapLayer, QgsProject, QgsVectorLayer, QgsWkbTypes
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                                 QDoubleSpinBox, QFormLayout, QGridLayout, QGroupBox, QLabel,
                                 QScrollArea, QVBoxLayout, QWidget)

from ..core.context_settings import (BandSetting, ContextSettings, LineLayerSetting,
                                     PointLayerSetting)
from .borehole_mapping import BoreholeGroup, field_of, fill_field_combo, fill_layer_combo
from .project_actions import SCOPE

KEY = "context"
POWER_WORDS = ("power", "strom", "kv")


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


def looks_like_powerline(layer) -> bool:
    names = [layer.name()] + layer.fields().names()
    return any(word in name.lower() for name in names for word in POWER_WORDS)


class LayerRow:
    """One checkable layer with a label-field combo (and optionally a 'Powerline' box)."""

    def __init__(self, layer, grid: QGridLayout, row: int, powerline: bool = False):
        self.layer_id = layer.id()
        self.check = QCheckBox(layer.name())
        self.label = QComboBox()
        fill_field_combo(self.label, layer)
        grid.addWidget(self.check, row, 0)
        grid.addWidget(self.label, row, 1)
        self.powerline = None
        if powerline:
            self.powerline = QCheckBox("Powerline")
            self.powerline.setChecked(looks_like_powerline(layer))
            grid.addWidget(self.powerline, row, 2)

    def load(self, label_field: str, powerline: bool | None = None):
        self.check.setChecked(True)
        self.label.setCurrentIndex(max(0, self.label.findData(label_field)))
        if self.powerline is not None and powerline is not None:
            self.powerline.setChecked(powerline)


def _spin(lo, hi, value, decimals=1) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setDecimals(decimals)
    box.setValue(value)
    return box


class ContextDialog(QDialog):
    def __init__(self, iface, project: QgsProject | None = None, parent=None):
        super().__init__(parent if parent is not None else iface.mainWindow())
        self.setWindowTitle("Context layers")
        self.iface = iface
        self.project = project if project is not None else QgsProject.instance()
        layers = sorted(self.project.mapLayers().values(), key=lambda lyr: lyr.name().lower())
        vectors = [lyr for lyr in layers if isinstance(lyr, QgsVectorLayer)]
        by_geom = {kind: [lyr for lyr in vectors if _geometry(lyr) == kind]
                   for kind in ("line", "point", "polygon")}
        rasters = [lyr for lyr in layers if lyr.type() == QgsMapLayer.LayerType.RasterLayer]

        content = QWidget()
        outer = QVBoxLayout(content)
        self.line_rows, box = self._layer_group("Crossing lines", by_geom["line"], True)
        outer.addWidget(box)
        self.point_rows, box = self._layer_group("Points near the line", by_geom["point"], False)
        outer.addWidget(box)
        self.borehole = BoreholeGroup(self.project, vectors, by_geom["point"])
        outer.addWidget(self.borehole)

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

        self.buffer_spin = _spin(0, 10000, 25.0)
        self.near_miss_spin = _spin(0, 10000, 10.0)
        self.dem_tolerance_spin = _spin(0, 1000, 1.0)
        values = QFormLayout()
        values.addRow("Buffer (m)", self.buffer_spin)
        values.addRow("Near-miss ties within (m)", self.near_miss_spin)
        values.addRow("DEM vs station height tolerance (m)", self.dem_tolerance_spin)
        outer.addLayout(values)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(scroll)
        layout.addWidget(buttons)
        self.resize(640, 720)
        self._load(read_settings(self.project))

    def _layer_group(self, title, layers, powerline):
        box = QGroupBox(title)
        grid = QGridLayout(box)
        rows = {}
        for i, layer in enumerate(layers):
            rows[layer.id()] = LayerRow(layer, grid, i, powerline)
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

    def select_dem(self, layer_id: str) -> None:
        self.dem_combo.setCurrentIndex(max(0, self.dem_combo.findData(layer_id)))

    def _load(self, s: ContextSettings) -> None:
        for item in s.line_layers:
            if item.layer_id in self.line_rows:
                self.line_rows[item.layer_id].load(item.label_field, item.powerline)
        for item in s.point_layers:
            if item.layer_id in self.point_rows:
                self.point_rows[item.layer_id].load(item.label_field)
        self.borehole.load(s.borehole)
        if s.band is not None:
            self.select_band(s.band.layer_id, s.band.label_field)
        self.select_dem(s.dem_layer_id)
        self.buffer_spin.setValue(s.buffer)
        self.near_miss_spin.setValue(s.near_miss)
        self.dem_tolerance_spin.setValue(s.dem_tolerance)

    def settings(self) -> ContextSettings:
        band_id = self.band_combo.currentData() or ""
        return ContextSettings(
            line_layers=[LineLayerSetting(r.layer_id, field_of(r.label), r.powerline.isChecked())
                         for r in self.line_rows.values() if r.check.isChecked()],
            point_layers=[PointLayerSetting(r.layer_id, field_of(r.label))
                          for r in self.point_rows.values() if r.check.isChecked()],
            borehole=self.borehole.setting(),
            band=BandSetting(band_id, field_of(self.band_label)) if band_id else None,
            dem_layer_id=self.dem_combo.currentData() or "",
            buffer=self.buffer_spin.value(), near_miss=self.near_miss_spin.value(),
            dem_tolerance=self.dem_tolerance_spin.value())

    def accept(self):
        write_settings(self.project, self.settings())
        super().accept()
