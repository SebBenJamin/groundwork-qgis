"""'Where the Line Runs': the group the Add Data, New Profile and Profile Properties dialogs
share to say where a profile's line lies. Six sources, one radio row each: an existing
profile, the selected line feature, start and end points (typed or picked on the map), a
positions file, a point layer and, when allowed, the file's own map coordinates.

Everything is in the workbench store's CRS. While the widget would create a line and is
visible, the line and its points are drawn on the map canvas in its selection colour.
``placement()`` says what was chosen as a ``core.placement.Placement``; a positions source
gives ``positions`` (the line is made through them) and no ``line_xy``."""
from __future__ import annotations

from functools import partial

import numpy as np
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsFieldProxyModel, QgsGeometry,
                       QgsPointXY, QgsVectorLayer, QgsWkbTypes)
from qgis.gui import (QgsDoubleSpinBox, QgsFieldComboBox, QgsFileWidget, QgsMapLayerComboBox,
                      QgsMapToolEmitPoint, QgsProjectionSelectionWidget, QgsRubberBand)
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QGridLayout, QGroupBox,
                                 QHBoxLayout, QLabel, QLineEdit, QPushButton, QRadioButton,
                                 QSizePolicy, QVBoxLayout, QWidget)

from ..core.layout import inline_distances
from ..core.model import profile_from_positions
from ..core.numbers import fmt, fmt_trim, parse
from ..core.placement import Placement
from ..core.roles import PositionColumns, guess_position_columns
from ..readers.texttable import guess_options, read_table
from ..section.crossing_lines import own_layer_ids
from .positions_source import crs_of, positions_from_layer, positions_from_table, \
    selected_line, to_store
from .table_widgets import TableOptionsBox

SOURCES = ("existing", "line", "points", "positions", "layer", "file")
CREATES_LINE = SOURCES[1:]
SOURCE_LABELS = {"existing": "Existing profile", "line": "Selected line feature",
                 "points": "Start and end points", "positions": "Positions file",
                 "layer": "Point layer", "file": "The file's own coordinates"}
POSITIONS_HINT = "Coordinates for some or all stations, or for known distances"
ZERO_ITEMS = (("Start of the line", "start"), ("End of the line", "end"),
              ("Station 1", "station1"))
ROLES = (("easting", "Easting"), ("northing", "Northing"), ("elevation", "Elevation"),
         ("number", "Number"), ("inline", "Distance"))
INLINE_TIP = "Each position's distance along the line, in the data file's metres"
TABLE_FILTER = "Text tables (*.csv *.txt *.dat);;All files (*)"


def _remove_bands(canvas, bands: list) -> None:
    """Take the overlay off the canvas (also called when the widget is destroyed)."""
    for band in bands:
        try:
            band.reset()
            canvas.scene().removeItem(band)
        except RuntimeError:            # the canvas went first
            pass
    bands.clear()


def _length(xy: np.ndarray) -> float:
    return float(np.hypot(*np.diff(np.asarray(xy, dtype=float), axis=0).T).sum())


def _label(text: str) -> QLabel:
    """A hint that never widens its container; the full text is in the tooltip."""
    label = QLabel(text)
    label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    label.setToolTip(text)
    return label


