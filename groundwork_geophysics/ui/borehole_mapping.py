"""The 'Boreholes' part of the context dialog: a list of borehole entries. Each entry is a
borehole point layer (id, elevation and total-depth fields), its interval table (any layer,
also non-spatial) with its field mapping and QGIS style, its curve tables, and how the
section draws its columns."""
from __future__ import annotations

from typing import Callable

from qgis.core import QgsVectorLayer
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QListWidget,
                                 QMessageBox, QPushButton, QStackedWidget, QTableWidget,
                                 QTableWidgetItem, QVBoxLayout, QWidget)

from ..core.context_settings import (BoreholeSetting, CurveField, CurveTableSetting,
                                     curve_key)

NONE = "None"
MISSING = "(not in project)"
IMPORT_LAS_TEXT = "Import LAS…"
IMPORT_LAS_TIP = ("Read well logs from LAS files into a curve table of this entry (one "
                  "well per file, matched to the borehole ids)")
IMPORT_LAS_NO_STORE = "Open or create a Groundwork project first: the curves are kept in it"
IMPORT_LAS_NO_LAYER = "Choose the borehole layer and its id field first"
LAS_LAYER_NAME = "LAS curves"


def fill_layer_combo(combo: QComboBox, layers, current: str = "") -> None:
    """``layers`` as entries after 'None'; the entry data is the layer id."""
    combo.blockSignals(True)
    combo.clear()
    combo.addItem(NONE, "")
    for layer in layers:
        combo.addItem(layer.name(), layer.id())
    combo.setCurrentIndex(max(0, combo.findData(current)))
    combo.blockSignals(False)


def keep_missing(combo: QComboBox, project, layer_id: str) -> None:
    """A saved layer id that is not in the project stays selectable as '(not in project)', so
    pressing OK keeps its settings; choosing another entry (or 'None') replaces it."""
    if layer_id and project.mapLayer(layer_id) is None:
        combo.addItem(MISSING, layer_id)
        combo.setCurrentIndex(combo.count() - 1)


def fill_field_combo(combo: QComboBox, layer, current: str = "", optional: bool = True) -> None:
    """The fields of ``layer`` (none when ``layer`` is None)."""
    combo.clear()
    if optional:
        combo.addItem(NONE, "")
    if layer is not None:
        for name in layer.fields().names():
            combo.addItem(name, name)
    combo.setCurrentIndex(max(0, combo.findData(current)))


def field_of(combo: QComboBox) -> str:
    return combo.currentData() or ""


