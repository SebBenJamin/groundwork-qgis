"""'Add Data' dialog: a model or data file read with its fixed format, or any other text table
read with the columns the user assigns, placed on an existing profile or on one made here
from a line, positions or the file's own map coordinates.

Shown non-modally (the placement can pick on the map). The preview reads only the first
rows of a text table; the whole file is read for the summary line when the file, its format
or the column assignment changes, never while the user types. No exception leaves a slot:
what goes wrong is shown in the preview."""
from __future__ import annotations

import functools
import json
from pathlib import Path

import numpy as np
from qgis.core import Qgis, QgsProject, QgsSettings
from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                                 QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                                 QPushButton, QRadioButton, QScrollArea, QVBoxLayout, QWidget)

from .help import add_help_button
from .. import readers
from ..core.coverage import overhang_message
from ..core.layout import model_stations
from ..core.lines import line_from_cloud
from ..core.model import Dataset
from ..core.numbers import fmt, fmt_sig, fmt_trim
from ..section.readout import format_value, unit_label
from ..core.placement import fit_report
from ..core.roles import VERTICAL_KINDS, ModelColumns, guess_model_columns
from ..ids import LEGACY_ID
from ..readers.errors import plain_error
from ..readers.text_columns import map_points
from ..readers.texttable import TableOptions, TextTable, guess_options, read_table
from ..section.placement_resolve import ProfileLayout, resolve
from .columns_box import GUESSED_HINT, REMEMBERED_HINT, ModelColumnsBox
from .fit_line import WARNING_STYLE, fit_line, show_fit
from ..core.dataset_types import METHODS, READINGS_KINDS, station_words
from .placement_widget import PlacementWidget
from .positions_source import xy_to_store
from .project_actions import (NotRefreshed, add_data, dataset_options, draft_profile,
                              read_for)
from .table_widgets import PreviewTable, TableOptionsBox

CHOOSE_OTHER = "Choose another file, or another format above."
MISSING_FILE = "Check the path, or choose another file."
Z_ITEMS = [("Choose…", None)] + list(VERTICAL_KINDS)
FILE_FILTER = ("Model and data files (*.dat *.txt *.csv *.xyz *.vtk *.data *.ohm);;"
               "All files (*)")
#: readers whose files hold readings and take a model-response file
RESPONSE_READERS = ("bert_data",)
#: response files looked for next to a data file
RESPONSE_NAMES = ("response.vector", "{stem}_response.vector", "{stem}.response",
                  "dcinv.response")
#: the last text-table settings, offered for the next file with the same columns
SETTINGS_KEY = f"{LEGACY_ID}/import/last"
PREVIEW_ROWS = 20
#: rows read for the preview and the first guess: the first rows of a model often share one
#: depth, so 20 would hide the vertical column
SAMPLE_ROWS = 1000
#: metres: cells of a map file further from the line than this are warned about
OFF_LINE = 5.0
GUESSED_ELECTRODES = ("{Words}: none in this file; guessed from the top row of cells: "
                      "{n}, about {spacing} m apart. Shown as a guess until real positions "
                      "are imported.")
NAMED_STATIONS = ("{Words}: taken from the shot and geophone points saved next to the file: "
                  "{n}, about {spacing} m apart. Shown as a guess until real positions are "
                  "imported.")
NO_STATIONS_NOTE = "No {word} positions: import them or type the spacing in Profile Properties"
METHOD_TIP = "Method of the data, and of the station set made from the positions"
READINGS_METHOD_TIP = "Measured ERT data: the method is ERT"
ERROR_STYLE = "color: #b00020;"


def guess_response(path) -> str:
    """The model-response file next to a data file, or "" when none or several fit.

    Tries the known names first, then the only ``*response*.vector`` / ``*.response``
    file in the folder (e.g. ``T3_response.vector`` next to ``T3_measured.data``).
    """
    data = Path(path)
    for pattern in RESPONSE_NAMES:
        candidate = data.parent / pattern.format(stem=data.stem)
        if candidate.is_file():
            return str(candidate)
    found = {p for p in data.parent.glob("*response*.vector") if p.is_file()}
    found |= {p for p in data.parent.glob("*.response") if p.is_file()}
    return str(found.pop()) if len(found) == 1 else ""


