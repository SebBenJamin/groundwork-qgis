"""The 'Boreholes' group of the context dialog: the borehole point layer with its id and
elevation fields, and the log table (any layer, also non-spatial) with its field mapping."""
from __future__ import annotations

from qgis.core import QgsVectorLayer
from qgis.PyQt.QtWidgets import QComboBox, QFormLayout, QGroupBox

from ..core.context_settings import BoreholeSetting

NONE = "None"
MISSING = "(not in project)"


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


class BoreholeGroup(QGroupBox):
    def __init__(self, project, vector_layers: list[QgsVectorLayer], point_layers):
        super().__init__("Boreholes")
        self.project = project
        self.loaded = None                  # the saved setting, kept for layers now missing
        self.layer_combo = QComboBox()
        self.id_combo = QComboBox()
        self.elevation_combo = QComboBox()
        self.log_combo = QComboBox()
        self.log_id_combo = QComboBox()
        self.top_combo = QComboBox()
        self.bottom_combo = QComboBox()
        self.lithology_combo = QComboBox()
        fill_layer_combo(self.layer_combo, point_layers)
        fill_layer_combo(self.log_combo, vector_layers)
        form = QFormLayout(self)
        form.addRow("Borehole layer", self.layer_combo)
        form.addRow("Borehole id field", self.id_combo)
        form.addRow("Ground elevation field", self.elevation_combo)
        form.addRow("Log table", self.log_combo)
        form.addRow("Log: borehole id field", self.log_id_combo)
        form.addRow("Log: top depth field", self.top_combo)
        form.addRow("Log: bottom depth field", self.bottom_combo)
        form.addRow("Log: lithology field", self.lithology_combo)
        self.layer_combo.currentIndexChanged.connect(lambda _i: self._refill_borehole())
        self.log_combo.currentIndexChanged.connect(lambda _i: self._refill_log())
        self._refill_borehole()
        self._refill_log()

    def _layer(self, combo):
        return self.project.mapLayer(combo.currentData() or "")

    def _refill_borehole(self, setting: BoreholeSetting | None = None):
        layer = self._layer(self.layer_combo)
        fill_field_combo(self.id_combo, layer, setting.id_field if setting else "", False)
        fill_field_combo(self.elevation_combo, layer,
                         setting.elevation_field if setting else "")
        for combo in (self.id_combo, self.elevation_combo):
            combo.setEnabled(layer is not None)

    def _refill_log(self, setting: BoreholeSetting | None = None):
        layer = self._layer(self.log_combo)
        for combo, name in ((self.log_id_combo, "log_id_field"), (self.top_combo, "top_field"),
                            (self.bottom_combo, "bottom_field"),
                            (self.lithology_combo, "lithology_field")):
            fill_field_combo(combo, layer, getattr(setting, name) if setting else "")
            combo.setEnabled(layer is not None)

    def set_layer(self, layer_id: str) -> None:
        self.layer_combo.setCurrentIndex(max(0, self.layer_combo.findData(layer_id)))

    def set_log_layer(self, layer_id: str) -> None:
        self.log_combo.setCurrentIndex(max(0, self.log_combo.findData(layer_id)))

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

    def setting(self) -> BoreholeSetting | None:
        layer_id = self.layer_combo.currentData() or ""
        log_id = self.log_combo.currentData() or ""
        if not layer_id and not log_id:
            return None
        old = self.loaded
        keep = old is not None and old.layer_id == layer_id and self._layer(self.layer_combo) is None
        keep_log = old is not None and old.log_layer_id == log_id             and self._layer(self.log_combo) is None
        return BoreholeSetting(
            layer_id, old.id_field if keep else field_of(self.id_combo),
            old.elevation_field if keep else field_of(self.elevation_combo), log_id,
            old.log_id_field if keep_log else field_of(self.log_id_combo),
            old.top_field if keep_log else field_of(self.top_combo),
            old.bottom_field if keep_log else field_of(self.bottom_combo),
            old.lithology_field if keep_log else field_of(self.lithology_combo))

    def missing_count(self) -> int:
        return sum(1 for c in (self.layer_combo, self.log_combo)
                   if c.currentText() == MISSING)