class CurveTableEditor(QGroupBox):
    """One curve table: layer, borehole id and depth fields, and which value fields are
    curves (with a unit each, and whether the section draws them)."""
    _CURVE, _UNIT = range(2)

    def __init__(self, project, tables: list[QgsVectorLayer], on_remove=None):
        super().__init__("Curve table")
        self.project = project
        self.loaded: CurveTableSetting | None = None
        self.layer_combo, self.id_combo, self.depth_combo = QComboBox(), QComboBox(), QComboBox()
        fill_layer_combo(self.layer_combo, tables)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Curve", "Unit"])
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(110)
        form = QFormLayout(self)
        form.addRow("Table", self.layer_combo)
        form.addRow("Borehole id field", self.id_combo)
        form.addRow("Depth field (m below top)", self.depth_combo)
        form.addRow(self.table)
        remove = QPushButton("Remove curve table")
        form.addRow(remove)
        if on_remove is not None:
            remove.clicked.connect(lambda: on_remove(self))
        self.layer_combo.currentIndexChanged.connect(lambda _i: self._refill())
        self._refill()

    def _layer(self):
        return self.project.mapLayer(self.layer_combo.currentData() or "")

    def _refill(self, setting: CurveTableSetting | None = None) -> None:
        layer = self._layer()
        fill_field_combo(self.id_combo, layer, setting.id_field if setting else "")
        fill_field_combo(self.depth_combo, layer, setting.depth_field if setting else "")
        chosen = {c.field: c.unit for c in (setting.curves if setting else [])}
        self.table.setRowCount(0)
        for name in (layer.fields().names() if layer is not None else []):
            row = self.table.rowCount()
            self.table.insertRow(row)
            item = QTableWidgetItem(name)
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            item.setCheckState(Qt.CheckState.Checked if name in chosen
                               else Qt.CheckState.Unchecked)
            self.table.setItem(row, self._CURVE, item)
            self.table.setItem(row, self._UNIT, QTableWidgetItem(chosen.get(name, "")))
        for combo in (self.id_combo, self.depth_combo):
            combo.setEnabled(layer is not None)

    def set_layer(self, layer_id: str) -> None:
        self.layer_combo.setCurrentIndex(max(0, self.layer_combo.findData(layer_id)))

    def set_fields(self, id_field: str, depth_field: str) -> None:
        self.id_combo.setCurrentIndex(max(0, self.id_combo.findData(id_field)))
        self.depth_combo.setCurrentIndex(max(0, self.depth_combo.findData(depth_field)))

    def check_curve(self, field_name: str, unit: str = "") -> None:
        for row in range(self.table.rowCount()):
            if self.table.item(row, self._CURVE).text() == field_name:
                self.table.item(row, self._CURVE).setCheckState(Qt.CheckState.Checked)
                self.table.item(row, self._UNIT).setText(unit)

    def load(self, setting: CurveTableSetting) -> None:
        self.loaded = setting
        keep_missing(self.layer_combo, self.project, setting.layer_id)
        self.layer_combo.blockSignals(True)
        self.set_layer(setting.layer_id)
        self.layer_combo.blockSignals(False)
        self._refill(setting)

    def _missing(self) -> bool:
        return self.layer_combo.currentText() == MISSING

    def setting(self) -> CurveTableSetting | None:
        layer_id = self.layer_combo.currentData() or ""
        if not layer_id:
            return None
        if self._missing() and self.loaded is not None:
            return self.loaded                       # layer gone: keep what was saved
        curves = [CurveField(self.table.item(r, self._CURVE).text(),
                             self.table.item(r, self._UNIT).text().strip())
                  for r in range(self.table.rowCount())
                  if self.table.item(r, self._CURVE).checkState() == Qt.CheckState.Checked]
        return CurveTableSetting(layer_id, field_of(self.id_combo), field_of(self.depth_combo),
                                 curves)