def describe(result: readers.ReaderResult, z_kind: str | None, sample: int = 0) -> str:
    """One-line summary of a reader result for the preview label, numbers in the QGIS
    locale; ``sample``: the result holds only the file's first ``sample`` rows."""
    mesh = result.mesh
    r = getattr(mesh, "readings", None)
    if r is not None:
        x0, x1 = float(np.nanmin(r.a)), float(np.nanmax(np.r_[r.b, r.m, r.n]))
        text = f"{len(r)} readings, electrodes x {fmt(x0)} – {fmt(x1)} m"
        if r.has_calculated:
            rms, chi2 = r.rms_percent(), r.chi2()
            text += f" · misfit RMS {fmt(rms)} %" if rms is not None else ""
            text += f", χ² {fmt(chi2, 2)}" if chi2 is not None else ""
        else:
            text += " · measured data only (add a response file for the misfit)"
        return text
    xmin, xmax, zmin, zmax = mesh.bounds()
    values = mesh.values[np.isfinite(mesh.values)]
    z_word = {"elevation": "elevation", "depth": "depth",
              "local": "local height"}.get(z_kind, "Z meaning not set")
    text = (f"{len(mesh.values)} cells · x {fmt(xmin)} – {fmt(xmax)} m, z {fmt(zmin)} – "
            f"{fmt(zmax)} m ({z_word}) · " +
            (f"values {format_value(values.min())} – {format_value(values.max())} "
             f"{unit_label(mesh.unit)}".rstrip()
             if len(values) else "no values"))
    n_masked = int(result.provenance.get("n_masked") or 0)
    if n_masked and result.provenance.get("reconstruction") == "delaunay":
        text += f" · {n_masked} fill/NaN values skipped"
    elif n_masked:
        text += f" · {n_masked} {'cell' if n_masked == 1 else 'cells'} without a value (shown blank)"
    n_skipped = int(result.provenance.get("n_skipped") or 0)
    if n_skipped:
        text += (f" · {n_skipped} {'row' if n_skipped == 1 else 'rows'} skipped "
                 f"(line {result.provenance.get('first_skipped_line')})")
    return text + (f" (first {sample} rows)" if sample else "")


def _remembered() -> dict | None:
    try:
        last = json.loads(QgsSettings().value(SETTINGS_KEY, "") or "null")
    except (TypeError, ValueError):
        return None
    return last if isinstance(last, dict) else None


def _guarded(method):
    """A slot that never raises: under PyQt6 an exception leaving a slot aborts QGIS. What
    goes wrong is shown in the preview."""
    @functools.wraps(method)
    def run(self, *args):
        try:
            return method(self, *args)
        except Exception as exc:                # noqa: BLE001 - shown, never raised
            self._show_error(plain_error(exc, self._path() or None, CHOOSE_OTHER,
                                         MISSING_FILE))
    return run


