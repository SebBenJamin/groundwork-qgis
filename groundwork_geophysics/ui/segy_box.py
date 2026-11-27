"""'SEG-Y Section': how the samples of a SEG-Y file are read (time or depth, the sample step),
hung (velocity, where time zero lies) and how its traces are placed along the profile (the
positions in its headers, a trace spacing, or a coordinate file).

Used by Add Data, and by Dataset Info with its vertical rows only (``vertical_only``). The box
knows the file only through ``readers.segy`` (``SegyInfo``, trace numbers for a coordinate
file). ``set_info`` / ``set_options`` are silent; ``changed`` follows every edit by the user
(typed numbers on ``editingFinished`` only). Numbers are typed and shown in QGIS's locale; a
decimal comma always works."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.gui import QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont, QFontDatabase, QKeySequence, QShortcut
from qgis.PyQt.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QDialog,
                                 QDialogButtonBox, QGridLayout, QGroupBox,
                                 QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
                                 QRadioButton, QSizePolicy, QTableWidget, QTableWidgetItem,
                                 QVBoxLayout, QWidget)

from ..core.numbers import fmt_trim
from ..core.trace_section import TraceSection, Velocity, sample_depths
from ..readers import segy
from .trace_fields import (NO_CRS, NO_DATUM, NO_SPACING, ZERO_ITEMS, CoordinateFile,
                           split_rows, zero_combo)
from .trace_fields import note as _note
from .trace_fields import number as _number
from .trace_fields import positive as _positive
from .trace_fields import row as _row
from .trace_fields import show as _show

TITLE = "SEG-Y Section"
WGS84 = "EPSG:4326"
FIELD_WORDS = {"cdp": "CDP", "source": "Source", "group": "Group (receiver)"}
KIND_ITEMS = (("Average", "average"), ("Interval", "interval"), ("RMS (stacking)", "rms"))
NO_POSITIONS_TIP = "The file has no positions that change along the line"
LINE_METRES = ("The positions in this file look like distances along the line, not map "
               "coordinates.")
DEPTH_GROUND_TIP = ("Only a time section can be corrected to the ground; hang a depth section "
                    "on the ground line or at a fixed height")
CHECK_STEP = "Check the sample step: the file does not say it is in metres."
STEP_SAID = "The file says {step} ms."
STEP_NUMBER = "The file's number is {step}, read as metres."
PASTE_TIP = ("Times in ms and velocities in m/s; paste rows with Ctrl+V (tab, semicolon or "
             "comma between the columns)")
# problems, in the user's words
NO_VELOCITY = "Enter the velocity in m/s."
NO_DEPTH_DATUM = "Enter the height of depth zero."
NO_STEP = "The sample step must be greater than 0."
NO_REPLACEMENT = "Enter the replacement velocity in m/s."
FEW_ROWS = "Enter at least two rows of time and velocity."
TIMES_UP = "The times must increase."
VELOCITIES_UP = "The velocities must be greater than 0."
# warnings, not blocks
UNUSUAL_VELOCITY = ("A velocity below 300 m/s or above 8000 m/s is unusual for seismic data. "
                    "Check the unit (m/s).")
SHORT_FUNCTION = ("The velocity function ends at {t} ms; the record is {T} ms long. Below it "
                  "the last velocity is used.")
PLAUSIBLE = (300.0, 8000.0)                     # m/s
TEXT_TITLE = "Text Header"
def _coord(v: float, geographic: bool) -> str:
    """A position for recognising the field: degrees to 6 decimals, map coordinates to the
    metre (to 0.1 m when small, as in files that give metres along the line)."""
    if geographic:
        return fmt_trim(v, 6)
    return fmt_trim(v, 0 if abs(v) >= 1000 else 1)


class TextHeaderDialog(QDialog):
    """The file's 40 text-header lines, read-only, in a monospace font."""

    def __init__(self, text: str, parent=None, name: str = ""):
        super().__init__(parent)
        self.setWindowTitle(f"{TEXT_TITLE} – {name}" if name else TEXT_TITLE)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        font.setFixedPitch(True)
        font.setFamilies([font.family(), "Consolas", "Courier New", "DejaVu Sans Mono"])
        view.setFont(font)
        width = view.fontMetrics().horizontalAdvance("M" * 82)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(view)
        layout.addWidget(buttons)
        screen = self.screen().availableGeometry()
        self.resize(min(width + 60, screen.width() - 40), min(560, screen.height() - 80))