class PlacementWidget(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, iface, store, project, allow_existing: bool = True,
                 allow_file_coordinates: bool = False, parent=None):
        super().__init__("Where the Line Runs", parent)
        self.iface, self.store, self.project = iface, store, project
        self._table = None                  # the positions file as read
        self._table_error = ""
        self._file_line, self._file_bends = None, 0
        self._guess = None                  # guessed station spacing
        self._needs_distance = False
        self._station1: dict[str, bool] = {}   # profile id -> it has a station 1
        self._skipped = 0                   # rows of the positions file without coordinates
        self._collapsed = False
        self._busy = False
        self._shape = None                  # (line, points) the overlay shows
        self._bands: list = []
        self._watched = None                # line layer whose selection the hint follows
        self.pick_tool, self._picked, self._prev_tool, self._closing = None, [], None, False
        self._radios: dict[str, QRadioButton] = {}
        self._details: dict[str, QWidget] = {}
        self._buttons = QButtonGroup(self)

        self._collapsed_row = QWidget()
        self._collapsed_label = _label("")
        other = QPushButton("Other…")
        other.setObjectName("other_button")
        other.setToolTip("Choose another way to say where the line runs")
        other.clicked.connect(self._expand)
        row = QHBoxLayout(self._collapsed_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(self._collapsed_label, 1)
        row.addWidget(other)

        self._expanded = QWidget()
        self._grid = QGridLayout(self._expanded)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setColumnStretch(1, 1)
        if allow_existing:
            self.profile_combo = QComboBox()
            self._fill_profiles()
            self._row("existing", self.profile_combo)
        self.line_info = _label("")
        self._row("line", self.line_info)
        pick = QPushButton("Pick on Map")
        pick.setToolTip("Click the start point, then the end point on the map")
        pick.clicked.connect(self.start_pick)
        pick_row = QWidget()
        box = QHBoxLayout(pick_row)
        box.setContentsMargins(0, 0, 0, 0)
        box.addWidget(pick)
        box.addStretch(1)
        self._row("points", pick_row, self._points_detail())
        self._row("positions", _label(POSITIONS_HINT), self._positions_detail())
        self.layer_combo = QgsMapLayerComboBox()
        self.layer_combo.setProject(project)
        self.layer_combo.setFilters(Qgis.LayerFilter.PointLayer)
        own = own_layer_ids(store, project)             # the workbench's stations are not data
        self.layer_combo.setExceptedLayerList([project.mapLayer(i) for i in own
                                               if project.mapLayer(i) is not None])
        self._row("layer", self.layer_combo, self._layer_detail())
        if allow_file_coordinates:
            self.file_info = _label("")
            self._row("file", self.file_info)

        self._spacing_row = QWidget()
        self.spacing_edit = QLineEdit()
        self.spacing_edit.setObjectName("spacing_edit")
        self.spacing_edit.setToolTip("Distance between neighbouring stations. Leave it empty "
                                     "to use the guess shown, which is never saved.")
        self._distance_row = QWidget()
        self.zero_combo = QComboBox()
        self.zero_combo.setObjectName("zero_combo")
        self.offset_spin = QgsDoubleSpinBox()
        self.offset_spin.setRange(-1e6, 1e6)
        self.offset_spin.setDecimals(2)
        self.offset_spin.setSuffix(" m")
        self.offset_spin.setClearValue(0.0)
        self.offset_spin.setToolTip("Distance 0 of the file lies this far along the line "
                                    "from the point chosen")
        for widget, items in ((self._spacing_row, (("Station spacing (m)", self.spacing_edit),)),
                              (self._distance_row, (("Distance 0 is at", self.zero_combo),
                                                    ("Offset", self.offset_spin)))):
            box = QHBoxLayout(widget)
            box.setContentsMargins(0, 0, 0, 0)
            for text, field in items:
                box.addWidget(QLabel(text))
                box.addWidget(field, 1)

        layout = QVBoxLayout(self)
        for w in (self._collapsed_row, self._expanded, self._spacing_row, self._distance_row):
            layout.addWidget(w)
        self._connect()
        default = "existing" if allow_existing and self.profile_combo.count() else "line"
        self._radios[default].setChecked(True)
        self.destroyed.connect(partial(_remove_bands, iface.mapCanvas(), self._bands))
        self._on_change()

    # -- building ----------------------------------------------------------------------------
    def _row(self, name: str, control: QWidget, detail: QWidget | None = None) -> None:
        radio = QRadioButton(SOURCE_LABELS[name])
        radio.setObjectName(f"source_{name}")
        self._buttons.addButton(radio)
        self._radios[name] = radio
        r = self._grid.rowCount()
        self._grid.addWidget(radio, r, 0)
        self._grid.addWidget(control, r, 1)
        if detail is not None:
            self._details[name] = detail
            self._grid.addWidget(detail, r + 1, 1)

    def _points_detail(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        self.x1, self.y1, self.x2, self.y2 = (QgsDoubleSpinBox() for _ in range(4))
        for box in (self.x1, self.y1, self.x2, self.y2):
            box.setRange(-1e9, 1e9)
            box.setDecimals(2)
            box.setToolTip(f"Coordinates in {self.store.crs_authid}")
        for r, (text, a, b) in enumerate((("Start X / Y", self.x1, self.y1),
                                          ("End X / Y", self.x2, self.y2))):
            grid.addWidget(QLabel(text), r, 0)
            grid.addWidget(a, r, 1)
            grid.addWidget(b, r, 2)
        return page

    def _positions_detail(self) -> QWidget:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(0, 0, 0, 0)
        self.file_widget = QgsFileWidget()
        self.file_widget.setFilter(TABLE_FILTER)
        self.options_box = TableOptionsBox()
        self.options_box.setCollapsed(True)
        grid = QGridLayout()
        self.role_combos: dict[str, QComboBox] = {}
        for i, (role, text) in enumerate(ROLES):
            combo = QComboBox()
            combo.setObjectName(f"role_{role}")
            self.role_combos[role] = combo
            grid.addWidget(QLabel(text), i // 2, (i % 2) * 2)
            grid.addWidget(combo, i // 2, (i % 2) * 2 + 1)
        self.role_combos["inline"].setToolTip(INLINE_TIP)
        self.crs_widget = QgsProjectionSelectionWidget()
        self.crs_widget.setObjectName("role_crs")
        self.crs_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        grid.addWidget(QLabel("CRS"), 2, 2)
        grid.addWidget(self.crs_widget, 2, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.positions_status = QLabel()
        self.positions_status.setWordWrap(True)
        for w in (self.file_widget, self.options_box):
            box.addWidget(w)
        box.addLayout(grid)
        box.addWidget(self.positions_status)
        return page

    def _layer_detail(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(0, 0, 0, 0)
        self.field_combos: dict[str, QgsFieldComboBox] = {}
        for i, (role, text) in enumerate((("number", "Number"), ("inline", "Distance"),
                                          ("elevation", "Elevation"))):
            combo = QgsFieldComboBox()
            combo.setFilters(QgsFieldProxyModel.Filter.Numeric)
            combo.setAllowEmptyFieldName(True)
            self.field_combos[role] = combo
            grid.addWidget(QLabel(text), i // 2, (i % 2) * 2)
            grid.addWidget(combo, i // 2, (i % 2) * 2 + 1)
        self.field_combos["inline"].setToolTip(INLINE_TIP)
        self.selected_check = QCheckBox("Selected features only")
        self.selected_check.setChecked(True)
        grid.addWidget(self.selected_check, 1, 2, 1, 2)
        return page

    def _connect(self) -> None:
        change = self._on_change
        for radio in self._radios.values():
            radio.toggled.connect(lambda on: on and self._on_change())
        if "existing" in self._radios:
            self.profile_combo.currentIndexChanged.connect(change)
        for w in (self.x1, self.y1, self.x2, self.y2, self.offset_spin):
            w.valueChanged.connect(change)
        for combo in (*self.role_combos.values(), self.zero_combo):
            combo.currentIndexChanged.connect(change)
        for combo in self.field_combos.values():
            combo.fieldChanged.connect(change)
        self.crs_widget.crsChanged.connect(change)
        self.selected_check.toggled.connect(change)
        self.spacing_edit.textChanged.connect(change)
        self.layer_combo.layerChanged.connect(self._layer_changed)
        self.file_widget.fileChanged.connect(self.set_positions_file)
        self.options_box.changed.connect(self._options_changed)
        if hasattr(self.iface, "currentLayerChanged"):
            self.iface.currentLayerChanged.connect(change)

    # -- public setters ----------------------------------------------------------------------
    def source(self) -> str | None:
        return next((n for n, r in self._radios.items() if r.isChecked()), None)

    def select_source(self, name: str) -> None:
        if name not in self._radios:
            raise ValueError(f"source {name!r} is not offered here")
        self._collapsed = self._collapsed and name == "existing"
        self._radios[name].setChecked(True)
        self._on_change()

    def set_current_profile(self, profile_id: str | None) -> None:
        """Preselect ``profile_id`` and collapse the group to one line with "Other…"."""
        if profile_id is None or "existing" not in self._radios:
            self._expand()
            return
        self._fill_profiles()
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(profile_id)))
        text = f"Profile “{self.profile_combo.currentText()}”"
        self._collapsed_label.setText(text)
        self._collapsed_label.setToolTip(text)
        self._collapsed = True
        self.select_source("existing")

    def set_file_line(self, xy: np.ndarray | None, bends: int = 0) -> None:
        """The line derived from a file in map coordinates (None: the file has none)."""
        self._file_line = None if xy is None else np.asarray(xy, dtype=float)[:, :2]
        self._file_bends = int(bends)
        self._on_change()

    def set_needs_distance(self, flag: bool) -> None:
        self._needs_distance = bool(flag)
        self._on_change()

    def set_guessed_spacing(self, value: float | None) -> None:
        self._guess = value if value is not None and value > 0 else None
        self.spacing_edit.setPlaceholderText(
            "" if self._guess is None else f"{fmt_trim(self._guess, 3)} (guessed)")
        self._on_change()

    def set_points(self, x1: float, y1: float, x2: float, y2: float) -> None:
        was, self._busy = self._busy, True
        for box, v in zip((self.x1, self.y1, self.x2, self.y2), (x1, y1, x2, y2)):
            box.setValue(float(v))
        self._busy = was
        self.select_source("points")

    def set_positions_file(self, path) -> None:
        path = str(path)
        self.file_widget.blockSignals(True)
        self.file_widget.setFilePath(path)
        self.file_widget.blockSignals(False)
        try:
            self.options_box.set_options(guess_options(path))
        except (OSError, ValueError):
            pass                            # read_table says what is wrong
        self._read_table()
        self.select_source("positions")

    def set_point_layer(self, layer, number_field: str | None = None,
                        inline_field: str | None = None, elevation_field: str | None = None,
                        selected_only: bool = True) -> None:
        was, self._busy = self._busy, True
        if self.project.mapLayer(layer.id()) is None:     # offered, not added to the project
            self.layer_combo.setAdditionalLayers([layer])
        self.layer_combo.setLayer(layer)
        self._layer_changed(layer)
        for role, name in (("number", number_field), ("inline", inline_field),
                           ("elevation", elevation_field)):
            self.field_combos[role].setField(name or "")
        self.selected_check.setChecked(selected_only)
        self._busy = was
        self.select_source("layer")

    # -- what was chosen ---------------------------------------------------------------------
    def placement(self) -> Placement:
        """The placement chosen; ValueError with a message for the user when incomplete."""
        src = self.source()
        if src is None:
            raise ValueError("Choose where the line runs")
        kw = {}
        if self._needs_distance:
            kw = {"zero": self.zero_combo.currentData() or "start",
                  "offset": self.offset_spin.value()}
        if src == "existing":
            if not self.profile_combo.currentData():
                raise ValueError("Choose a profile")
            return Placement(profile_id=self.profile_combo.currentData(), **kw)
        if src in ("positions", "layer"):
            positions = self._positions()
            profile_from_positions("", self.store.crs_authid, positions)   # raises if no line
            spacing = self._typed_spacing() if self._numbers_only() else None
            return Placement(positions=positions, spacing=spacing, **kw)
        return Placement(line_xy=self._line(src), **kw)

    def known_points(self) -> tuple[np.ndarray, np.ndarray, list[str]] | None:
        """(distance in the file, chainage, labels) of the positions with a known distance,
        for the fit report; None with fewer than two or without positions."""
        if self.source() not in ("positions", "layer"):
            return None
        try:
            _, sset = profile_from_positions("", self.store.crs_authid, self._positions())
            spacing = self._typed_spacing() if self._numbers_only() else None
        except ValueError:
            return None
        guess = self._guess if self._numbers_only() else None
        d, _ = inline_distances(sset.numbers, sset.inline, None, spacing, guess)
        s = np.asarray(sset.chainage, dtype=float)
        ok = np.isfinite(d) & np.isfinite(s)
        if ok.sum() < 2:
            return None
        return d[ok], s[ok], [str(int(n)) for n in np.asarray(sset.numbers)[ok]]

    def spacing_is_guess(self) -> bool:
        return not self.spacing_edit.text().strip() and self._guess is not None

    # -- sources -----------------------------------------------------------------------------
    def _fill_profiles(self) -> None:
        current = self.profile_combo.currentData()
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in self.store.profiles():
            self.profile_combo.addItem(p.name or p.id, p.id)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(current)))
        self.profile_combo.blockSignals(False)
        radio = self._radios.get("existing")
        if radio is not None:
            radio.setEnabled(self.profile_combo.count() > 0)
            radio.setToolTip("" if self.profile_combo.count() else "There is no profile yet")

    def _line_layer(self):
        layer = self.iface.activeLayer() if hasattr(self.iface, "activeLayer") else None
        if isinstance(layer, QgsVectorLayer) and \
                layer.geometryType() == QgsWkbTypes.GeometryType.LineGeometry:
            return layer
        return None

    def _watch(self, layer) -> None:
        """Follow the selection of the active line layer, so the hint stays current."""
        if layer is self._watched:
            return
        if self._watched is not None:
            try:
                self._watched.selectionChanged.disconnect(self._on_change)
            except (TypeError, RuntimeError):
                pass
        self._watched = layer
        if layer is not None:
            layer.selectionChanged.connect(self._on_change)

    def _update_line_info(self) -> None:
        layer = self._line_layer()
        self._watch(layer)
        if layer is None:
            text = "Make a line layer active and select one line feature"
        else:
            n = layer.selectedFeatureCount()
            text = f"Layer “{layer.name()}”: " + (f"{n} features selected" if n != 1 else
                                                  "1 feature selected")
            if n == 1:
                try:
                    text += f", {fmt(_length(self._line('line')), 1)} m"
                except ValueError as exc:
                    text += f"; {exc}"
        self.line_info.setText(text)
        self.line_info.setToolTip(text)

    def _update_file_info(self) -> None:
        if "file" not in self._radios:
            return
        if self._file_line is None:
            text = "The file has no map coordinates"
        else:
            bends = self._file_bends
            text = f"Line through the file's coordinates, {fmt(_length(self._file_line), 1)} m"
            text += f", {bends} bend{'s' if bends != 1 else ''}" if bends else ""
        self.file_info.setText(text)
        self.file_info.setToolTip(text)

    def _line(self, src: str) -> np.ndarray:
        if src == "line":
            return selected_line(self._line_layer(), self.store.crs_authid, self.project)
        if src == "points":
            xy = np.array([[self.x1.value(), self.y1.value()],
                           [self.x2.value(), self.y2.value()]])
            if np.hypot(*(xy[1] - xy[0])) == 0.0:
                raise ValueError("Start and end point must be different")
            return xy
        if src == "file":
            if self._file_line is None:
                raise ValueError("The file has no map coordinates to draw the line from")
            return self._file_line.copy()
        profile, _ = profile_from_positions("", self.store.crs_authid, self._positions())
        return profile.xy

    def _layer_changed(self, layer) -> None:
        for combo in self.field_combos.values():
            combo.setLayer(layer)
        self._on_change()

    # -- positions ---------------------------------------------------------------------------
    def _options_changed(self) -> None:
        self._read_table()
        self._on_change()

    def _read_table(self) -> None:
        path = self.file_widget.filePath()
        self._table, self._table_error = None, ""
        if not path.strip():
            self._fill_roles()
            return
        try:
            self._table = read_table(path, self.options_box.options())
        except FileNotFoundError:
            self._table_error = f"File not found: {path}"
        except (OSError, ValueError) as exc:
            self._table_error = str(exc)
        self._fill_roles()

    def _fill_roles(self) -> None:
        table, was, self._busy = self._table, self._busy, True
        guess = guess_position_columns(table) if table is not None else None
        numeric = [] if table is None else \
            [c for c in range(table.n_columns) if table.is_numeric(c)]
        for role, combo in self.role_combos.items():
            combo.clear()
            combo.addItem("(none)", None)
            for c in numeric:                       # a text column is never a coordinate
                combo.addItem(table.names[c], c)
            chosen = getattr(guess, role) if guess is not None else None
            combo.setCurrentIndex(max(0, combo.findData(chosen)))
        if guess is not None:
            self.crs_widget.setCrs(crs_of(guess.crs, self.store.crs_authid))
        self._busy = was

    def _columns(self) -> PositionColumns:
        data = {role: combo.currentData() for role, combo in self.role_combos.items()}
        crs = self.crs_widget.crs()
        text = "" if crs.authid() == self.store.crs_authid else \
            (crs.authid() or ("WKT:" + crs.toWkt() if crs.isValid() else ""))
        return PositionColumns(crs=text, **data)

    def _positions(self):
        if self.source() == "layer":
            fields = {role: combo.currentField() or None
                      for role, combo in self.field_combos.items()}
            return positions_from_layer(self.layer_combo.currentLayer(), fields["number"],
                                        fields["inline"], fields["elevation"],
                                        self.selected_check.isChecked(),
                                        self.store.crs_authid, self.project)
        if self._table is None:
            raise ValueError(self._table_error or "Choose a positions file")
        positions, self._skipped = positions_from_table(self._table, self._columns(),
                                                        self.store.crs_authid, self.project)
        return positions

    def _numbers_only(self) -> bool:
        """The positions have station numbers but no distances: the spacing matters."""
        if self.source() == "layer":
            fields = self.field_combos
            return bool(fields["number"].currentField()) and not fields["inline"].currentField()
        if self.source() == "positions" and self._table is not None:
            roles = self.role_combos
            return roles["number"].currentData() is not None and \
                roles["inline"].currentData() is None
        return False

    def _typed_spacing(self) -> float | None:
        text = self.spacing_edit.text().strip()
        if not text:
            return None
        try:
            value = parse(text)
        except ValueError:
            raise ValueError("Type the station spacing as a number, for example "
                             f"{fmt_trim(2.5)}") from None
        if not np.isfinite(value) or value <= 0:
            raise ValueError("The station spacing must be greater than 0 m")
        return value

    def _has_station1(self) -> bool:
        src = self.source()
        if src == "existing" and self.profile_combo.currentData():
            pid = self.profile_combo.currentData()
            if pid not in self._station1:           # one store read per profile
                self._station1[pid] = any(1 in np.asarray(s.numbers).tolist()
                                          for s in self.store.station_sets(pid))
            return self._station1[pid]
        if src == "positions" and self._table is not None:
            col = self.role_combos["number"].currentData()
            return col is not None and 1.0 in self._table.numeric(col)
        return src == "layer" and bool(self.field_combos["number"].currentField())

    # -- state and overlay -------------------------------------------------------------------
    def _expand(self) -> None:
        self._collapsed = False
        self._on_change()

    def _on_change(self, *_args) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self._sync()
        finally:
            self._busy = False
        self._update_overlay()
        self.changed.emit()

    def _sync(self) -> None:
        src = self.source()
        self._collapsed_row.setVisible(self._collapsed)
        self._expanded.setVisible(not self._collapsed)
        for name, detail in self._details.items():
            detail.setVisible(name == src)
        self._update_line_info()
        self._update_file_info()
        self._spacing_row.setVisible(self._numbers_only())
        self._distance_row.setVisible(self._needs_distance)
        current = self.zero_combo.currentData()
        self.zero_combo.clear()
        for text, value in ZERO_ITEMS[:3 if self._has_station1() else 2]:
            self.zero_combo.addItem(text, value)
        self.zero_combo.setCurrentIndex(max(0, self.zero_combo.findData(current)))
        self._shape, status = None, ""
        if src in CREATES_LINE:
            try:
                line = self._line(src)
                points = self._positions().xyz[:, :2] if src in ("positions", "layer") else line
                self._shape = (line, points)
                if src == "positions":
                    status = f"{len(points)} positions, line {fmt(_length(line), 1)} m"
                    k = self._skipped
                    status += f"; {k} row{'s' if k != 1 else ''} without coordinates " \
                              "skipped" if k else ""
            except ValueError as exc:
                status = str(exc)
        self.positions_status.setText(status)

    def _update_overlay(self) -> None:
        if not self.isVisible() or self._shape is None:
            self.clear_overlay()
            return
        canvas = self.iface.mapCanvas()
        if not self._bands:
            for kind in (Qgis.GeometryType.Line, Qgis.GeometryType.Point):
                band = QgsRubberBand(canvas, kind)
                band.setColor(canvas.selectionColor())
                band.setWidth(2)
                self._bands.append(band)
            self._bands[1].setIcon(QgsRubberBand.IconType.ICON_CIRCLE)
            self._bands[1].setIconSize(8)
        crs = QgsCoordinateReferenceSystem(self.store.crs_authid)
        line, points = ([QgsPointXY(float(x), float(y)) for x, y in a] for a in self._shape)
        self._bands[0].setToGeometry(QgsGeometry.fromPolylineXY(line), crs)
        self._bands[1].setToGeometry(QgsGeometry.fromMultiPointXY(points), crs)

    def clear_overlay(self) -> None:
        _remove_bands(self.iface.mapCanvas(), self._bands)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._on_change()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.clear_overlay()

    # -- pick on map -------------------------------------------------------------------------
    def start_pick(self) -> None:
        canvas = self.iface.mapCanvas()
        self._picked = []
        self._prev_tool = canvas.mapTool()
        self.pick_tool = QgsMapToolEmitPoint(canvas)
        self.pick_tool.canvasClicked.connect(self._pick_clicked)
        self.pick_tool.deactivated.connect(self._pick_done)
        canvas.setMapTool(self.pick_tool)
        self.window().hide()

    def _pick_clicked(self, point, _button=None) -> None:
        canvas = self.iface.mapCanvas()
        tr = to_store(canvas.mapSettings().destinationCrs(), self.store.crs_authid,
                      self.project)
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
            self.select_source("points")
            self.window().show()
            self.window().raise_()

    def cancel_pick(self) -> None:
        """End a pick without bringing the dialog back (its ``done()`` calls this)."""
        self._closing = True
        try:
            if self.pick_tool is not None:
                self._finish_pick()
        finally:
            self._closing = False