def _label(name: str) -> QLabel:
    label = QLabel()
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class AddDataDialog(QDialog):
    def __init__(self, iface, store, profile_id: str | None = None, provider=None,
                 project=None, parent=None):
        super().__init__(parent if parent is not None else iface.mainWindow())
        self.iface, self.store, self.provider = iface, store, provider
        self.project = project if project is not None else QgsProject.instance()
        self.setWindowTitle("Add Data")
        self.dataset = self.profile = None
        self.created = False                        # the profile was made here
        self.last_error = self.last_warning = None
        self._profile_id = profile_id
        self._auto_name = ""
        self._file = ""                             # the file set_file last showed
        self._table = self._table_key = None        # the first rows of a text table
        self._more = False                          # the file has more rows than the sample
        self._sets_for, self._sets = None, []       # station sets of the chosen profile
        self._pending_columns = None                # remembered assignment for the next table
        self._result = self._read_key = None        # the whole file as read
        self._z_preset = None                       # (path, reader) whose z hint is shown
        self._line_key, self._line, self._line_error = None, None, ""
        self._on_map_shown = False
        self._zero_chosen = False                   # the user chose where distance 0 lies
        self._confirm: list[str] = []               # asked before saving
        self._busy = False

        self.file_edit = QLineEdit()
        self.file_edit.editingFinished.connect(self._file_typed)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        file_row = QHBoxLayout()
        file_row.addWidget(self.file_edit)
        file_row.addWidget(browse)
        self.name_edit = QLineEdit()
        self.name_edit.setToolTip("Name of the dataset, and of the profile when one is made")
        self.format_combo = QComboBox()
        self.format_combo.setObjectName("format_combo")
        for name in readers.names():
            self.format_combo.addItem(readers.get(name).label, name)
        self.response_edit = QLineEdit()
        self.response_edit.setPlaceholderText("optional: calculated values of the inversion")
        self.response_edit.setToolTip("Model response (one calculated value per reading), "
                                      "e.g. BERT's response.vector or a pyGIMLi response: "
                                      "with it the layer shows the misfit")
        response_browse = QPushButton("Browse…")
        response_browse.clicked.connect(self._browse_response)
        self.response_row = QHBoxLayout()
        self.response_row.addWidget(self.response_edit)
        self.response_row.addWidget(response_browse)
        self.z_combo = QComboBox()
        for text, value in Z_ITEMS:
            self.z_combo.addItem(text, value)
        self.method_combo = QComboBox()
        for text, value in METHODS:
            self.method_combo.addItem(text, value)
        self.method_combo.setToolTip(METHOD_TIP)
        self.station_set_combo = QComboBox()
        self.station_set_combo.setObjectName("station_set_combo")
        self.station_set_combo.setToolTip("The profile's station set this file belongs to")
        form = QFormLayout()
        for text, field in (("File", file_row), ("Name", self.name_edit),
                            ("Format", self.format_combo), ("Response file", self.response_row),
                            ("Z means", self.z_combo), ("Method", self.method_combo),
                            ("Station set", self.station_set_combo)):
            form.addRow(text, field)
        self._form = form

        self.table_options = TableOptionsBox()
        self.table_options.setObjectName("table_options")
        self.columns_group = ModelColumnsBox(store.crs_authid)
        self.columns_group.setObjectName("columns_group")
        self.placement = PlacementWidget(iface, store, self.project, allow_existing=True,
                                         allow_file_coordinates=True)
        self.placement.setObjectName("placement")
        self.placement.set_current_profile(profile_id)

        self._preview_group = preview = QGroupBox("Preview")
        preview.setObjectName("preview_group")
        self.preview_table = PreviewTable()
        self.preview_table.setObjectName("preview_table")
        self.preview_table.setMaximumHeight(170)
        self.preview_table.verticalHeader().setDefaultSectionSize(
            self.fontMetrics().height() + 6)
        self.summary_label = _label("summary_label")
        self.fit_label = _label("fit_label")
        self.electrode_label = _label("electrode_label")
        self.warning_label = _label("warning_label")
        self.warning_label.setStyleSheet(WARNING_STYLE)
        QVBoxLayout(preview).addWidget(self.preview_table)
        # the verdict stays in view above the buttons; only the groups and the table scroll
        self.status_block = QWidget()
        self.status_block.setObjectName("status_block")
        status = QVBoxLayout(self.status_block)
        status.setContentsMargins(0, 0, 0, 0)
        for w in (self.summary_label, self.fit_label, self.electrode_label,
                  self.warning_label):
            status.addWidget(w)

        self._page = page = QWidget()
        column = QVBoxLayout(page)
        column.addLayout(form)
        for w in (self.table_options, self.columns_group, self.placement, preview):
            column.addWidget(w)
        column.addStretch(1)
        self._scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Add")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        add_help_button(buttons, "add_data")
        layout = QVBoxLayout(self)
        layout.addWidget(scroll, 1)
        layout.addWidget(self.status_block)
        layout.addWidget(buttons)

        self.format_combo.currentIndexChanged.connect(self._format_changed)
        self.response_edit.editingFinished.connect(self._refresh)
        self.z_combo.currentIndexChanged.connect(self._refresh)
        self.method_combo.currentIndexChanged.connect(self._refresh)
        self.station_set_combo.currentIndexChanged.connect(self._refresh)
        self.table_options.changed.connect(self._refresh)
        self.columns_group.changed.connect(self._refresh)
        self.placement.changed.connect(self._refresh)
        self.placement.zero_combo.activated.connect(self._zero_activated)
        self._refresh()
        screen = self.screen().availableGeometry()
        self.resize(min(760, screen.width() - 40), min(580, screen.height() - 80))

    # -- what is chosen ----------------------------------------------------------------------
    def _path(self) -> str:
        return self.file_edit.text().strip()

    def _reader(self) -> str:
        return self.format_combo.currentData()

    def _is_table(self) -> bool:
        return self._reader() == readers.FALLBACK

    def _on_map(self) -> bool:
        return self._is_table() and self.columns_group.columns().position == "map"

    def _name(self) -> str:
        return self.name_edit.text().strip() or Path(self._path()).stem

    def _reader_options(self) -> dict:
        """The reader options as saved (the placement is added on saving)."""
        if self._is_table():
            return {"table": self.table_options.options().to_dict(),
                    "columns": self.columns_group.columns().to_dict()}
        options = {"z_kind": self.z_combo.currentData()} if self.z_combo.currentData() else {}
        response = self.response_edit.text().strip()
        if self._reader() in RESPONSE_READERS and response:
            resp, data = Path(response), Path(self._path())   # kept next to the data file
            options["response"] = (resp.name if resp.parent.resolve() ==
                                   data.parent.resolve() else str(resp))
        return options

    # -- file --------------------------------------------------------------------------------
    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Data File", "", FILE_FILTER)
        if path:
            self.set_file(path)

    def _browse_response(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Model Response File", "",
                                              "Response (*.vector *.response *.txt);;"
                                              "All files (*)")
        if path:
            self.response_edit.setText(path)
            self._refresh()

    def _file_typed(self) -> None:
        if self._path() != self._file:
            self.set_file(self._path())

    @_guarded
    def set_file(self, path) -> None:
        path = self._file = str(path)
        self.file_edit.setText(path)
        self._table = self._table_key = self._result = self._read_key = None
        self._z_preset = self._line_key = self._pending_columns = None
        if path:
            found = readers.detect(path)
            self.format_combo.blockSignals(True)
            self.format_combo.setCurrentIndex(
                self.format_combo.findData(found[0] if found else readers.FALLBACK))
            self.format_combo.blockSignals(False)
            self._format_settings(path)
            if self.name_edit.text() in ("", self._auto_name):
                self._auto_name = Path(path).stem
                self.name_edit.setText(self._auto_name)
        self._refresh()

    @_guarded
    def _format_changed(self, *_args) -> None:
        self._result = self._read_key = self._z_preset = None
        if self._path():
            self._format_settings(self._path())
        self._refresh()

    def _format_settings(self, path: str) -> None:
        """A response file for a readings format; for a text table the remembered settings
        when this file has the same columns as the last one, else the guessed layout."""
        self.response_edit.setText(guess_response(path) if self._reader() in RESPONSE_READERS
                                   else "")
        if not self._is_table() or self._table_key is not None:
            return
        try:
            options = guess_options(path)
        except (OSError, ValueError):
            options = TableOptions()                # the preview says what is wrong
        last = _remembered()
        if last:
            try:
                stored = TableOptions.from_dict(last["table"])
                columns = ModelColumns.from_dict(last["columns"])
                table = read_table(path, stored, max_rows=SAMPLE_ROWS)
                if table.names == list(last["names"]):
                    options, self._pending_columns = stored, columns
            except (KeyError, TypeError, ValueError, AttributeError, OSError):
                pass                                # a stored value that no longer loads
        self.table_options.set_options(options)

    def _preview(self):
        """The first rows (``SAMPLE_ROWS``) of the text table, read again when the file or
        its layout changed; a new table gets the remembered or a guessed assignment."""
        key = (self._path(), self.table_options.options())
        if key != self._table_key:
            old, self._table, self._table_key = self._table, None, None
            table = read_table(key[0], key[1], max_rows=SAMPLE_ROWS + 1)
            self._more = table.n_rows > SAMPLE_ROWS
            if self._more:
                table = TextTable(table.names, table.cells[:SAMPLE_ROWS],
                                  table.line_numbers[:SAMPLE_ROWS], table.decimal_comma)
            self._table, self._table_key = table, key
            pending, self._pending_columns = self._pending_columns, None
            if pending is not None:
                self.columns_group.set_columns(table, pending, REMEMBERED_HINT)
            elif old is None or old.names != table.names:
                self.columns_group.set_columns(table, guess_model_columns(table), GUESSED_HINT)
            else:                                   # same columns: keep the assignment
                self.columns_group.set_columns(table, self.columns_group.columns(), None)
        return self._table

    def _read(self) -> readers.ReaderResult:
        """The whole file as the section will read it (cached); a map file on the line of
        the chosen placement. A fixed format's own Z hint presets "Z means" once."""
        path, reader = self._path(), self._reader()
        profile = self._draft()[0] if self._on_map() else None
        if not self._is_table() and self._z_preset != (path, reader):
            self._read_key = None
            self._result = read_for(self.store, profile, path, reader,
                                    {k: v for k, v in self._reader_options().items()
                                     if k != "z_kind"})
            self.z_combo.blockSignals(True)         # unknown -> choose
            self.z_combo.setCurrentIndex(max(0, self.z_combo.findData(self._result.z_kind)))
            self.z_combo.blockSignals(False)
            self._preset_method(self._result.provenance)
            self._z_preset = (path, reader)
            self._read_key = self._key(profile)
        elif self._is_table():
            self._preset_method({})
        if self._key(profile) != self._read_key:          # a text table: its sample only
            self._result, self._read_key = None, None
            self._result = read_for(self.store, profile, path, reader, self._reader_options(),
                                    SAMPLE_ROWS if self._is_table() else None)
            self._read_key = self._key(profile)
        return self._result

    def _key(self, profile) -> tuple:
        line = None if profile is None else np.asarray(profile.xy, float).tobytes()
        return (self._path(), self._reader(),
                json.dumps(self._reader_options(), sort_keys=True), line)

    def _draft(self):
        """(profile, station sets, new station set) the placement gives; nothing saved."""
        return draft_profile(self.store, self.placement.placement(), self._name(),
                             self.method_combo.currentData())

    # -- preview -----------------------------------------------------------------------------
    @_guarded
    def _refresh(self, *_args) -> None:
        if self._busy:
            return
        self._busy = True
        try:
            self._update()
        finally:
            self._busy = False
            for label in (self.summary_label, self.fit_label, self.electrode_label,
                          self.warning_label):
                label.setVisible(bool(label.text()))
            self._fit_width()

    def _update(self) -> None:
        table = self._is_table()
        for w in (self.table_options, self.columns_group, self._preview_group):
            w.setVisible(table)
        self._form.setRowVisible(self.response_row, self._reader() in RESPONSE_READERS)
        self._form.setRowVisible(self.z_combo, not table)
        for label in (self.summary_label, self.fit_label, self.electrode_label,
                      self.warning_label):
            label.clear()
        self.summary_label.setStyleSheet("")
        self.fit_label.setStyleSheet("")
        self._confirm = []
        problems = []
        if table and self._path():
            tab = self._preview()
            self.preview_table.show(tab, self.columns_group.roles_for(tab.n_columns),
                                    PREVIEW_ROWS)
            problems = self.columns_group.columns().problems(tab)
        self._sync_placement(not problems)
        if not self._path():
            self.summary_label.setText("Choose a data file.")
            return
        if problems:
            self.summary_label.setText("; ".join(problems))
            return
        if self._on_map():                          # read onto the line, once there is one
            try:
                self._draft()
            except ValueError as exc:
                self.summary_label.setText(f"The cells are placed by their map coordinates "
                                           f"once the line is chosen: {exc}")
                return
        try:
            result = self._read()
        except ValueError as exc:
            if not (table and self._more):
                raise
            # e.g. the sample ends inside the first row of cells: the file may still be fine
            self.summary_label.setText(f"The first {SAMPLE_ROWS} rows alone give no section "
                                       f"({exc}); the whole file is read on Add.")
            return
        z_kind = self.columns_group.columns().vertical_kind if table else \
            self.z_combo.currentData()
        self.summary_label.setText(describe(result, z_kind,
                                            SAMPLE_ROWS if table and self._more else 0))
        self._show_placement(result, z_kind)

    def _fit_width(self) -> None:
        """Wide enough for the groups shown, so only the height scrolls."""
        bar = self._scroll.verticalScrollBar().sizeHint().width()
        self._scroll.setMinimumWidth(self._page.minimumSizeHint().width() + bar
                                     + 2 * self._scroll.frameWidth())

    def _sync_placement(self, columns_ok: bool) -> None:
        """The placement's rows for this file: distance 0 and offset for a file in distance
        along the line, the line through a map file's own coordinates."""
        on_map = self._on_map()
        self.placement.set_needs_distance(not on_map)
        radio = self.placement.findChild(QRadioButton, "source_file")
        radio.setEnabled(on_map)
        radio.setToolTip("" if on_map else "For a file with map coordinates")
        if on_map != self._on_map_shown:
            self._on_map_shown = on_map
            source = self.placement.source()
            if on_map and not (self._profile_id and source == "existing"):
                self.placement.select_source("file")
            elif not on_map and source == "file":
                self.placement.select_source(
                    "existing" if self.placement.profile_combo.count() else "line")
        if on_map and columns_ok:
            self._file_line()
        if not self._zero_chosen:                   # as 0.8 placed it: from station 1
            combo = self.placement.zero_combo
            i = combo.findData("station1")
            if i >= 0 and combo.currentIndex() != i:
                combo.blockSignals(True)
                combo.setCurrentIndex(i)
                combo.blockSignals(False)
        source = self.placement.source()
        pid = self.placement.profile_combo.currentData() if source == "existing" else None
        if pid != self._sets_for:                   # the chosen profile's station sets
            self._sets_for = pid
            self._sets = self.store.station_sets(pid) if pid else []
            self.station_set_combo.blockSignals(True)
            self.station_set_combo.clear()
            for s in self._sets:
                self.station_set_combo.addItem(s.name or s.id, s.id)
            self.station_set_combo.blockSignals(False)
        self._form.setRowVisible(self.station_set_combo, len(self._sets) > 1)

    def _file_line(self) -> None:
        """Hand the line through the file's map positions (in the store's CRS) to the
        placement; remembered per file, layout and coordinate columns."""
        cols = self.columns_group.columns()
        key = (self._path(), self.table_options.options(), cols.easting, cols.northing,
               cols.crs)
        if key != self._line_key:
            self._line, self._line_error = None, ""
            try:
                xy = map_points(key[0], key[1].to_dict(), cols.to_dict(), SAMPLE_ROWS)
                self._line = line_from_cloud(xy_to_store(xy, cols.crs, self.store.crs_authid,
                                                         self.project))
            except ValueError as exc:
                self._line_error = str(exc)
            self._line_key = key
            self.placement.set_file_line(*(self._line or (None, 0)))

    def _show_placement(self, result, z_kind) -> None:
        """Fit report, electrode note and warnings for the placement as chosen."""
        mesh = result.mesh
        on_map, readings = self._on_map(), mesh.readings is not None
        guess = (np.empty(0) if on_map or readings
                 else model_stations(mesh, result.provenance, z_kind))
        self.placement.set_guessed_spacing(float(np.median(np.diff(guess)))
                                           if guess.size >= 2 else None)
        warnings = [self._line_error] if on_map and self._line_error else []
        try:
            placement = self.placement.placement()
            profile, sets, new_set = self._draft()
        except ValueError as exc:
            self.fit_label.setText(str(exc))
            self._set_warnings(warnings)
            return
        if new_set is not None and new_set.warnings and placement.profile_id is not None:
            warnings.append("Positions off the line: " + ", ".join(new_set.warnings))
            self._confirm.append(warnings[-1] + ". Add them anyway?")
        station_set_id, options = dataset_options(placement, profile, sets,
                                                  self._reader_options(),
                                                  self._station_set_id(new_set))
        station_set = next((s for s in sets if s.id == station_set_id), None)
        if on_map:
            span, guessed = mesh.bounds()[:2], False
            if self.placement.source() != "file":
                warnings += self._map_fit(result.provenance)
        else:
            draft = Dataset("", profile.id, station_set_id, "", "", 0.0, "", self._reader(),
                            options, {})
            resolution = resolve(profile, sets, draft,
                                 self._layout(placement, profile, guess, result))
            span = resolution.map(np.asarray(mesh.bounds()[:2], dtype=float))
            guessed = resolution.source == "guessed"
            known = self.placement.known_points()
            fit = fit_report(*known) if known is not None else resolution.fit
            guess_used = self.placement.spacing_is_guess() if known is not None else guessed
            show_fit(self.fit_label, *fit_line(fit, guess_used, resolution.note))
        named = not on_map and not readings and "station_x" in result.provenance
        self.electrode_label.setText(self._electrode_text(placement, profile, sets, readings,
                                                          guess, named))
        if station_set is not None and not guessed:
            overhang = overhang_message(span[0], span[1], station_set, profile.name)
            if overhang:
                warnings.append(overhang)
                self._confirm.append(overhang)
        self._set_warnings(warnings)

    def _station_set_id(self, new_set) -> str | None:
        """The station set chosen for the dataset: a new one made from positions, else the
        one picked in "Station set" (None: the profile's first)."""
        return new_set.id if new_set is not None else self.station_set_combo.currentData()

    def _map_fit(self, provenance: dict) -> list[str]:
        offset = float(provenance.get("max_offset") or 0.0)
        beyond = int(provenance.get("n_beyond") or 0)
        text = f"Cells up to {fmt(offset, 1)} m from the line"
        if beyond:
            text += f"; {beyond} {'position lies' if beyond == 1 else 'positions lie'} " \
                    "beyond its ends"
        self.fit_label.setText(text)
        out = []
        if offset > OFF_LINE:
            out.append(f"Some cells lie up to {fmt(offset, 1)} m from the profile line: is "
                       "this the right profile?")
        if beyond:
            out.append(f"{beyond} of the file's positions lie beyond the ends of the line.")
        return out

    def _layout(self, placement, profile, guess, result) -> ProfileLayout:
        """What the section would resolve the placement from, with this file added: the
        file comes after the profile's datasets, so its guess counts only when none of
        theirs gives one (``SectionDataProvider._layout_sources``)."""
        if placement.profile_id is not None and self.provider is not None:
            layout = self.provider.layout(placement.profile_id)
        else:
            layout = ProfileLayout()
            try:
                stated = profile.metadata.get("electrode_spacing")
                layout.spacing = None if stated is None else float(stated)
            except (TypeError, ValueError):
                pass
        if placement.spacing is not None:
            layout.spacing = placement.spacing
        electrode_x = result.provenance.get("electrode_x")
        if layout.readings_x is None and electrode_x is not None:
            layout.readings_x = np.array([np.nan if v is None else v for v in electrode_x],
                                         dtype=float)
        if layout.guess is None and guess.size >= 2:
            layout.guess, layout.guessed_spacing = guess, float(np.median(np.diff(guess)))
        return layout

    def _preset_method(self, provenance: dict) -> None:
        """The method the file says (Refrapy, a velocity VTK); measured ERT data fix it to
        ERT. Silent: the preview follows in the same refresh."""
        readings = provenance.get("kind") in READINGS_KINDS
        proposed = "ert" if readings else provenance.get("method")
        self.method_combo.blockSignals(True)
        if proposed:
            self.method_combo.setCurrentIndex(max(0, self.method_combo.findData(proposed)))
        self.method_combo.setEnabled(not readings)
        self.method_combo.setToolTip(READINGS_METHOD_TIP if readings else METHOD_TIP)
        self.method_combo.blockSignals(False)

    def _electrode_text(self, placement, profile, sets, readings: bool, guess,
                        named: bool = False) -> str:
        """What the section will show as electrodes (geophones) when the profile has no
        positions."""
        if sets or readings or profile.metadata.get("electrode_spacing") is not None:
            return ""
        if placement.profile_id is not None and self.provider is not None and \
                self.provider.electrodes(placement.profile_id) is not None:
            return ""                               # its other data give them
        word, words = station_words(self.method_combo.currentData() or "")
        if guess.size < 2:
            return NO_STATIONS_NOTE.format(word=word)
        text = NAMED_STATIONS if named else GUESSED_ELECTRODES
        return text.format(Words=words.capitalize(), n=guess.size,
                           spacing=fmt_trim(float(np.median(np.diff(guess)))))

    def _set_warnings(self, warnings: list[str]) -> None:
        self.warning_label.setText("\n".join(warnings))

    def _show_error(self, message: str) -> None:
        self.summary_label.setStyleSheet(ERROR_STYLE)
        self.summary_label.setText(message)
        self.summary_label.setVisible(True)

    def _zero_activated(self, *_args) -> None:
        self._zero_chosen = True

    # -- saving ------------------------------------------------------------------------------
    def accept(self) -> None:
        path = self._path()
        try:
            try:
                placement = self._ready()
            except ValueError as exc:               # said in the user's words already
                self._error(str(exc))
                return
            self._refresh()                         # the questions need the current preview
            for question in self._confirm:
                if QMessageBox.question(
                        self, self.windowTitle(), question,
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                    return
            if self._on_map() and self._more and self.placement.source() == "file":
                self._whole_file_line()
                placement = self.placement.placement()
            try:
                self.profile, self.dataset = add_data(
                    self.store, placement, Path(path), self._reader(),
                    self._reader_options(), self._name(), self.method_combo.currentData(),
                    self.project, self.provider,
                    self.station_set_combo.currentData() if self._sets else None)
            except NotRefreshed as exc:             # saved: never reported as a failure
                self.profile, self.dataset = exc.saved
                self._warn(str(exc))
            self.created = placement.profile_id is None
        except Exception as exc:                    # noqa: BLE001 - a slot never raises
            self._error(plain_error(exc, path or None, CHOOSE_OTHER, MISSING_FILE))
            return
        if self._is_table():
            QgsSettings().setValue(SETTINGS_KEY, json.dumps(
                {"names": self._table.names, "table": self.table_options.options().to_dict(),
                 "columns": self.columns_group.columns().to_dict()}))
        super().accept()

    def _whole_file_line(self) -> None:
        """The preview drew the line through the sample's positions: the profile gets the
        line through all of them."""
        cols = self.columns_group.columns()
        xy = map_points(self._path(), self.table_options.options().to_dict(), cols.to_dict())
        self.placement.set_file_line(*line_from_cloud(
            xy_to_store(xy, cols.crs, self.store.crs_authid, self.project)))

    def _ready(self):
        """The placement, once a file is chosen and its columns are assigned; ValueError
        saying what is missing otherwise."""
        if not self._path():
            raise ValueError("Choose a data file")
        if self._is_table():
            problems = self.columns_group.columns().problems(self._preview())
            if problems:
                raise ValueError("; ".join(problems))
        return self.placement.placement()

    def _error(self, message: str) -> None:
        self.last_error = message
        QMessageBox.warning(self, self.windowTitle(), message)

    def _warn(self, message: str) -> None:
        """Non-blocking, for after the dialog closes: on the message bar."""
        self.last_warning = message
        bar = self.iface.messageBar() if hasattr(self.iface, "messageBar") else None
        if bar is not None:
            bar.pushMessage(self.windowTitle(), message, Qgis.MessageLevel.Warning, 15)

    def done(self, result: int) -> None:
        self.placement.cancel_pick()
        self.placement.clear_overlay()
        super().done(result)