class SegyBox(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, vertical_only: bool = False, parent=None):
        super().__init__(TITLE, parent)
        self.setObjectName("segy_box")
        self.vertical_only = vertical_only
        self.info: segy.SegyInfo | None = None
        self.path = ""                              # the SEG-Y file ("" when not known)
        self._busy = False
        self._numbers = self._numbers_for = None    # the file's trace numbers (table use)
        self._position_chosen = False               # the user (or set_options) chose it
        self._crs_chosen: QgsCoordinateReferenceSystem | None = None
        prj = QgsProject.instance().crs()
        self._default_crs = prj if prj.isValid() else QgsCoordinateReferenceSystem()
        self.text_dialog = None
        self._busy = True                           # no slot runs before the rows exist
        self._build()
        self._busy = False
        self._sync()

    # -- building ----------------------------------------------------------------------------
    def _build(self) -> None:
        def radios(*texts):
            group = QButtonGroup(self)
            out = []
            for text in texts:
                r = QRadioButton(text)
                group.addButton(r)
                r.toggled.connect(lambda on: on and self._edited())
                out.append(r)
            out[0].setChecked(True)
            return out

        def edit(name: str, tip: str) -> QLineEdit:
            e = QLineEdit()
            e.setObjectName(name)
            e.setToolTip(tip)
            e.editingFinished.connect(self._edited)
            return e

        self.time_radio, self.depth_radio = radios("Time", "Depth")
        self.step_edit = edit("step_edit", "Time (or depth) between two samples; filled in "
                                           "from the file")
        self.step_note = _note("step_note")
        self.step_edit.textChanged.connect(self._sync_step_note)
        self.by_one, self.by_function = radios("One velocity", "Velocity function")
        self.velocity_edit = edit("velocity_edit", "Velocity that turns two-way time into "
                                                   "depth, in m/s; Groundwork assumes none")
        self.velocity_edit.setPlaceholderText("m/s")
        self.velocity_table = QTableWidget(0, 2)
        self.velocity_table.setObjectName("velocity_table")
        self.velocity_table.setHorizontalHeaderLabels(["Time (ms)", "Velocity (m/s)"])
        self.velocity_table.verticalHeader().hide()
        self.velocity_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)
        self.velocity_table.setSelectionMode(QAbstractItemView.SelectionMode.ContiguousSelection)
        self.velocity_table.setToolTip(PASTE_TIP)
        self.velocity_table.verticalHeader().setDefaultSectionSize(
            self.fontMetrics().height() + 6)
        row = self.fontMetrics().height() + 6       # five rows in view, then it scrolls
        self.velocity_table.setMinimumHeight(6 * row + 4)
        self.velocity_table.setMaximumHeight(7 * row + 4)
        self.velocity_table.itemChanged.connect(lambda *_a: self._edited())
        paste = QShortcut(QKeySequence(QKeySequence.StandardKey.Paste), self.velocity_table)
        paste.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        paste.activated.connect(self._paste_clipboard)
        self.add_row_button = QPushButton("Add Row")
        self.add_row_button.setToolTip("Add a row of time and velocity")
        self.add_row_button.clicked.connect(self._add_row)
        self.remove_row_button = QPushButton("Remove Row")
        self.remove_row_button.setToolTip("Remove the selected rows")
        self.remove_row_button.clicked.connect(self._remove_rows)
        self.kind_combo = QComboBox()
        self.kind_combo.setObjectName("velocity_kind_combo")
        for text, value in KIND_ITEMS:
            self.kind_combo.addItem(text, value)
        self.kind_combo.setToolTip("Average: from time zero down to each time. Interval: "
                                   "from each row's time down to the next row's. RMS: "
                                   "stacking velocities, turned into interval velocities.")
        self.kind_combo.currentIndexChanged.connect(lambda *_a: self._edited())
        self.zero_combo = zero_combo("segy_zero_combo", tuple(v for _t, v in ZERO_ITEMS),
                                     self._edited)
        self.datum_edit = edit("datum_edit", "Height of time zero above sea level (the "
                                             "processing datum), in m")
        self.replacement_edit = edit("replacement_edit",
                                     "Velocity between the datum and the ground, in m/s")

        self.by_positions, self.by_spacing, self.by_table = radios(
            "Positions in the file", "Trace spacing", "A coordinate file")
        self.by_spacing.setChecked(True)
        for r in (self.by_positions, self.by_spacing, self.by_table):
            r.clicked.connect(self._position_clicked)
        self.field_combo = QComboBox()
        self.field_combo.setObjectName("segy_field_combo")
        self.field_combo.setToolTip("Header fields that hold the trace positions: first and "
                                    "last trace")
        self.field_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.field_combo.currentIndexChanged.connect(lambda *_a: self._edited())
        self.crs_widget = QgsProjectionSelectionWidget()
        self.crs_widget.setObjectName("segy_crs")
        self.crs_widget.setToolTip("Coordinate reference system of the trace positions")
        self.crs_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.crs_widget.crsChanged.connect(self._crs_edited)
        self.spacing_edit = edit("spacing_edit", "Distance between two traces along the line")
        self.coords = CoordinateFile(self, "segy", self._trace_numbers, lambda: self.path,
                                     lambda: self._busy)
        self.coords.chosen.connect(self._table_chosen)
        self.coords.changed.connect(self._edited)
        self.table_file, self.table_options = self.coords.file, self.coords.options_box
        self.number_combo, self.easting_combo, self.northing_combo = (
            self.coords.number_combo, self.coords.easting_combo, self.coords.northing_combo)
        self.table_note = self.coords.note
        self.position_note = _note("position_note")
        self.text_button = QPushButton("Text Header…")
        self.text_button.setToolTip("The 40 lines of text at the start of the file")
        self.text_button.clicked.connect(self.show_text)

        self._velocity_row = _row(self.by_one, self.by_function, self.velocity_edit)
        self._function_row = QWidget()
        f = QGridLayout(self._function_row)
        f.setContentsMargins(0, 0, 0, 0)
        f.addWidget(self.velocity_table, 0, 0, 3, 1)
        f.addWidget(self.add_row_button, 0, 1)
        f.addWidget(self.remove_row_button, 1, 1)
        f.setColumnStretch(0, 1)
        self._kind_row = _row(self.kind_combo)
        self._datum_row = _row(self.datum_edit)
        self._replacement_row = _row(self.replacement_edit)
        self._columns_row = self.coords.columns_row
        self._position_row = _row(self.by_positions, self.by_spacing, self.by_table)
        # the text header stays in reach while velocity and height are typed from it
        samples_row = _row(self.time_radio, self.depth_radio)
        samples_row.layout().addWidget(self.text_button)
        rows = (("samples", "Samples are", samples_row),
                ("step", "Sample step (ms)", _row(self.step_edit)),
                ("step_note", "", self.step_note),
                ("velocity", "Velocity (m/s)", self._velocity_row),
                ("function", "", self._function_row),
                ("kind", "Velocities are", self._kind_row),
                ("zero", "Time zero is", _row(self.zero_combo)),
                ("datum", "Height of time zero (m)", self._datum_row),
                ("replacement", "Replacement velocity (m/s)", self._replacement_row),
                ("position", "Traces are placed by", self._position_row),
                ("position_note", "", self.position_note),
                ("field", "Position fields", _row(self.field_combo)),
                ("table_file", "Coordinate file", self.table_file),
                ("table_options", "", self.table_options),
                ("columns", "", self._columns_row),
                ("table_note", "", self.table_note),
                ("crs", "CRS", self.crs_widget),
                ("spacing", "Trace spacing (m)", _row(self.spacing_edit)))
        grid = QGridLayout(self)
        grid.setColumnStretch(1, 1)
        self._rows: dict[str, tuple[QLabel, QWidget]] = {}
        for r, (name, text, widget) in enumerate(rows):
            label = QLabel(text)
            grid.addWidget(label, r, 0)
            grid.addWidget(widget, r, 1)
            self._rows[name] = (label, widget)
        chain = (self.time_radio, self.depth_radio, self.text_button, self.step_edit, self.by_one,
                 self.by_function, self.velocity_edit, self.velocity_table, self.add_row_button,
                 self.remove_row_button, self.kind_combo, self.zero_combo, self.datum_edit,
                 self.replacement_edit, self.by_positions, self.by_spacing, self.by_table,
                 self.field_combo, self.table_file, self.number_combo, self.easting_combo,
                 self.northing_combo, self.crs_widget, self.spacing_edit)
        for first, second in zip(chain, chain[1:]):      # in the order the rows are shown
            QWidget.setTabOrder(first, second)
        self.step_label = self._rows["step"][0]
        self.zero_label = self._rows["zero"][0]

    # -- in ------------------------------------------------------------------------------------
    def set_default_crs(self, crs: QgsCoordinateReferenceSystem) -> None:
        """The CRS offered for positions that are not degrees (normally the project's)."""
        self._default_crs = QgsCoordinateReferenceSystem(crs)
        self._preset_crs()

    def set_info(self, info: segy.SegyInfo, path: str | None = None) -> None:
        """Show what the headers of ``path`` say: its sample step, a velocity it states, its
        position fields; the user's other choices stay, but the CRS and the height of time
        zero belong to a file and start afresh with another one. Position fields that look
        like distances along the line (``SegyInfo.flat``) are not proposed. Silent."""
        new_file = str(path or "") != self.path
        self.info, self.path = info, str(path or "")
        self._numbers = self._numbers_for = None
        self.coords.forget()
        self._busy = True
        try:
            if new_file:
                self._crs_chosen = None
                self.datum_edit.clear()
            self.velocity_edit.setText(_show(info.velocity, 1) if info.velocity else "")
            self.step_edit.setText(_show(info.step * 1000.0) if info.step > 0 else "")
            current = self.field_combo.currentData()
            self.field_combo.clear()
            for name, ((x0, y0), (x1, y1)) in info.positions.items():
                g = info.geographic
                self.field_combo.addItem(
                    f"{FIELD_WORDS.get(name, name)}  {_coord(x0, g)} / {_coord(y0, g)} → "
                    f"{_coord(x1, g)} / {_coord(y1, g)}", name)
            proposed = self._proposed()
            if current not in info.positions or (current not in proposed and proposed):
                current = proposed[0] if proposed else None
            self.field_combo.setCurrentIndex(max(0, self.field_combo.findData(current)))
            has = bool(info.positions)
            self.by_positions.setEnabled(has)
            self.by_positions.setToolTip("" if has else NO_POSITIONS_TIP)
            if not has and self.by_positions.isChecked():
                self.by_spacing.setChecked(True)
            elif has and not self._position_chosen:
                (self.by_positions if proposed else self.by_spacing).setChecked(True)
            self._preset_crs()
            if self.table_file.filePath():
                self.coords.read_columns(keep=True)
        finally:
            self._busy = False
        self._sync()

    def _proposed(self) -> list[str]:
        """The file's position fields that may hold map coordinates (X and Y both change)."""
        if self.info is None:
            return []
        return [n for n in self.info.positions if n not in (self.info.flat or ())]

    def position_warning(self) -> str:
        """What to warn about the chosen positions: a field that looks like distances along
        the line, chosen by hand ("" otherwise)."""
        if self.vertical_only or self.position() != "map" or self.info is None:
            return ""
        return LINE_METRES if self.field_combo.currentData() in (self.info.flat or ()) else ""

    def _position_note(self) -> str:
        """The note under the position rows when no field is proposed for that reason."""
        if self.vertical_only or self.info is None or not self.info.positions or \
                self._proposed() or self.position() == "map":
            return ""
        return LINE_METRES

    def _preset_crs(self) -> None:
        geographic = self.info is not None and self.info.geographic
        crs = QgsCoordinateReferenceSystem(WGS84) if geographic else \
            (self._crs_chosen or self._default_crs)
        was, self._busy = self._busy, True
        self.crs_widget.setCrs(crs)
        self._busy = was

    def set_options(self, options: dict) -> None:
        """Show stored options; keys that are missing keep what is shown. Silent."""
        o = options or {}
        self._busy = True
        try:
            if o.get("domain") in ("time", "depth"):
                (self.depth_radio if o["domain"] == "depth" else self.time_radio).setChecked(True)
            if o.get("sample_step") is not None:
                step = float(o["sample_step"])
                self.step_edit.setText(_show(step if self.domain() == "depth" else step * 1000))
            if o.get("velocity") is not None:
                self.velocity_edit.setText(_show(float(o["velocity"]), 3))
                self.by_one.setChecked(True)
            if o.get("velocity_table"):
                self._fill_table([(float(t) * 1000.0, float(v)) for t, v in o["velocity_table"]])
                self.by_function.setChecked(True)
            if o.get("velocity_kind"):
                self.kind_combo.setCurrentIndex(max(0, self.kind_combo.findData(
                    o["velocity_kind"])))
            if o.get("zero"):
                self.zero_combo.setCurrentIndex(max(0, self.zero_combo.findData(o["zero"])))
            if o.get("datum") is not None:
                self.datum_edit.setText(_show(float(o["datum"]), 3))
            if o.get("replacement_velocity") is not None:
                self.replacement_edit.setText(_show(float(o["replacement_velocity"]), 3))
            if not self.vertical_only:
                self._set_placement(o)
        finally:
            self._busy = False
        self._sync()

    def _set_placement(self, o: dict) -> None:
        position = o.get("position")
        if position == "map" and self.by_positions.isEnabled() and \
                (self._proposed() or self.info is None):
            self.by_positions.setChecked(True)
            self._position_chosen = True
        elif position == "table":
            self.by_table.setChecked(True)
        elif position == "spacing":
            self.by_spacing.setChecked(True)
        self._position_chosen = self._position_chosen or position in ("table", "spacing")
        if o.get("spacing") is not None:
            self.spacing_edit.setText(_show(float(o["spacing"]), 3))
        if o.get("xy_field"):
            i = self.field_combo.findData(o["xy_field"])
            if i >= 0:
                self.field_combo.setCurrentIndex(i)
        if o.get("crs"):
            self._crs_chosen = QgsCoordinateReferenceSystem(str(o["crs"]))
            self._preset_crs()
        if o.get("positions_file"):
            self.coords.set_options(o)

    def set_domain(self, domain: str) -> None:
        (self.depth_radio if domain == "depth" else self.time_radio).setChecked(True)

    def set_zero(self, zero: str) -> None:
        i = self.zero_combo.findData(zero)
        if i >= 0:
            self.zero_combo.setCurrentIndex(i)
        self._sync()

    # -- out -----------------------------------------------------------------------------------
    def domain(self) -> str:
        return "depth" if self.depth_radio.isChecked() else "time"

    def zero(self) -> str:
        return self.zero_combo.currentData()

    def position(self) -> str:
        if self.by_positions.isChecked():
            return "map"
        return "table" if self.by_table.isChecked() else "spacing"

    def _file_step(self) -> float | None:
        """The step the file gives, as the field shows it (ms for time, m for depth)."""
        if self.info is None or self.info.step <= 0:
            return None
        return self.info.step * 1000.0

    def _step_changed(self) -> bool:
        typed, given = _number(self.step_edit.text()), self._file_step()
        if typed is None:
            return given is None and bool(self.step_edit.text().strip())
        return given is None or abs(typed - given) > 1e-9 * max(1.0, abs(given))

    def _step(self) -> float | None:
        """The sample step in the section's unit (s or m), None when unusable."""
        typed = _positive(self.step_edit.text())
        if typed is None:
            return None
        return typed if self.domain() == "depth" else typed / 1000.0

    def _function_rows(self) -> list[tuple[float | None, float | None]]:
        rows = []
        t = self.velocity_table
        for r in range(t.rowCount()):
            cells = [(t.item(r, c).text() if t.item(r, c) else "").strip() for c in (0, 1)]
            if not any(cells):
                continue
            rows.append((_number(cells[0]), _number(cells[1])))
        return rows

    def _function(self) -> list[list[float]] | None:
        rows = self._function_rows()
        if any(t is None or v is None for t, v in rows):
            return None
        return [[t / 1000.0, v] for t, v in rows]

    def options(self) -> dict:
        """The reader options (Task 3's keys) and the hanging (``velocity``, ``zero``, …);
        only the keys that apply, and only values that can be read."""
        o: dict = {}
        if not self.vertical_only:
            o.update(self._placement_options())
        o["domain"] = self.domain()
        if self._step_changed():
            step = self._step()
            if step is not None:
                o["sample_step"] = step
        if self.domain() == "time":
            if self.by_function.isChecked():
                table = self._function()
                if table:
                    o["velocity_table"] = table
                o["velocity_kind"] = self.kind_combo.currentData()
            else:
                v = _positive(self.velocity_edit.text())
                if v is not None:
                    o["velocity"] = v
        o["zero"] = self.zero()
        if o["zero"] != "ground":
            datum = _number(self.datum_edit.text())
            if datum is not None:
                o["datum"] = datum
        if o["zero"] == "datum_ground":
            rv = _positive(self.replacement_edit.text())
            if rv is not None:
                o["replacement_velocity"] = rv
        return o

    def _crs_text(self) -> str:
        crs = self.crs_widget.crs()
        if not crs.isValid():
            return ""
        return crs.authid() or "WKT:" + crs.toWkt()

    def _placement_options(self) -> dict:
        position = self.position()
        o: dict = {"position": position}
        if position == "spacing":
            spacing = _positive(self.spacing_edit.text())
            if spacing is not None:
                o["spacing"] = spacing
            return o
        if position == "map":
            if self.field_combo.currentData():
                o["xy_field"] = self.field_combo.currentData()
        else:
            o.update(self.coords.options())
        crs = self._crs_text()
        if crs:
            o["crs"] = crs
        return o

    def problems(self) -> list[str]:
        """What must be entered before the section can be read and hung."""
        return self.read_problems() + self.hang_problems()

    def read_problems(self) -> list[str]:
        """What the file cannot be read without: the sample step and the trace positions."""
        out = [] if self._step() is not None else [NO_STEP]
        if not self.vertical_only:
            out += self._placement_problems()
        return out

    def hang_problems(self) -> list[str]:
        """What the section cannot be hung without: velocity, height of time zero."""
        out = self._velocity_problems() if self.domain() == "time" else []
        if self.zero() != "ground" and _number(self.datum_edit.text()) is None:
            out.append(NO_DEPTH_DATUM if self.domain() == "depth" else NO_DATUM)
        if self.zero() == "datum_ground" and _positive(self.replacement_edit.text()) is None:
            out.append(NO_REPLACEMENT)
        return out

    def warnings(self) -> list[str]:
        """What looks unusual in the velocity, without stopping the section: a velocity
        outside 300–8000 m/s (a unit typed wrong), a function that ends in the upper half of
        the record."""
        if self.domain() != "time":
            return []
        lo, hi = PLAUSIBLE
        if not self.by_function.isChecked():
            v = _positive(self.velocity_edit.text())
            return [UNUSUAL_VELOCITY] if v is not None and not lo <= v <= hi else []
        rows = [(t, v) for t, v in self._function_rows() if t is not None and v is not None]
        out = [UNUSUAL_VELOCITY] if any(v > 0 and not lo <= v <= hi for _t, v in rows) else []
        step = self._step()
        if rows and self.info is not None and step is not None:
            end_ms = (self.info.first + (max(1, self.info.n_samples) - 1) * step) * 1000.0
            last_ms = max(t for t, _v in rows)
            if last_ms < end_ms / 2:
                out.append(SHORT_FUNCTION.format(t=f"{last_ms:.0f}", T=f"{end_ms:.0f}"))
        return out

    def _velocity_problems(self) -> list[str]:
        if not self.by_function.isChecked():
            return [] if _positive(self.velocity_edit.text()) is not None else [NO_VELOCITY]
        rows = self._function_rows()
        if len(rows) < 2 or any(t is None or v is None for t, v in rows):
            return [FEW_ROWS]
        times = np.array([t for t, _v in rows])
        if (np.array([v for _t, v in rows]) <= 0).any():
            return [VELOCITIES_UP]
        if (np.diff(times) <= 0).any():
            return [TIMES_UP]
        if self.info is None or self._step() is None:
            return []
        trial = TraceSection(np.zeros((1, max(1, self.info.n_samples)), np.float32), [0.0],
                             self.info.first, self._step(), "time")
        try:
            sample_depths(trial, Velocity.from_options(self.options()))
        except ValueError as exc:
            return [str(exc)]
        return []

    def _placement_problems(self) -> list[str]:
        position = self.position()
        if position == "spacing":
            return [] if _positive(self.spacing_edit.text()) is not None else [NO_SPACING]
        out = []
        if position == "table":
            out += self.coords.problems()
        if not self.crs_widget.crs().isValid():
            out.append(NO_CRS)
        return out

    # -- the coordinate file -------------------------------------------------------------------
    def set_positions_file(self, path: str) -> None:
        """Use the coordinate file ``path`` (as if chosen): its layout and columns guessed."""
        self.coords.set_file(path)

    def _table_chosen(self) -> None:
        self._busy = True
        try:
            self.by_table.setChecked(True)
            self._position_chosen = True
        finally:
            self._busy = False
        self._edited()

    def _trace_numbers(self) -> np.ndarray | None:
        if self.info is None:
            return None
        if not self.info.numbers_from_cdp:
            return np.arange(1, self.info.n_traces + 1)
        if self._numbers_for != self.path:
            self._numbers_for = self.path
            try:
                self._numbers = segy.trace_numbers(self.path)
            except (OSError, ValueError):
                self._numbers = None
        return self._numbers

    # -- the velocity function -----------------------------------------------------------------
    def _fill_table(self, rows) -> None:
        t = self.velocity_table
        t.blockSignals(True)
        t.setRowCount(0)
        for time_ms, v in rows:
            self._append_row(_show(time_ms, 3), _show(v, 3))
        t.blockSignals(False)

    def _append_row(self, time_text: str = "", velocity_text: str = "") -> None:
        t = self.velocity_table
        r = t.rowCount()
        t.insertRow(r)
        t.setItem(r, 0, QTableWidgetItem(time_text))
        t.setItem(r, 1, QTableWidgetItem(velocity_text))

    def _add_row(self) -> None:
        self.velocity_table.blockSignals(True)
        self._append_row()
        self.velocity_table.blockSignals(False)
        self.velocity_table.setCurrentCell(self.velocity_table.rowCount() - 1, 0)
        self._edited()

    def _remove_rows(self) -> None:
        t = self.velocity_table
        rows = sorted({i.row() for i in t.selectedIndexes()} or
                      ({t.currentRow()} if t.currentRow() >= 0 else set()), reverse=True)
        t.blockSignals(True)
        for r in rows:
            t.removeRow(r)
        t.blockSignals(False)
        self._edited()

    def _paste_clipboard(self) -> None:
        from qgis.PyQt.QtWidgets import QApplication
        self.paste_rows(QApplication.clipboard().text())

    def paste_rows(self, text: str) -> None:
        """Rows of time (ms) and velocity (m/s) pasted as text: empty rows of the table are
        dropped, the pasted ones added at the end. Numbers are shown in QGIS's locale."""
        t = self.velocity_table
        t.blockSignals(True)
        for r in reversed(range(t.rowCount())):
            if not any((t.item(r, c).text() if t.item(r, c) else "").strip() for c in (0, 1)):
                t.removeRow(r)
        for cells in split_rows(text):
            cells = (cells + ["", ""])[:2]
            shown = [(_show(v, 3) if (v := _number(c)) is not None else c) for c in cells]
            self._append_row(*shown)
        t.blockSignals(False)
        self._edited()

    # -- state ---------------------------------------------------------------------------------
    def _crs_edited(self, *_args) -> None:
        if self._busy:
            return
        self._crs_chosen = QgsCoordinateReferenceSystem(self.crs_widget.crs())
        self._edited()

    def _position_clicked(self, *_args) -> None:
        self._position_chosen = True

    def _sync_step_note(self, *_args) -> None:
        if not hasattr(self, "_rows"):
            return
        self.step_note.setText(self._step_note())
        self._rows["step_note"][1].setVisible(bool(self.step_note.text()))

    def _edited(self, *_args) -> None:
        if self._busy:
            return
        if self.by_function.isChecked() and self.velocity_table.rowCount() == 0:
            self.velocity_table.blockSignals(True)
            self._append_row()
            self._append_row()
            self.velocity_table.blockSignals(False)
        self._sync()
        self.changed.emit()

    def _sync(self) -> None:
        depth = self.domain() == "depth"
        model = self.zero_combo.model()
        ground_item = model.item(self.zero_combo.findData("datum_ground"))
        ground_item.setEnabled(not depth)
        ground_item.setToolTip(DEPTH_GROUND_TIP if depth else "")
        if depth and self.zero() == "datum_ground":
            self.zero_combo.blockSignals(True)
            self.zero_combo.setCurrentIndex(self.zero_combo.findData("datum"))
            self.zero_combo.blockSignals(False)
        function = self.by_function.isChecked()
        position = self.position()
        place = not self.vertical_only
        shown = {
            "samples": True, "step": True, "step_note": True,
            "velocity": not depth, "function": not depth and function,
            "kind": not depth and function,
            "zero": True, "datum": self.zero() != "ground",
            "replacement": self.zero() == "datum_ground",
            "position": place, "position_note": place and bool(self._position_note()),
            "field": place and position == "map",
            "table_file": place and position == "table",
            "table_options": place and position == "table",
            "columns": place and position == "table",
            "table_note": place and position == "table",
            "crs": place and position in ("map", "table"),
            "spacing": place and position == "spacing"}
        for name, on in shown.items():
            label, widget = self._rows[name]
            label.setVisible(on and bool(label.text()))
            widget.setVisible(on)
        self.velocity_edit.setVisible(not depth and not function)
        for w in (self.by_one, self.by_function):
            w.setVisible(not depth)
        for w in (self.by_positions, self.by_spacing, self.by_table, self.text_button):
            w.setVisible(place)
        self.step_label.setText("Sample step (m)" if depth else "Sample step (ms)")
        self.zero_label.setText("Depth zero is" if depth else "Time zero is")
        self._rows["datum"][0].setText("Height of depth zero (m)" if depth else
                                       "Height of time zero (m)")
        self._sync_step_note()
        self.table_note.setText(self._table_note() if shown["table_note"] else "")
        self.table_note.setVisible(bool(self.table_note.text()))
        self.position_note.setText(self._position_note() if shown["position_note"] else "")
        self.text_button.setEnabled(self.info is not None)

    def _step_note(self) -> str:
        given = self._file_step()
        if self.domain() == "depth" and not self._step_changed():
            return CHECK_STEP
        if given is not None and self._step_changed():
            return (STEP_NUMBER if self.domain() == "depth" else STEP_SAID).format(
                step=_show(given))
        return ""

    def _table_note(self) -> str:
        return self.coords.note_text(self.info.n_traces if self.info is not None else None)

    # -- the text header -----------------------------------------------------------------------
    def show_text(self) -> None:
        """The file's text header in a read-only window (one per box, raised when open)."""
        if self.info is None:
            return
        name = Path(self.path).name if self.path else ""
        if self.text_dialog is None:
            self.text_dialog = TextHeaderDialog(self.info.text, self.window(), name)
        else:
            self.text_dialog.findChild(QPlainTextEdit).setPlainText(self.info.text)
            self.text_dialog.setWindowTitle(f"{TEXT_TITLE} – {name}" if name else TEXT_TITLE)
        self.text_dialog.show()
        self.text_dialog.raise_()