class BoreholeGroup(QGroupBox):
    """One borehole entry."""

    def __init__(self, project, vector_layers: list[QgsVectorLayer], point_layers,
                 current_boreholes: Callable[[], tuple] = lambda: ([], ""), on_styled=None,
                 on_layer_changed=None, store_path: Callable[[], object] = lambda: None):
        super().__init__("Borehole Entry")
        self.project = project
        self.store_path = store_path        # the Groundwork GeoPackage, or None
        self.vector_layers = vector_layers
        self.current_boreholes, self.on_styled = current_boreholes, on_styled
        self.loaded = None                  # the saved setting, kept for layers now missing
        self.layer_combo = QComboBox()
        self.id_combo = QComboBox()
        self.elevation_combo = QComboBox()
        self.total_depth_combo = QComboBox()
        self.log_combo = QComboBox()
        self.log_id_combo = QComboBox()
        self.top_combo = QComboBox()
        self.bottom_combo = QComboBox()
        self.lithology_combo = QComboBox()
        self.layer_combo.setObjectName("borehole_layer")
        self.elevation_combo.setObjectName("borehole_elevation")
        self.total_depth_combo.setObjectName("borehole_total_depth")
        self.log_combo.setObjectName("interval_table")
        self.log_id_combo.setObjectName("interval_id")
        self.lithology_combo.setObjectName("interval_text")
        fill_layer_combo(self.layer_combo, point_layers)
        fill_layer_combo(self.log_combo, vector_layers)
        self.style_button = QPushButton("Borehole Style…")
        self.style_button.setObjectName("borehole_style")
        self.style_button.setToolTip("Style the intervals with QGIS's own style editor")
        self.style_button.clicked.connect(self._open_style)
        form = QFormLayout(self)
        form.addRow("Borehole layer", self.layer_combo)
        form.addRow("Borehole id field", self.id_combo)
        form.addRow("Ground elevation field", self.elevation_combo)
        form.addRow("Total depth field", self.total_depth_combo)
        form.addRow("Interval table", self.log_combo)
        form.addRow("Intervals: borehole id field", self.log_id_combo)
        form.addRow("Intervals: top depth field", self.top_combo)
        form.addRow("Intervals: bottom depth field", self.bottom_combo)
        form.addRow("Intervals: text field", self.lithology_combo)
        form.addRow("", self.style_button)
        # how the columns look (width, opacity, layer text, curves) is set in the borehole
        # viewer, for the viewer and the section alike; kept unchanged here
        self.curves_box = QVBoxLayout()
        form.addRow(self.curves_box)
        add_curves = QPushButton("Add Curve Table")
        add_curves.setObjectName("add_curve_table")
        add_curves.clicked.connect(lambda: self.add_curve_table())
        self.import_las_button = QPushButton(IMPORT_LAS_TEXT)
        self.import_las_button.setObjectName("import_las")
        self.import_las_button.clicked.connect(lambda: self.import_las())
        curve_buttons = QHBoxLayout()
        curve_buttons.addWidget(add_curves)
        curve_buttons.addWidget(self.import_las_button)
        form.addRow(curve_buttons)
        self.curve_editors: list[CurveTableEditor] = []
        self.layer_combo.currentIndexChanged.connect(lambda _i: self._refill_borehole())
        self.id_combo.currentIndexChanged.connect(lambda _i: self._sync_import_las())
        self.log_combo.currentIndexChanged.connect(lambda _i: self._refill_log())
        if on_layer_changed is not None:
            self.layer_combo.currentIndexChanged.connect(lambda _i: on_layer_changed(self))
        self._refill_borehole()
        self._refill_log()

    def _layer(self, combo):
        return self.project.mapLayer(combo.currentData() or "")

    def _refill_borehole(self, setting: BoreholeSetting | None = None):
        layer = self._layer(self.layer_combo)
        fill_field_combo(self.id_combo, layer, setting.id_field if setting else "", False)
        fill_field_combo(self.elevation_combo, layer,
                         setting.elevation_field if setting else "")
        fill_field_combo(self.total_depth_combo, layer,
                         setting.total_depth_field if setting else "")
        for combo in (self.id_combo, self.elevation_combo, self.total_depth_combo):
            combo.setEnabled(layer is not None)
        self._sync_import_las()

    # -- LAS files -----------------------------------------------------------------------------
    def _sync_import_las(self) -> None:
        if not hasattr(self, "import_las_button"):
            return
        if self.store_path() is None:
            ok, tip = False, IMPORT_LAS_NO_STORE
        elif self._layer(self.layer_combo) is None or not field_of(self.id_combo):
            ok, tip = False, IMPORT_LAS_NO_LAYER
        else:
            ok, tip = True, IMPORT_LAS_TIP
        self.import_las_button.setEnabled(ok)
        self.import_las_button.setToolTip(tip)

    def _borehole_ids(self) -> list[str]:
        layer, field_name = self._layer(self.layer_combo), field_of(self.id_combo)
        if layer is None or not field_name:
            return []
        from qgis.core import QgsFeatureRequest
        request = QgsFeatureRequest().setFlags(QgsFeatureRequest.Flag.NoGeometry)
        request.setSubsetOfAttributes([field_name], layer.fields())
        return sorted({str(f[field_name]).strip() for f in layer.getFeatures(request)
                       if f[field_name] is not None and str(f[field_name]).strip()})

    def import_las(self) -> CurveTableEditor | None:
        """Pick LAS files, match them to this entry's boreholes, keep their curves as a new
        table in the Groundwork project and add it as this entry's curve table."""
        from qgis.PyQt.QtWidgets import QDialog, QFileDialog

        from ..store.las_table import write_las_table
        from .las_import_dialog import LasImportDialog
        from .project_actions import plugin_group
        gpkg = self.store_path()
        if gpkg is None:
            return None
        paths, _f = QFileDialog.getOpenFileNames(self, "LAS Files", "",
                                                 "LAS files (*.las *.LAS);;All files (*)")
        if not paths:
            return None
        dialog = LasImportDialog(paths, self._borehole_ids(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.entries():
            return None
        try:
            table, curves = write_las_table(gpkg, dialog.entries())
        except (OSError, RuntimeError) as exc:
            QMessageBox.warning(self, "Import LAS", f"The curves could not be saved: {exc}")
            return None
        layer = QgsVectorLayer(f"{gpkg}|layername={table}", LAS_LAYER_NAME, "ogr")
        if not layer.isValid():
            QMessageBox.warning(self, "Import LAS", f"QGIS cannot open the table {table}")
            return None
        self.project.addMapLayer(layer, False)
        plugin_group(self.project.layerTreeRoot()).addLayer(layer)
        self.vector_layers.append(layer)
        editor = self.add_curve_table()
        editor.set_layer(layer.id())
        editor.set_fields("id", "depth")
        for name, unit in curves:
            editor.check_curve(name, unit)
        return editor

    def _refill_log(self, setting: BoreholeSetting | None = None):
        layer = self._layer(self.log_combo)
        for combo, name in ((self.log_id_combo, "log_id_field"), (self.top_combo, "top_field"),
                            (self.bottom_combo, "bottom_field"),
                            (self.lithology_combo, "lithology_field")):
            fill_field_combo(combo, layer, getattr(setting, name) if setting else "")
            combo.setEnabled(layer is not None)
        self.style_button.setEnabled(layer is not None)

    def set_layer(self, layer_id: str) -> None:
        self.layer_combo.setCurrentIndex(max(0, self.layer_combo.findData(layer_id)))

    def set_log_layer(self, layer_id: str) -> None:
        self.log_combo.setCurrentIndex(max(0, self.log_combo.findData(layer_id)))

    def set_total_depth(self, field_name: str) -> None:
        self.total_depth_combo.setCurrentIndex(
            max(0, self.total_depth_combo.findData(field_name)))

    def add_curve_table(self, setting: CurveTableSetting | None = None) -> CurveTableEditor:
        editor = CurveTableEditor(self.project, self.vector_layers, self._remove_curve_table)
        if setting is not None:
            editor.load(setting)
        self.curve_editors.append(editor)
        self.curves_box.addWidget(editor)
        return editor

    def _remove_curve_table(self, editor: CurveTableEditor) -> None:
        self.curve_editors.remove(editor)
        self.curves_box.removeWidget(editor)
        editor.deleteLater()

    def load(self, setting: BoreholeSetting | None) -> None:
        if setting is None:
            return
        self.loaded = setting
        keep_missing(self.layer_combo, self.project, setting.layer_id)
        keep_missing(self.log_combo, self.project, setting.log_layer_id)
        self.set_layer(setting.layer_id)
        self.set_log_layer(setting.log_layer_id)
        self._refill_borehole(setting)
        self._refill_log(setting)
        for table in setting.curve_tables:
            self.add_curve_table(table)

    def setting(self) -> BoreholeSetting | None:
        layer_id = self.layer_combo.currentData() or ""
        log_id = self.log_combo.currentData() or ""
        if not layer_id and not log_id:
            return None
        old = self.loaded
        keep = old is not None and old.layer_id == layer_id and self._layer(self.layer_combo) is None
        keep_log = old is not None and old.log_layer_id == log_id \
            and self._layer(self.log_combo) is None
        tables = [t for t in (e.setting() for e in self.curve_editors) if t is not None]
        # the look comes from the viewer: taken as saved now (the viewer may have changed it
        # while this dialog was open), minus curves no longer set up
        kept = {curve_key(t.layer_id, c.field) for t in tables for c in t.curves}
        look = self._current_look(layer_id) or old or BoreholeSetting("", "")
        return BoreholeSetting(
            layer_id, old.id_field if keep else field_of(self.id_combo),
            old.elevation_field if keep else field_of(self.elevation_combo), log_id,
            old.log_id_field if keep_log else field_of(self.log_id_combo),
            old.top_field if keep_log else field_of(self.top_combo),
            old.bottom_field if keep_log else field_of(self.bottom_combo),
            old.lithology_field if keep_log else field_of(self.lithology_combo),
            total_depth_field=old.total_depth_field if keep
            else field_of(self.total_depth_combo),
            curve_tables=tables, column_px=look.column_px, opacity=look.opacity,
            layer_text=look.layer_text,
            section_curves=[k for k in look.section_curves if k in kept])

    def _current_look(self, layer_id: str):
        from .context_dialog import read_settings
        old_id = self.loaded.layer_id if self.loaded is not None else layer_id
        return next((b for b in read_settings(self.project).boreholes
                     if b.layer_id in (old_id, layer_id)), None)

    def missing_count(self) -> int:
        return sum(1 for c in [self.layer_combo, self.log_combo]
                   + [e.layer_combo for e in self.curve_editors] if c.currentText() == MISSING)

    def _open_style(self) -> None:
        from .borehole_style_dialog import BoreholeStyleDialog
        setting = self.setting()
        if setting is None or self._layer(self.log_combo) is None:
            return
        ids, name = self.current_boreholes()
        try:
            dlg = BoreholeStyleDialog(self.project, setting, ids,
                                      self.on_styled or (lambda: None), self, name)
        except ValueError as exc:
            QMessageBox.warning(self, "Borehole style", str(exc))
            return
        dlg.exec()
        dlg.deleteLater()


class BoreholeEntries(QWidget):
    """The borehole entries: a list on the left, the selected entry's editor on the right."""

    def __init__(self, project, vector_layers, point_layers,
                 current_boreholes: Callable[[], tuple] = lambda: ([], ""), on_styled=None,
                 store_path: Callable[[], object] = lambda: None):
        super().__init__()
        self.store_path = store_path
        self.project, self.vector_layers, self.point_layers = project, vector_layers, point_layers
        self.current_boreholes, self.on_styled = current_boreholes, on_styled
        self.list = QListWidget()
        self.list.setMaximumWidth(180)
        self.stack = QStackedWidget()
        add, remove = QPushButton("Add"), QPushButton("Remove")
        add.clicked.connect(lambda: self.add_entry())
        remove.clicked.connect(self.remove_current)
        left = QVBoxLayout()
        left.addWidget(self.list)
        buttons = QHBoxLayout()
        buttons.addWidget(add)
        buttons.addWidget(remove)
        left.addLayout(buttons)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addLayout(left)
        row.addWidget(self.stack, 1)
        self.list.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.groups: list[BoreholeGroup] = []
        self.add_entry()

    def count(self) -> int:
        return len(self.groups)

    def current(self) -> BoreholeGroup:
        return self.groups[max(0, self.list.currentRow())]

    def _label(self, group: BoreholeGroup) -> str:
        text = group.layer_combo.currentText()
        return text if group.layer_combo.currentData() else "(new entry)"

    def _relabel(self, group: BoreholeGroup) -> None:
        if group in self.groups:
            self.list.item(self.groups.index(group)).setText(self._label(group))

    def add_entry(self, setting: BoreholeSetting | None = None) -> BoreholeGroup:
        group = BoreholeGroup(self.project, self.vector_layers, self.point_layers,
                              self.current_boreholes, self.on_styled, self._relabel,
                              store_path=self.store_path)
        group.load(setting)
        self.groups.append(group)
        self.stack.addWidget(group)
        self.list.addItem(self._label(group))
        self.list.setCurrentRow(len(self.groups) - 1)
        return group

    def remove_current(self) -> None:
        if not self.groups:
            return
        i = max(0, self.list.currentRow())
        group = self.groups.pop(i)
        self.stack.removeWidget(group)
        group.deleteLater()
        self.list.takeItem(i)
        if not self.groups:
            self.add_entry()

    def load(self, entries: list[BoreholeSetting]) -> None:
        for group in list(self.groups):
            self.stack.removeWidget(group)
            group.deleteLater()
        self.groups.clear()
        self.list.clear()
        for entry in entries:
            self.add_entry(entry)
        if not self.groups:
            self.add_entry()
        self.list.setCurrentRow(0)

    def entries(self) -> list[BoreholeSetting]:
        return [s for s in (g.setting() for g in self.groups) if s is not None]

    def missing_count(self) -> int:
        return sum(g.missing_count() for g in self.groups)
