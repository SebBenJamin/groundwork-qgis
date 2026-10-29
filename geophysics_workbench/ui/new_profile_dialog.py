"""'New profile' dialog: from a station file, a selected line feature or two points.

Coordinates typed or picked here are in the workbench project's CRS. The dialog is meant
to be shown non-modally (``show()``), so "Pick on map" can use the map canvas; it hides
itself while picking and comes back after the second click.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry,
                       QgsProject, QgsVectorLayer, QgsWkbTypes)
from qgis.gui import QgsMapToolEmitPoint
from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                                 QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                                 QMessageBox, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from ..core.model import profile_from_line, profile_from_stations
from ..readers.textcols import read_columns
from .project_actions import add_profile

TAB_FILE, TAB_LINE, TAB_POINTS = 0, 1, 2
METHODS = [("ERT", "ert")]
NONE = -1                                   # "(none)" entry of the optional column combos
_HEADER_NAMES = {
    "number": {"nr", "no", "num", "number", "electrode", "elektrode", "station", "id"},
    "x": {"x", "east", "easting", "rechts", "rechtswert", "e"},
    "y": {"y", "north", "northing", "hoch", "hochwert", "n"},
    "z": {"z", "elev", "elevation", "height", "höhe", "hoehe", "alt", "altitude", "h"},
}


def guess_columns(header: list[str] | None, ncols: int) -> dict[str, int]:
    """Column index per role (number, x, y, z) from header names, else by position."""
    if ncols >= 4:
        guess = {"number": 0, "x": 1, "y": 2, "z": 3}
    else:
        guess = {"number": NONE, "x": 0, "y": min(1, ncols - 1), "z": 2 if ncols == 3 else NONE}
    if header:
        for i, token in enumerate(header):
            word = re.sub(r"[^\wäöüß]", "", token.lower())
            for role, names in _HEADER_NAMES.items():
                if word in names:
                    guess[role] = i
    return guess


def _spin(lo: float, hi: float, value: float, decimals: int = 2, suffix: str = "") -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(lo, hi)
    box.setDecimals(decimals)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    return box


class NewProfileDialog(QDialog):
    def __init__(self, iface, store, project: QgsProject | None = None, provider=None,
                 parent=None):
        super().__init__(parent if parent is not None else iface.mainWindow())
        self.setWindowTitle("New profile")
        self.iface, self.store, self.provider = iface, store, provider
        self.project = project if project is not None else QgsProject.instance()
        self.profile = None
        self.last_error = None
        self._columns = None                # (header, array) of the station file
        self.pick_tool = None
        self._picked = []
        self._prev_tool = None
        self._closing = False

        self.name_edit = QLineEdit()
        self.method_combo = QComboBox()
        for label, value in METHODS:
            self.method_combo.addItem(label, value)
        form = QFormLayout()
        form.addRow("Name", self.name_edit)
        form.addRow("Method", self.method_combo)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._file_tab(), "From station file")
        self.tabs.addTab(self._line_tab(), "From selected line feature")
        self.tabs.addTab(self._points_tab(), "From start/end points")
        self.tabs.currentChanged.connect(lambda _i: self._update_line_info())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.tabs)
        layout.addWidget(buttons)
        self._update_line_info()

    # -- tabs --------------------------------------------------------------------------------
    def _file_tab(self) -> QWidget:
        page = QWidget()
        self.file_edit = QLineEdit()
        self.file_edit.editingFinished.connect(lambda: self.set_station_file(self.file_edit.text()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.file_edit)
        row.addWidget(browse)
        self.file_info = QLabel("CSV or text table with one row per electrode.")
        self.file_info.setWordWrap(True)
        self.col_number, self.col_x, self.col_y, self.col_z = (QComboBox() for _ in range(4))
        form = QFormLayout(page)
        form.addRow("File", row)
        form.addRow(self.file_info)
        form.addRow("Electrode number", self.col_number)
        form.addRow("X (easting)", self.col_x)
        form.addRow("Y (northing)", self.col_y)
        form.addRow("Z (elevation)", self.col_z)
        return page

    def _line_tab(self) -> QWidget:
        page = QWidget()
        self.line_info = QLabel()
        self.line_info.setWordWrap(True)
        self.line_spacing = _spin(0.0, 1e4, 5.0, suffix=" m")
        form = QFormLayout(page)
        form.addRow(self.line_info)
        form.addRow("Station spacing", self.line_spacing)
        return page

    def _points_tab(self) -> QWidget:
        page = QWidget()
        self.x1, self.y1, self.x2, self.y2 = (_spin(-1e9, 1e9, 0.0) for _ in range(4))
        self.points_spacing = _spin(0.0, 1e4, 5.0, suffix=" m")
        pick = QPushButton("Pick on map")
        pick.setToolTip("Click the start point, then the end point on the map")
        pick.clicked.connect(self.start_pick)
        form = QFormLayout(page)
        form.addRow(QLabel(f"Coordinates in {self.store.crs_authid}"))
        for label, a, b in (("Start X / Y", self.x1, self.y1), ("End X / Y", self.x2, self.y2)):
            row = QHBoxLayout()
            row.addWidget(a)
            row.addWidget(b)
            form.addRow(label, row)
        form.addRow("", pick)
        form.addRow("Station spacing", self.points_spacing)
        return page

    # -- station file ------------------------------------------------------------------------
    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "Station file", "",
                                              "Text tables (*.csv *.txt *.dat);;All files (*)")
        if path:
            self.set_station_file(path)

    def set_station_file(self, path) -> None:
        path = str(path)
        self.file_edit.setText(path)
        combos = (self.col_number, self.col_x, self.col_y, self.col_z)
        for combo in combos:
            combo.clear()
        self._columns = None
        if not path:
            return
        try:
            header, arr = read_columns(Path(path))
        except FileNotFoundError:
            self.file_info.setText(f"File not found: {path}")
            return
        except (ValueError, OSError) as exc:
            self.file_info.setText(str(exc))
            return
        self._columns = (header, arr)
        names = header if header and len(header) == arr.shape[1] else \
            [f"column {i + 1}" for i in range(arr.shape[1])]
        guess = guess_columns(header, arr.shape[1])
        for combo, role, optional in ((self.col_number, "number", True), (self.col_x, "x", False),
                                      (self.col_y, "y", False), (self.col_z, "z", True)):
            if optional:
                combo.addItem("(none)", NONE)
            for i, name in enumerate(names):
                combo.addItem(name, i)
            combo.setCurrentIndex(max(0, combo.findData(guess[role])))
        self.file_info.setText(f"{arr.shape[0]} rows, {arr.shape[1]} columns")
        if not self.name_edit.text():
            self.name_edit.setText(Path(path).stem)

    def _from_file(self, name: str, method: str):
        if self._columns is None:
            raise ValueError("Choose a readable station file")
        arr = self._columns[1]
        cx, cy = self.col_x.currentData(), self.col_y.currentData()
        cn, cz = self.col_number.currentData(), self.col_z.currentData()
        if cx is None or cy is None or cx == cy:
            raise ValueError("Choose two different columns for X and Y")
        z = arr[:, cz] if cz not in (None, NONE) else np.full(len(arr), np.nan)
        xyz = np.column_stack([arr[:, cx], arr[:, cy], z])
        numbers = None
        if cn not in (None, NONE):
            numbers = arr[:, cn]
            if not np.all(np.isfinite(numbers)) or np.any(numbers != np.round(numbers)):
                raise ValueError("Electrode numbers must be whole numbers")
            numbers = numbers.astype(int)
        if len(xyz) < 2:
            raise ValueError("A profile needs at least 2 stations")
        return profile_from_stations(name, self.store.crs_authid, xyz, numbers, method=method)

    # -- selected line -----------------------------------------------------------------------
    def _line_layer(self):
        layer = self.iface.activeLayer() if hasattr(self.iface, "activeLayer") else None
        if isinstance(layer, QgsVectorLayer) and \
                layer.geometryType() == QgsWkbTypes.GeometryType.LineGeometry:
            return layer
        return None

    def _update_line_info(self) -> None:
        layer = self._line_layer()
        if layer is None:
            self.line_info.setText("Make a line layer active and select one line feature.")
        else:
            self.line_info.setText(f"Layer “{layer.name()}”: {layer.selectedFeatureCount()} "
                                   "feature(s) selected. Stations start at the first vertex.")

    def _to_store(self, crs: QgsCoordinateReferenceSystem):
        dst = QgsCoordinateReferenceSystem(self.store.crs_authid)
        if not crs.isValid() or crs == dst:
            return None
        return QgsCoordinateTransform(crs, dst, self.project)

    def _from_line(self, name: str, method: str):
        layer = self._line_layer()
        if layer is None or layer.selectedFeatureCount() != 1:
            raise ValueError("Select exactly one line feature in the active line layer")
        geom = QgsGeometry(layer.selectedFeatures()[0].geometry())
        tr = self._to_store(layer.crs())
        if tr is not None:
            geom.transform(tr)
        if geom.isMultipart():
            parts = geom.asMultiPolyline()
            if len(parts) != 1:
                raise ValueError("The selected feature has several parts; select a single line")
            line = parts[0]
        else:
            line = geom.asPolyline()
        xy = np.array([(p.x(), p.y()) for p in line], dtype=float)
        if len(xy) < 2:
            raise ValueError("The selected line needs at least 2 vertices")
        return profile_from_line(name, self.store.crs_authid, xy,
                                 self._spacing(self.line_spacing), method=method)

    # -- start / end points ------------------------------------------------------------------
    def _from_points(self, name: str, method: str):
        xy = np.array([[self.x1.value(), self.y1.value()], [self.x2.value(), self.y2.value()]])
        if np.hypot(*(xy[1] - xy[0])) == 0.0:
            raise ValueError("Start and end point must be different")
        return profile_from_line(name, self.store.crs_authid, xy,
                                 self._spacing(self.points_spacing), method=method)

    def start_pick(self) -> None:
        canvas = self.iface.mapCanvas()
        self._picked = []
        self._prev_tool = canvas.mapTool()
        self.pick_tool = QgsMapToolEmitPoint(canvas)
        self.pick_tool.canvasClicked.connect(self._pick_clicked)
        self.pick_tool.deactivated.connect(self._pick_done)
        canvas.setMapTool(self.pick_tool)
        self.hide()

    def _pick_clicked(self, point, _button=None) -> None:
        canvas = self.iface.mapCanvas()
        tr = self._to_store(canvas.mapSettings().destinationCrs())
        if tr is not None:
            point = tr.transform(point)
        self._picked.append(point)
        a, b = (self.x1, self.y1) if len(self._picked) == 1 else (self.x2, self.y2)
        a.setValue(point.x())
        b.setValue(point.y())
        if len(self._picked) >= 2:
            self._finish_pick()

    def _finish_pick(self) -> None:
        canvas, tool = self.iface.mapCanvas(), self.pick_tool
        if tool is not None and canvas.mapTool() is tool:
            if self._prev_tool is not None:
                canvas.setMapTool(self._prev_tool)
            else:
                canvas.unsetMapTool(tool)
        self._pick_done()

    def _pick_done(self) -> None:
        """The pick tool finished or lost the canvas: bring the dialog back."""
        if self.pick_tool is None:
            return
        tool, self.pick_tool = self.pick_tool, None
        tool.deactivated.disconnect(self._pick_done)
        tool.deleteLater()
        self._prev_tool = None
        if not self._closing:
            self.tabs.setCurrentIndex(TAB_POINTS)
            self.show()
            self.raise_()

    # -- saving ------------------------------------------------------------------------------
    @staticmethod
    def _spacing(box: QDoubleSpinBox) -> float:
        if box.value() <= 0:
            raise ValueError("Station spacing must be greater than 0 m")
        return box.value()

    def build(self):
        """(profile, station set) from the current tab. Raises ValueError."""
        name = self.name_edit.text().strip()
        if not name:
            raise ValueError("Enter a name for the profile")
        method = self.method_combo.currentData()
        build = {TAB_FILE: self._from_file, TAB_LINE: self._from_line,
                 TAB_POINTS: self._from_points}[self.tabs.currentIndex()]
        return build(name, method)

    def accept(self) -> None:
        try:
            profile, station_set = self.build()
            add_profile(self.store, profile, station_set, self.project, self.provider)
        except (ValueError, OSError) as exc:
            self._error(str(exc))
            return
        self.profile = profile
        super().accept()

    def _error(self, message: str) -> None:
        self.last_error = message
        QMessageBox.warning(self, self.windowTitle(), message)

    def done(self, result: int) -> None:
        self._closing = True
        if self.pick_tool is not None:
            self._finish_pick()
        super().done(result)
        self._closing = False
