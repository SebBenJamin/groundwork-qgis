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
import math
from pathlib import Path

import numpy as np
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsCsException,
                       QgsPointXY, QgsProject, QgsSettings)
from qgis.PyQt.QtCore import Qt
from qgis.gui import QgsDoubleSpinBox
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog,
                                 QFormLayout,
                                 QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                                 QPushButton, QRadioButton, QScrollArea, QVBoxLayout, QWidget)

from .help import add_help_button
from .add_data_files import READY, FilesBox
from .. import libs, readers
from ..core.coverage import overhang_message
from ..core.layout import model_stations
from ..core.lines import line_from_cloud
from ..core.model import Dataset
from ..core.numbers import fmt, fmt_count, fmt_sig, fmt_trim
from ..core.trace_section import Velocity, depth_at, first_arrival
from ..section.readout import format_value, unit_label
from ..core.placement import Placement, fit_report
from ..core.roles import VERTICAL_KINDS, ModelColumns, guess_model_columns
from ..ids import LEGACY_ID
from ..readers import segy
from ..readers.errors import plain_error
from ..core.coarsen import proposed_block
from ..readers.text_columns import grid_of_file, map_points
from ..readers.texttable import TableOptions, TextTable, guess_options, read_table
from ..section.data import HANG_KEYS
from ..section.placement_resolve import NO_STATIONS_NOTE, ProfileLayout, resolve
from ..section.topography import station_line
from .columns_box import GUESSED_HINT, REMEMBERED_HINT, ModelColumnsBox
from .lib_install import start_install
from .radar_box import RadarBox
from .segy_box import FIELD_WORDS, SegyBox
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
FILE_FILTER = ("Model and data files (*.dat *.txt *.csv *.xyz *.vtk *.data *.ohm *.sgy "
               "*.segy *.dzt *.dt1 *.hd);;All files (*)")
#: readers whose files hold readings and take a model-response file
RESPONSE_READERS = ("bert_data",)
#: response files looked for next to a data file
RESPONSE_NAMES = ("response.vector", "{stem}_response.vector", "{stem}.response",
                  "dcinv.response")
#: the last text-table settings, offered for the next file with the same columns
SETTINGS_KEY = f"{LEGACY_ID}/import/last"
#: the last SEG-Y settings that are not about one file, offered for the next SEG-Y file
SEGY_SETTINGS_KEY = f"{LEGACY_ID}/import/segy"
#: what the next SEG-Y file is offered from the last one; the CRS and the height of time zero
#: belong to a file (older settings that hold them are read without them)
SEGY_REMEMBERED = ("domain", "zero", "velocity_kind", "position")
#: where time zero starts the first time: at a height the user types (no height assumed)
SEGY_FIRST_ZERO = "datum"
OUTSIDE_CRS = ("These positions lie outside the area where {crs} is used. Check the position "
               "fields and the CRS.")
ADD_ANYWAY = " Add it anyway?"
SEGY = "segy"
#: readers of radar files (``radar_box.RadarBox``)
RADAR_READERS = ("gssi_dzt", "pulseekko")
#: the last radar settings that are not about one file: where time zero lies, how the traces
#: are placed (never the velocity, time zero or height)
RADAR_SETTINGS_KEY = f"{LEGACY_ID}/import/radar"
RADAR_REMEMBERED = ("zero", "position")
SEGYIO = "segyio"
SEGYIO_MISSING = ("Reading SEG-Y needs the free library segyio (0.4 MB), which is not "
                  "installed.")
INSTALL_TIP = "Download segyio with pip and install it into your QGIS profile"
NO_SEGYIO_TIP = "Install segyio first"
VOLUME_TIP = "Groundwork shows 2D sections"
UNSTACKED = ("This file looks like unstacked records (several traces per CDP or offsets that "
             "are not zero). Groundwork shows processed sections.")
REPEATS = ("Many traces of this file share a position or run back along the line. It looks "
           "like a shot record or several passes, not one section along a line.")
#: a section hung from the ground (by zero choice) on a profile without heights
NO_HEIGHTS = {
    "ground": ("This profile has no heights yet. Choose an elevation model in Context Layers, "
               "or the section hangs flat."),
    "datum_ground": ("This profile has no heights yet. Choose an elevation model in Context "
                     "Layers first: a section corrected to the ground needs them."),
}
#: a depth or local-height model on a profile that will have no heights (a hint, not a block)
FLAT_MODEL = ("This profile has no heights yet, so the model is drawn in depth below a flat "
              "surface. For real heights, choose an elevation model in Context Layers, or use "
              "Reference Height… in the section panel.")
#: what "Z means" gives a model that hangs from the profile's surface
HANGING_Z = ("depth", "local")
COARSE_NOTE ="{n} cells of {dx} × {dz} m: far finer than an inversion resolves."
COARSE_TEXT = "Read as cells of"
COARSE_TIP = ("Average the file's points in blocks of this size: faster sections, plates and "
              "3D. The file itself is not changed; untick to keep every point.")
COARSE_SIZE_TIP = "Snaps to a whole multiple of the file's spacing ({step} m)"
COARSE_COUNT = "(about {n} cells, averaged)"
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
METHOD_TIP = "Method of the data, and of the station set made from the positions"
READINGS_METHOD_TIP = "Measured ERT data: the method is ERT"
ERROR_STYLE = "color: #b00020;"


def size_decimals(step: float) -> int:
    """Decimals that show a multiple of the spacing ``step`` (0.25 -> 2, 0.1 -> 1), at most 2:
    in field geophysics nothing is placed finer than a centimetre."""
    for d in range(3):
        if abs(step * 10 ** d - round(step * 10 ** d)) < 1e-6:
            return d
    return 2


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


def describe_traces(section, options: dict | None = None) -> str:
    """'1970 traces × 1125 samples · 4 ms · 0 – 4.5 s', with a usable velocity in
    ``options`` ' · to 6750 m depth' (below time zero, at the end of the record)."""
    n, ns = section.n_traces, section.n_samples
    end = section.first + ns * section.step
    if section.domain == "depth":
        return (f"{fmt_count(n)} traces × {fmt_count(ns)} samples · "
                f"{fmt_trim(section.step, 3)} m · {fmt_trim(section.first, 2)} – "
                f"{fmt_trim(end, 2)} m")
    text = (f"{fmt_count(n)} traces × {fmt_count(ns)} samples · "
            f"{fmt_trim(section.step * 1000.0, 3)} ms · {fmt_trim(section.first, 3)} – "
            f"{fmt_trim(end, 3)} s")
    try:
        depth = float(depth_at(section, Velocity.from_options(options or {}),
                               np.array([end]))[0])
    except ValueError:
        return text                             # no usable velocity yet: the box says so
    return text + f" · to {fmt_count(depth)} m depth" if np.isfinite(depth) else text


def describe(result: readers.ReaderResult, z_kind: str | None, sample: int = 0,
             options: dict | None = None) -> str:
    """One-line summary of a reader result for the preview label, numbers in the QGIS
    locale; ``sample``: the result holds only the file's first ``sample`` rows; ``options``:
    a trace section's velocity for its depth."""
    if result.traces is not None:
        return describe_traces(result.traces, options)
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
    text = (f"{fmt_count(len(mesh.values))} cells · x {fmt(xmin)} – {fmt(xmax)} m, z {fmt(zmin)} – "
            f"{fmt(zmax)} m ({z_word}) · " +
            (f"values {format_value(values.min())} – {format_value(values.max())} "
             f"{unit_label(mesh.unit)}".rstrip()
             if len(values) else "no values"))
    # rows without a map position are reported as such (unplaced_text), not as blank cells
    n_masked = int(result.provenance.get("n_masked") or 0) - \
        int(result.provenance.get("n_unplaced") or 0)
    if n_masked and result.provenance.get("reconstruction") == "delaunay":
        text += f" · {n_masked} fill/NaN values skipped"
    elif n_masked:
        text += f" · {n_masked} {'cell' if n_masked == 1 else 'cells'} without a value (shown blank)"
    n_skipped = int(result.provenance.get("n_skipped") or 0)
    if n_skipped:
        text += (f" · {n_skipped} {'row' if n_skipped == 1 else 'rows'} skipped "
                 f"(line {result.provenance.get('first_skipped_line')})")
    return text + (f" (first {sample} rows)" if sample else "")


def unplaced_rows(provenance: dict) -> int:
    """Rows of a map file left out because their easting or northing is -9999."""
    return int(provenance.get("n_unplaced") or 0)


def _rows_word(n: int) -> str:
    return f"{n} {'row' if n == 1 else 'rows'}"


def _remembered(key: str = SETTINGS_KEY) -> dict | None:
    try:
        last = json.loads(QgsSettings().value(key, "") or "null")
    except (TypeError, ValueError):
        return None
    return last if isinstance(last, dict) else None


def _remember_segy(options: dict) -> None:
    QgsSettings().setValue(SEGY_SETTINGS_KEY, json.dumps(
        {k: options[k] for k in SEGY_REMEMBERED if k in options}))


def _remember_radar(options: dict) -> None:
    QgsSettings().setValue(RADAR_SETTINGS_KEY, json.dumps(
        {k: options[k] for k in RADAR_REMEMBERED if k in options}))


def radar_file(path: str) -> str:
    """The file a radar dataset is read from: a pulseEKKO header (.hd) stands for the trace
    file (.dt1) of the same name beside it; any other path as it is."""
    from ..readers.radar_info import partner
    p = Path(path)
    if p.suffix.lower() == ".hd":
        trace_file = partner(p, ".DT1")
        if trace_file is not None:
            return str(trace_file)
    return str(path)


def describe_radar(section, options: dict | None = None) -> str:
    """'6290 traces × 1024 samples · 0.552 ns · 0 – 565 ns', with a usable velocity and time
    zero in ``options`` ' · to 25.5 m depth' (below time zero, at the end of the record)."""
    ns = 1e-9
    end = section.first + section.n_samples * section.step
    text = (f"{fmt_count(section.n_traces)} traces × {fmt_count(section.n_samples)} samples · "
            f"{fmt_trim(section.step / ns, 3)} ns · {fmt_trim(section.first / ns, 1)} – "
            f"{fmt_trim(end / ns, 1)} ns")
    o = options or {}
    try:
        depth = float(depth_at(section, Velocity.from_options(o), np.array([end]),
                               time_zero=float(o.get("time_zero") or 0.0))[0])
    except (TypeError, ValueError):
        return text                             # no usable velocity yet: the box says so
    return text + f" · to {fmt_trim(depth, 1)} m depth" if np.isfinite(depth) else text


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
        self._method_for = None                     # (path, quantity) of a table's method
        self._line_key, self._line, self._line_error = None, None, ""
        self._on_map_shown = False
        self._zero_chosen = False                   # the user chose where distance 0 lies
        self._confirm: list[str] = []               # asked before saving
        self._busy = False
        self._files: list[str] = []                 # several files chosen: all of them
        self._file_grids: dict = {}                 # path -> (key, grid) of the coarse check
        self._file_blocks: dict = {}                # path -> proposed block or None
        self.added: list = []                       # (profile, dataset) per file added
        self._segy_key = self._segy_info = None     # (path, mtime) and what its headers say
        self._segy_infos: dict = {}                 # path -> (mtime, info or error), several
        self._radar_zeros: dict = {}                # path -> (key, (time zero s, how) or error)
        self._segy_remembered = False               # the last SEG-Y settings were offered
        self._install_task = None
        self._install_message = ""                  # why installing segyio failed
        self._segy_ends = None                      # first and last trace position (file CRS)
        self._radar_key = self._radar_info = None   # (path, mtime, reader) and its header
        self._radar_remembered = False              # the last radar settings were offered
        self._estimated_for = None                  # the read whose first arrival was offered

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
        self.segy_box = SegyBox()
        prj_crs = self.project.crs()
        self.segy_box.set_default_crs(prj_crs if prj_crs.isValid() else
                                      QgsCoordinateReferenceSystem(store.crs_authid))
        self.segy_box.set_zero(SEGY_FIRST_ZERO)
        self.segy_box.hide()
        self.radar_box = RadarBox()
        self.radar_box.set_default_crs(prj_crs if prj_crs.isValid() else
                                       QgsCoordinateReferenceSystem(store.crs_authid))
        self.radar_box.hide()

        self._preview_group = preview = QGroupBox("Preview")
        preview.setObjectName("preview_group")
        self.preview_table = PreviewTable()
        self.preview_table.setObjectName("preview_table")
        self.preview_table.setMaximumHeight(170)
        self.preview_table.verticalHeader().setDefaultSectionSize(
            self.fontMetrics().height() + 6)
        self.summary_label = _label("summary_label")
        self.summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._install_button = None                 # made when segyio is found missing
        self.summary_row = QWidget()
        summary_row = QHBoxLayout(self.summary_row)
        summary_row.setContentsMargins(0, 0, 0, 0)
        summary_row.addWidget(self.summary_label, 1)
        self.fit_label = _label("fit_label")
        self.electrode_label = _label("electrode_label")
        self.warning_label = _label("warning_label")
        self.warning_label.setStyleSheet(WARNING_STYLE)
        #: what a SEG-Y section still needs ("Enter the velocity in m/s."), as a warning
        self.missing_label = _label("missing_label")
        self.missing_label.setStyleSheet(WARNING_STYLE)
        self._build_coarse()
        QVBoxLayout(preview).addWidget(self.preview_table)
        # the verdict stays in view above the buttons; only the groups and the table scroll
        self.status_block = QWidget()
        self.status_block.setObjectName("status_block")
        status = QVBoxLayout(self.status_block)
        status.setContentsMargins(0, 0, 0, 0)
        for w in (self.coarse_note, self.coarse_row, self.summary_row, self.missing_label,
                  self.fit_label, self.electrode_label, self.warning_label):
            status.addWidget(w)

        self.files_box = FilesBox()
        self.files_box.hide()                       # only when several files are chosen
        self.files_box.changed.connect(self._refresh)

        self._page = page = QWidget()
        column = QVBoxLayout(page)
        column.addLayout(form)
        for w in (self.files_box, self.segy_box, self.radar_box, self.table_options,
                  self.columns_group, self.placement, preview):
            column.addWidget(w)
        column.addStretch(1)
        self._scroll = scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        self.add_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.add_button.setText("Add")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        add_help_button(buttons, lambda: ("add_data" if not self._path() else "add_segy"
                                          if self._is_segy() else "add_gpr"
                                          if self._is_radar() else "add_data"))
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
        self.segy_box.changed.connect(self._refresh)
        self.radar_box.changed.connect(self._refresh)
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

    def _is_segy(self) -> bool:
        return self._reader() == SEGY

    def _is_radar(self) -> bool:
        return self._reader() in RADAR_READERS

    def _is_traces(self) -> bool:
        """A file of traces: a SEG-Y section or a radargram (the box says how it hangs)."""
        return self._is_segy() or self._is_radar()

    def _trace_box(self):
        """The box of the trace reader chosen: ``SegyBox`` or ``RadarBox``."""
        return self.radar_box if self._is_radar() else self.segy_box

    def _on_map(self) -> bool:
        if self._is_radar():
            return self.radar_box.position() == "table"
        if self._is_segy():
            return self.segy_box.position() in ("map", "table")
        return self._is_table() and self.columns_group.columns().position == "map"

    def _name(self) -> str:
        return self.name_edit.text().strip() or Path(self._path()).stem

    def _reader_options(self) -> dict:
        """The reader options as saved (the placement is added on saving)."""
        if self._is_segy():
            return self.segy_box.options()
        if self._is_radar():
            return self._radar_options(self._path())
        if self._is_table():
            options = {"table": self.table_options.options().to_dict(),
                       "columns": self.columns_group.columns().to_dict()}
            block = self._block()
            if block is not None:
                options["block"] = list(block)
            return options
        options = {"z_kind": self.z_combo.currentData()} if self.z_combo.currentData() else {}
        response = self.response_edit.text().strip()
        if self._reader() in RESPONSE_READERS and response:
            resp, data = Path(response), Path(self._path())   # kept next to the data file
            options["response"] = (resp.name if resp.parent.resolve() ==
                                   data.parent.resolve() else str(resp))
        return options

    def _radar_options(self, path: str) -> dict:
        """The radar box's options for ``path`` (the fit is a placement, not an option); a
        pulseEKKO line names its header file, which is read with it."""
        from ..readers.radar_info import partner
        options = {k: v for k, v in self.radar_box.options().items()
                   if k not in ("fit_length", "span")}
        if self._reader() == "pulseekko":
            header = partner(Path(path), ".HD")
            if header is not None and header.parent == Path(path).parent:
                options["header_file"] = header.name
        return options

    def _sample_options(self) -> dict:
        """The reader options for the preview, which reads a sample: never in blocks."""
        return {k: v for k, v in self._reader_options().items() if k != "block"}

    # -- coarser cells -----------------------------------------------------------------------
    def _build_coarse(self) -> None:
        """The offer to read an over-fine table as coarser cells (``core.coarsen``)."""
        self.coarse_note = _label("coarse_note")
        self.coarse_row = QWidget()
        self.coarse_row.setObjectName("coarse_row")
        row = QHBoxLayout(self.coarse_row)
        row.setContentsMargins(0, 0, 0, 0)
        self.coarse_check = QCheckBox(COARSE_TEXT)
        self.coarse_check.setObjectName("coarse_check")
        self.coarse_check.setToolTip(COARSE_TIP)
        self.coarse_dx, self.coarse_dz = QgsDoubleSpinBox(), QgsDoubleSpinBox()
        for name, spin in (("coarse_dx", self.coarse_dx), ("coarse_dz", self.coarse_dz)):
            spin.setObjectName(name)
            spin.setDecimals(3)
            spin.setSuffix(" m")
            spin.setShowClearButton(False)
            spin.editingFinished.connect(self._snap_coarse)
        self.coarse_count = _label("coarse_count")
        self.coarse_check.toggled.connect(self._coarse_changed)
        row.addWidget(self.coarse_check)
        row.addWidget(self.coarse_dx)
        row.addWidget(QLabel("×"))
        row.addWidget(self.coarse_dz)
        row.addWidget(self.coarse_count, 1)
        self.coarse_note.hide()
        self.coarse_row.hide()
        self._grid = self._grid_key = self._coarse_for = None

    def _block(self) -> tuple[int, int] | None:
        """The ticked block factors (fx, fz), or None (no offer, or unticked)."""
        if self._grid is None or self.coarse_row.isHidden() or not self.coarse_check.isChecked():
            return None
        return (max(1, round(self.coarse_dx.value() / self._grid.dx)),
                max(1, round(self.coarse_dz.value() / self._grid.dz)))

    def _sync_coarse(self, columns_ok: bool) -> None:
        """Offer coarser cells when the whole file's points form an over-fine grid; the
        proposal is made again only for another file or a grid that differs."""
        grid, key = None, None
        if columns_ok:
            path = Path(self._path())
            cols = self.columns_group.columns()
            try:
                key = (str(path), path.stat().st_mtime,
                       json.dumps(self.table_options.options().to_dict(), sort_keys=True),
                       cols.position, cols.distance, cols.easting, cols.northing, cols.vertical)
                if key != self._grid_key:
                    self._grid = grid_of_file(path, self.table_options.options().to_dict(),
                                              cols.to_dict())
                    self._grid_key = key
                grid = self._grid
            except (OSError, ValueError):
                grid = None
        block = proposed_block(grid) if grid is not None else None
        for w in (self.coarse_note, self.coarse_row):
            w.setVisible(block is not None)
        if block is None:
            return
        # proposed (and ticked) again only for another file or another grid: a choice the
        # user made stays when an option that reads the same grid changes
        if self._coarse_for != (self._path(), grid):
            self._coarse_for = (self._path(), grid)
            for spin, step, f in ((self.coarse_dx, grid.dx, block[0]),
                                  (self.coarse_dz, grid.dz, block[1])):
                spin.setDecimals(size_decimals(step))
                spin.setSingleStep(step)
                spin.setRange(step, step * 64)
                spin.setToolTip(COARSE_SIZE_TIP.format(step=fmt_trim(step, 3)))
                spin.setValue(f * step)
            self.coarse_check.setChecked(True)
        self.coarse_note.setText(COARSE_NOTE.format(n=fmt_count(grid.n_points),
                                                    dx=fmt_trim(grid.dx, 3),
                                                    dz=fmt_trim(grid.dz, 3)))
        self._coarse_changed()

    def _snap_coarse(self) -> None:
        """A typed size goes to the nearest whole multiple of the file's spacing."""
        if self._grid is None:
            return
        for spin, step in ((self.coarse_dx, self._grid.dx), (self.coarse_dz, self._grid.dz)):
            spin.setValue(max(1, round(spin.value() / step)) * step)
        self._coarse_changed()

    def _coarse_changed(self, *_args) -> None:
        on = self.coarse_check.isChecked()
        self.coarse_dx.setEnabled(on)
        self.coarse_dz.setEnabled(on)
        block = self._block()
        self.coarse_count.setText(
            "" if block is None or self._grid is None else
            COARSE_COUNT.format(n=fmt_count(self._grid.n_points / (block[0] * block[1]))))

    # -- file --------------------------------------------------------------------------------
    def _browse(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Data Files", "", FILE_FILTER)
        if paths:
            self.set_files(paths)

    def set_files(self, paths) -> None:
        """One file: the dialog as always. Several: the first file's settings for all, and a
        row per file saying which profile it goes to."""
        paths = list(dict.fromkeys(radar_file(str(p)) for p in paths))   # a pair is one line
        self._files = paths if len(paths) > 1 else []
        if self._files:
            self._file_blocks = {}
            on_map = False                          # known once the first file is read
            self.files_box.set_files(paths, [(p.id, p.name) for p in self.store.profiles()],
                                     on_map)
        self.files_box.setVisible(bool(self._files))
        self.set_file(paths[0] if paths else "")

    def _browse_response(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Model Response File", "",
                                              "Response (*.vector *.response *.txt);;"
                                              "All files (*)")
        if path:
            self.response_edit.setText(path)
            self._refresh()

    def _file_typed(self) -> None:
        if radar_file(self._path()) != self._file:
            self.set_files([self._path()])         # a typed path: one file

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
                self._auto_name = readers.default_name(path, found[0] if found else None)
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
        if self._is_traces():                       # the method is set with the headers
            pass
        elif not self._is_table() and self._z_preset != (path, reader):
            self._read_key = None
            self._result = read_for(self.store, profile, path, reader,
                                    {k: v for k, v in self._reader_options().items()
                                     if k != "z_kind"})
            self.z_combo.blockSignals(True)         # unknown -> choose
            self.z_combo.setCurrentIndex(max(0, self.z_combo.findData(self._result.z_kind)))
            self.z_combo.blockSignals(False)
            self._preset_method(self._result.provenance, self._result.mesh.quantity)
            self._method_for = None
            self._z_preset = (path, reader)
            self._read_key = self._key(profile)
        elif self._is_table():                      # proposed again only when the file or
            quantity = self.columns_group.columns().quantity   # its quantity changes
            key = (path, quantity)
            self._preset_method({}, quantity, propose=key != self._method_for)
            self._method_for = key
        if self._key(profile) != self._read_key:          # a text table: its sample only
            self._result, self._read_key = None, None
            self._result = read_for(self.store, profile, path, reader, self._sample_options(),
                                    SAMPLE_ROWS if self._is_table() else None)
            self._read_key = self._key(profile)
        return self._result

    def _key(self, profile) -> tuple:
        """What the read depends on; a section's velocity and time zero only hang it."""
        line = None if profile is None else np.asarray(profile.xy, float).tobytes()
        options = {k: v for k, v in self._sample_options().items()
                   if not (self._is_traces() and k in HANG_KEYS)}
        return (self._path(), self._reader(), json.dumps(options, sort_keys=True), line)

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
            for label in (self.summary_label, self.missing_label, self.fit_label,
                          self.electrode_label, self.warning_label):
                label.setVisible(bool(label.text()))
            self._fit_width()

    def _update(self) -> None:
        table, segy_file, radar = self._is_table(), self._is_segy(), self._is_radar()
        for w in (self.table_options, self.columns_group, self._preview_group):
            w.setVisible(table)
        self.segy_box.setVisible(False)             # shown once the headers are read
        self.radar_box.setVisible(False)
        if self._install_button is not None:
            self._install_button.setVisible(False)
        self._set_addable(True)
        self._form.setRowVisible(self.response_row, self._reader() in RESPONSE_READERS)
        self._form.setRowVisible(self.z_combo, not table and not segy_file and not radar)
        for label in (self.summary_label, self.missing_label, self.fit_label,
                      self.electrode_label, self.warning_label):
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
        elif segy_file and self._path():
            if not self._segy_headers():            # segyio missing, or a 3D volume
                return
            problems = self.segy_box.read_problems()  # velocity etc. only hang it
        elif radar and self._path():
            self._radar_headers()
            problems = self.radar_box.read_problems()  # velocity, time zero only hang it
        self._sync_placement(not problems)
        self._sync_coarse(table and bool(self._path()) and not problems)
        several = bool(self._files)
        self.placement.setVisible(not several)      # each file's row says where it goes
        self._form.setRowVisible(self.name_edit, not several)   # each is named after its file
        if several:
            for w in (self.coarse_note, self.coarse_row):        # offered per file instead
                w.hide()
            self._check_files(not problems)
        if not self._path():
            self.summary_label.setText("Choose a data file.")
            return
        if problems and (segy_file or radar):       # what to enter, said as a warning
            self.missing_label.setText(" ".join(problems))
            return
        if problems:
            self.summary_label.setText("; ".join(problems))
            return
        if self._on_map():                          # read onto the line, once there is one
            try:
                self._draft()
            except ValueError as exc:
                what = "traces" if segy_file or radar else "cells"
                self.summary_label.setText(f"The {what} are placed by their map coordinates "
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
        if radar and result.traces is not None:
            self._offer_time_zero(result)
            self.summary_label.setText(describe_radar(result.traces, self._reader_options()))
        else:
            self.summary_label.setText(describe(result, z_kind,
                                                SAMPLE_ROWS if table and self._more else 0,
                                                self._reader_options()))
        if result.traces is not None and self._trace_box().hang_problems():
            self.missing_label.setText(" ".join(self._trace_box().hang_problems()))
        if several:                                 # the summary is the first file's
            self.summary_label.setText(f"{Path(self._path()).name}: "
                                       f"{self.summary_label.text()}")
            return
        if result.traces is not None:
            self._show_trace_placement(result)
        else:
            self._show_placement(result, z_kind)

    # -- SEG-Y -------------------------------------------------------------------------------
    def _set_addable(self, ok: bool, why: str = "") -> None:
        self.add_button.setEnabled(ok)
        self.add_button.setToolTip("" if ok else why)

    @property
    def install_button(self) -> QPushButton:
        """The Install segyio button beside the summary, made the first time segyio is
        found missing."""
        if self._install_button is None:
            button = self._install_button = QPushButton("Install segyio")
            button.setObjectName("install_button")
            button.setToolTip(INSTALL_TIP)
            button.clicked.connect(self._install)
            self.summary_row.layout().addWidget(button, 0, Qt.AlignmentFlag.AlignTop)
        return self._install_button

    def _segy_headers(self) -> bool:
        """Read the SEG-Y file's headers into the box (once per file and change); False when
        the file cannot be added as it is: segyio is missing (with the Install button) or it
        is a 3D volume."""
        if self._method_for != (self._path(), SEGY):     # proposed once per file
            self._preset_method({"method": "refl"}, "amplitude")
            self._method_for = (self._path(), SEGY)
        if not libs.available(SEGYIO):
            text = SEGYIO_MISSING
            if self._install_message:
                text += "\n\n" + self._install_message
            self.summary_label.setText(text)
            button = self.install_button
            button.setVisible(True)
            busy = self._install_task is not None
            button.setEnabled(not busy)
            button.setText("Installing…" if busy else "Install segyio")
            self._set_addable(False, NO_SEGYIO_TIP)
            return False
        self._install_message = ""
        path = Path(self._path())
        key = (str(path), path.stat().st_mtime if path.is_file() else None)
        if key != self._segy_key:
            self._segy_key, self._segy_info = None, None
            info = segy.inspect(path)               # a file segyio cannot read: said so
            self.segy_box.set_info(info, str(path))
            if not self._segy_remembered:           # the last file's settings, once
                self._segy_remembered = True
                last = _remembered(SEGY_SETTINGS_KEY) or {}
                self.segy_box.set_options({k: last[k] for k in SEGY_REMEMBERED if k in last})
            self._segy_key, self._segy_info = key, info
        self.segy_box.setVisible(True)
        if self._segy_info.volume:
            self.summary_label.setText(segy.volume_message(path.name, self._segy_info))
            self._set_addable(False, VOLUME_TIP)
            return False
        return True

    def _radar_headers(self) -> None:
        """Read the radar file's header into the box (once per file and change), the method
        GPR proposed once per file, the last radar settings offered once per dialog. A file
        that cannot be read raises (the preview says why)."""
        if self._method_for != (self._path(), "gpr"):
            self._preset_method({"method": "gpr"}, "amplitude")
            self._method_for = (self._path(), "gpr")
        path = Path(self._path())
        key = (str(path), path.stat().st_mtime if path.is_file() else None, self._reader())
        if key != self._radar_key:
            self._radar_key = self._radar_info = None
            if self._reader() == "pulseekko":
                from ..readers.pulseekko import inspect
            else:
                from ..readers.gssi_dzt import inspect
            info = inspect(path)
            self.radar_box.set_info(info, str(path))
            if not self._radar_remembered:          # the last file's choices, once
                self._radar_remembered = True
                last = _remembered(RADAR_SETTINGS_KEY) or {}
                self.radar_box.set_options({k: last[k] for k in RADAR_REMEMBERED if k in last})
            self._radar_key, self._radar_info = key, info
        self.radar_box.setVisible(True)

    def _offer_time_zero(self, result) -> None:
        """Time zero estimated from the first arrival of the file just read (its leading
        samples that are not data left out), offered once per read when the file states
        none; the box keeps a number from the file or the user."""
        key = (self._radar_key, id(result))
        if key == self._estimated_for:
            return
        self._estimated_for = key
        if self._radar_info is not None and self._radar_info.time_zero is None:
            skip = int(result.provenance.get("reserved_samples") or 0)
            self.radar_box.set_estimate(first_arrival(result.traces, skip=skip))

    def _radar_line(self) -> None:
        """The line through a radargram's coordinate file, in the store's CRS, for the
        placement's "file" source."""
        o = self.radar_box.options()
        where = {k: o.get(k) for k in ("positions_file", "positions_table",
                                       "positions_columns", "crs")}
        key = ("radar", self._path(), json.dumps(where, sort_keys=True))
        if key != self._line_key:
            self._line, self._line_error = None, ""
            try:
                if not o.get("positions_file") or self._radar_info is None:
                    raise ValueError("Choose the coordinate file with the trace positions.")
                table = Path(o["positions_file"])
                if not table.is_absolute():
                    table = Path(self._path()).parent / table
                xy = segy.table_positions(table, o.get("positions_table") or {},
                                          o.get("positions_columns") or {},
                                          np.arange(1, self._radar_info.n_traces + 1))
                self._line = line_from_cloud(xy_to_store(xy, o.get("crs", ""),
                                                         self.store.crs_authid, self.project))
            except ValueError as exc:
                self._line_error = str(exc)
            self._line_key = key
            self.placement.set_file_line(*(self._line or (None, 0)))

    def _compare_lengths(self, result, profile, sets, placement: Placement) -> None:
        """From and To for the fit, when the traces are placed by the file's distances on an
        existing profile or a line (not by positions): where ``placement`` puts the first and
        last trace on an existing profile; a new line's start and end (its end and start for
        "End of the line")."""
        span = (None, None, None)
        if self.radar_box.position() == "file" and profile is not None and \
                self.placement.source() in ("existing", "line", "points"):
            x = np.asarray(result.traces.x, dtype=float)
            ends = np.array([x[0], x[-1]])
            length = float(profile.chainage.length)
            if self.placement.source() == "existing":
                set_id, options = dataset_options(placement, profile, sets, {})
                draft = Dataset("", profile.id, set_id, "gpr_section", "", 0.0, "",
                                self._reader(), options, {})
                ends = resolve(profile, sets, draft, ProfileLayout()).map(ends)
            else:
                ends = (length, 0.0) if placement.zero == "end" else (0.0, length)
            span = (float(x[-1] - x[0]), float(ends[0]), float(ends[1]))
        self.radar_box.set_span(*span)

    def _fitted(self, placement: Placement) -> Placement:
        """``placement`` as From and To say: pinned at them (the file's first and last trace)
        when the fit is ticked; else, when the user typed them, the first trace at From, the
        file running towards To."""
        if not self._is_radar() or self._result is None or self._result.traces is None:
            return placement
        options, span = self.radar_box.options(), self.radar_box.span()
        if span is None:
            return placement
        x = self._result.traces.x
        x0 = float(x[0])
        if options.get("fit_length"):
            placement.fit, placement.fit_to = (x0, float(x[-1])), span
        elif "span" in options:
            start, end = span
            if end < start:                     # against the profile's direction
                length = float(self._draft()[0].chainage.length)
                placement.zero, placement.offset = "end", length - start - x0
            else:
                placement.zero, placement.offset = "start", start - x0
        return placement

    def _segy_line(self) -> None:
        """The line through the section's trace positions (headers or coordinate file), in
        the store's CRS, for the placement's "file" source."""
        o = self.segy_box.options()
        where = {k: o.get(k) for k in ("position", "xy_field", "positions_file",
                                       "positions_table", "positions_columns", "crs")}
        key = (SEGY, self._path(), json.dumps(where, sort_keys=True))
        if key != self._line_key:
            self._line, self._line_error, self._segy_ends = None, "", None
            try:
                xy = segy.map_positions(self._path(), o)
                self._segy_ends = (tuple(map(float, xy[0])), tuple(map(float, xy[-1])))
                self._line = line_from_cloud(xy_to_store(xy, o.get("crs", ""),
                                                         self.store.crs_authid, self.project))
            except ValueError as exc:
                self._line_error = str(exc)
            self._line_key = key
            self.placement.set_file_line(*(self._line or (None, 0)))

    def _show_trace_placement(self, result) -> None:
        """Warnings for a trace section: unstacked records, traces sharing positions or
        running back along the line, positions off an existing profile's line (as for map
        tables)."""
        on_map = self._on_map()
        self.placement.set_guessed_spacing(None)
        warnings = [UNSTACKED] if result.provenance.get("unstacked") else []
        if result.provenance.get("repeats"):        # a warning, not a block
            warnings.append(REPEATS)
        box = self._trace_box()
        warnings += box.warnings()                  # an unusual velocity: not a block
        if box.position_warning():
            warnings.append(box.position_warning())
        outside = self._outside_crs() if on_map else ""
        if outside:
            warnings.append(outside)
            self._confirm.append(outside + ADD_ANYWAY)
        if on_map and self._line_error:
            warnings.append(self._line_error)
        try:
            placement = self.placement.placement()
            profile, sets, _new = self._draft()
        except ValueError as exc:
            if self._is_radar():
                self.radar_box.set_span(None, None, None)
            self.fit_label.setText(str(exc))
            self._set_warnings(warnings)
            return
        if self._is_radar():
            self._compare_lengths(result, profile, sets, placement)
        if on_map and self.placement.source() != "file":
            warnings += self._map_fit(result.provenance, "traces")
        zero = box.zero()
        if zero in NO_HEIGHTS and not self._has_heights(placement.profile_id):
            warnings.append(NO_HEIGHTS[zero])
        self._set_warnings(warnings)

    def _outside_crs(self) -> str:
        """``OUTSIDE_CRS`` when the first or last trace position lies outside the area of use
        of the chosen CRS, else "" (also when the CRS gives no area to check against)."""
        crs = self._trace_box().crs_widget.crs()
        if self._segy_ends is None or not self._is_segy() or not crs.isValid():
            return ""
        area = crs.bounds()                         # geographic degrees
        if area is None or area.isNull() or area.isEmpty() or \
                not all(math.isfinite(v) for v in (area.xMinimum(), area.yMinimum(),
                                                   area.xMaximum(), area.yMaximum())):
            return ""
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(crs, wgs84, self.project)
        for x, y in self._segy_ends:
            try:
                p = transform.transform(QgsPointXY(x, y))
                inside = math.isfinite(p.x()) and math.isfinite(p.y()) and \
                    area.contains(QgsPointXY(p.x(), p.y()))
            except QgsCsException:
                inside = False                      # beyond what the CRS can even reach
            if not inside:
                return OUTSIDE_CRS.format(crs=crs.description() or crs.authid())
        return ""

    def _has_heights(self, profile_id: str | None) -> bool:
        """Whether the profile the placement gives will have heights to hang a section from:
        an existing profile as the section reads it; a new one (no stations) only from the
        elevation model chosen in Context Layers."""
        if profile_id is not None and self.provider is not None:
            return not self.provider.is_local(profile_id)
        from ..section.topography import station_line
        if profile_id is not None and \
                station_line(self.store.station_sets(profile_id)) is not None:
            return True
        from .context_dialog import read_settings
        dem = read_settings(self.project).dem_layer_id
        return bool(dem) and self.project.mapLayer(dem) is not None

    def _install(self) -> None:
        """Install segyio on the user's click, in a QGIS task; the dialog stays usable."""
        if self._install_task is not None:
            return
        self._install_message = ""
        self.install_button.setEnabled(False)
        self.install_button.setText("Installing…")
        self._install_task = start_install(SEGYIO)
        self._install_task.done.connect(self._installed)

    @_guarded
    def _installed(self, ok: bool, message: str) -> None:
        self._install_task = None
        self._install_message = "" if ok else message
        self._segy_key = None                       # read the headers now
        self._refresh()

    # -- several files -----------------------------------------------------------------------
    def _check_files(self, columns_ok: bool) -> None:
        """Each file's row: the coarser cells offered for it and whether it is ready."""
        box = self.files_box
        box.set_on_map(self._on_map())
        names = self._table.names if self._is_table() and self._table is not None else None
        box.show_time_zero(self._is_radar())
        for row, (path, target) in enumerate(box.targets()):
            problem = self._file_problem(path, target, names, columns_ok)
            box.set_cells(row, "" if problem else self._cells_offer(path))
            box.set_status(row, problem or READY)
            if self._is_radar():
                box.set_time_zero(row, self._time_zero_text(path))

    def _file_problem(self, path: str, target, names, columns_ok: bool) -> str:
        if not Path(path).is_file():
            return "File not found"
        if self._is_traces():
            problem = (self._segy_file_problem(path, columns_ok) if self._is_segy() else
                       self._radar_file_problem(path, columns_ok))
            if problem:
                return problem
            return "" if target is not None else "Choose a profile"
        if not columns_ok:
            return "Assign the columns first (above)"
        if names is not None and path != self._path():
            try:
                theirs = read_table(path, self.table_options.options(), max_rows=1).names
            except (OSError, ValueError) as exc:
                return str(exc)
            if theirs != names:
                return "Other columns than the first file"
        if target is None:
            return "Choose a profile"
        return ""

    def _segy_file_problem(self, path: str, settings_ok: bool) -> str:
        """Why one of several SEG-Y files cannot be added with the box's settings ("" when it
        can)."""
        if not libs.available(SEGYIO):
            return "Install segyio first (above)"
        if not settings_ok or self.segy_box.problems():  # velocity too: it blocks Add
            return "Complete the SEG-Y settings first (above)"
        mtime = Path(path).stat().st_mtime
        cached = self._segy_infos.get(path)
        if cached is None or cached[0] != mtime:
            try:
                cached = (mtime, segy.inspect(path))
            except ValueError as exc:
                cached = (mtime, str(exc))
            self._segy_infos[path] = cached
        info = cached[1]
        if isinstance(info, str):
            return info
        if info.volume:
            return "A 3D volume: Groundwork shows 2D sections"
        o = self.segy_box.options()
        if o.get("position") == "map" and o.get("xy_field") not in info.positions:
            word = FIELD_WORDS.get(o.get("xy_field"), "chosen")
            return f"The file has no positions in the {word} fields that change"
        if o.get("position") == "table" and path != self._path():
            return "A coordinate file is for one file: add this file on its own"
        return ""

    def _radar_file_problem(self, path: str, settings_ok: bool) -> str:
        """Why one of several radar files cannot be added with the box's settings ("" when it
        can). Every file takes the box's velocity, and its own time zero."""
        if not settings_ok or self.radar_box.problems():
            return "Complete the radargram settings first (above)"
        if self.radar_box.position() == "table" and path != self._path():
            return "A coordinate file is for one file: add this file on its own"
        if self.radar_box.position() == "file":
            try:
                if self._reader() == "pulseekko":
                    from ..readers.pulseekko import inspect
                else:
                    from ..readers.gssi_dzt import inspect
                info = inspect(Path(path))
            except (OSError, ValueError) as exc:
                return str(exc)
            if info.length is None and info.trace_step is None:
                return "Recorded without a distance wheel: add it on its own"
        found = self._radar_time_zero(path)
        return found if isinstance(found, str) else ""

    def _radar_time_zero(self, path: str):
        """(time zero in s, how it was found) of one of several radar files, or why there is
        none: the box's for the file shown above it; for every other file the time zero its
        header states, else its own first-arrival estimate (from the stride of traces the
        estimate takes, ``sample_traces``: the whole file is read only when it is added).
        The velocity is the box's for all."""
        if path == self._path():
            t = self.radar_box.time_zero()
            if t is None:
                return "Enter time zero first (above)"
            return t, self.radar_box.time_zero_source()
        options = {k: v for k, v in self._radar_options(path).items() if k not in HANG_KEYS}
        key = (Path(path).stat().st_mtime, self._reader(), json.dumps(options, sort_keys=True))
        cached = self._radar_zeros.get(path)
        if cached is None or cached[0] != key:
            try:
                if self._reader() == "pulseekko":
                    from ..readers.pulseekko import inspect, sample_traces
                else:
                    from ..readers.gssi_dzt import inspect, sample_traces
                info = inspect(Path(path))
                if info.time_zero is not None:
                    found = (float(info.time_zero), "file")
                else:
                    found = (first_arrival(sample_traces(Path(path)), skip=info.reserved),
                             "estimate")
            except (OSError, ValueError) as exc:
                found = str(exc)
            cached = self._radar_zeros[path] = (key, found)
        return cached[1]

    def _time_zero_text(self, path: str) -> str:
        """A radar file's time zero for its row: "55.18 ns (estimated)"."""
        try:
            found = self._radar_time_zero(path)
        except OSError:
            return ""
        if isinstance(found, str):
            return ""
        t, how = found
        text = f"{fmt_trim(t * 1e9, 2)} ns"
        return {"estimate": f"{text} (estimated)", "file": f"{text} (from the file)"}.get(how,
                                                                                         text)

    def _cells_offer(self, path: str) -> str:
        """The coarser cells proposed for an over-fine text table ("" for none)."""
        if not self._is_table():
            return ""
        cols, options = self.columns_group.columns(), self.table_options.options()
        try:
            key = (Path(path).stat().st_mtime, json.dumps(options.to_dict(), sort_keys=True),
                   cols.position, cols.distance, cols.easting, cols.northing, cols.vertical)
            cached = self._file_grids.get(path)
            if cached is None or cached[0] != key:
                cached = (key, grid_of_file(path, options.to_dict(), cols.to_dict()))
                self._file_grids[path] = cached
            grid = cached[1]
        except (OSError, ValueError):
            grid = None
        block = proposed_block(grid) if grid is not None else None
        self._file_blocks[path] = block
        if block is None:
            return ""
        # as in the one-file box: a map file's spacing is walked along the ground, so it is
        # not exactly round (0.502 m: two decimals)
        return (f"{fmt_trim(block[0] * grid.dx, size_decimals(grid.dx))} × "
                f"{fmt_trim(block[1] * grid.dz, size_decimals(grid.dz))} m")

    def _file_placement(self, path: str, target) -> Placement:
        if target == FilesBox.NEW and self._is_segy():    # through the trace positions
            o = self.segy_box.options()
            line, _bends = line_from_cloud(xy_to_store(segy.map_positions(path, o),
                                                       o.get("crs", ""),
                                                       self.store.crs_authid, self.project))
            return Placement(line_xy=line)
        if target == FilesBox.NEW:                  # a line through the file's coordinates
            cols = self.columns_group.columns()
            xy = map_points(path, self.table_options.options().to_dict(), cols.to_dict())
            line, _bends = line_from_cloud(xy_to_store(xy, cols.crs, self.store.crs_authid,
                                                       self.project))
            return Placement(line_xy=line)
        return Placement(profile_id=target, zero="station1")

    def _file_options(self, path: str, coarse: bool) -> dict:
        if self._is_radar():                        # each line its own header file and
            options = self._radar_options(path)     # time zero; the velocity is shared
            found = self._radar_time_zero(path)
            if not isinstance(found, str):
                options["time_zero"] = found[0]
            return options
        options = {k: v for k, v in self._reader_options().items()
                   if k not in ("block", "response")}
        block = self._file_blocks.get(path)
        if coarse and block is not None:
            options["block"] = list(block)
        if self._reader() in RESPONSE_READERS:
            response = guess_response(path)         # each file's own, next to it
            if response:
                resp = Path(response)
                options["response"] = (resp.name if resp.parent.resolve() ==
                                       Path(path).parent.resolve() else str(resp))
        return options

    def _accept_files(self) -> None:
        """Add every ready file, after asking when some are not; one message for all."""
        self._refresh()
        box = self.files_box
        rows = box.targets()
        ready = [i for i in range(len(rows)) if box.status(i) == READY]
        left = [f"{Path(rows[i][0]).name} ({box.status(i).lower()})"
                for i in range(len(rows)) if i not in ready]
        if not ready:
            self._error("No file can be added yet:\n" + "\n".join(left))
            return
        if left and QMessageBox.question(
                self, self.windowTitle(),
                f"{len(left)} of {len(rows)} files cannot be added yet:\n" + "\n".join(left)
                + f"\n\nAdd the other {len(ready)} and leave these out?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        added, failed, notes = [], [], []
        for i in ready:
            path, target = rows[i]
            try:
                placement = self._file_placement(path, target)
                # the file shown above was read whole for its preview: not read again (a
                # file placed by map positions is read on its own target's line)
                shown = (self._preview_read() if path == self._path() and not self._on_map()
                         else None)
                try:
                    profile, dataset = add_data(
                        self.store, placement, Path(path), self._reader(),
                        self._file_options(path, box.cells_checked(i)),
                        readers.default_name(path, self._reader() or None),
                        self.method_combo.currentData(), self.project, self.provider,
                        result=shown)
                except NotRefreshed as exc:         # saved: never reported as a failure
                    profile, dataset = exc.saved
                    notes.append(str(exc))
            except Exception as exc:                # noqa: BLE001 - one file must not stop all
                failed.append(plain_error(exc, path, CHOOSE_OTHER, MISSING_FILE))
                continue
            added.append((profile, dataset, placement.profile_id is None))
            unplaced = unplaced_rows(dataset.provenance)
            if unplaced:
                notes.append(f"{_rows_word(unplaced)} of {Path(path).name} "
                             f"{'has' if unplaced == 1 else 'have'} no map position (-9999) "
                             f"and {'was' if unplaced == 1 else 'were'} left out.")
        if not added:
            self._error("\n".join(failed))
            return
        self.added = [(p, d) for p, d, _new in added]
        self.created = any(new for *_pd, new in added)
        self.profile, self.dataset = next(((p, d) for p, d, new in added if new),
                                          self.added[0])
        if left or failed or notes:
            text = f"{len(added)} of {len(rows)} files added."
            if left:
                text += " Left out: " + ", ".join(left) + "."
            if failed:
                text += " Not added: " + " ".join(failed)
            self._warn(" ".join([text] + notes))
        if self._is_table():
            QgsSettings().setValue(SETTINGS_KEY, json.dumps(
                {"names": self._table.names, "table": self.table_options.options().to_dict(),
                 "columns": self.columns_group.columns().to_dict()}))
        elif self._is_segy():
            _remember_segy(self._reader_options())
        elif self._is_radar():
            _remember_radar(self._reader_options())
        super().accept()

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
        if self._is_segy():
            self._segy_line()
            return
        if self._is_radar():
            self._radar_line()
            return
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
        unplaced = unplaced_rows(result.provenance)
        if on_map and unplaced:
            n = _rows_word(unplaced)
            warnings.append(f"{n} {'has' if unplaced == 1 else 'have'} no map position "
                            "(-9999) and will be left out.")
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
        if not readings and z_kind in HANGING_Z and station_line(sets) is None and \
                not self._has_heights(placement.profile_id):
            warnings.append(FLAT_MODEL)
        self._set_warnings(warnings)

    def _station_set_id(self, new_set) -> str | None:
        """The station set chosen for the dataset: a new one made from positions, else the
        one picked in "Station set" (None: the profile's first)."""
        return new_set.id if new_set is not None else self.station_set_combo.currentData()

    def _map_fit(self, provenance: dict, what: str = "cells") -> list[str]:
        offset = float(provenance.get("max_offset") or 0.0)
        beyond = int(provenance.get("n_beyond") or 0)
        text = f"{what.capitalize()} up to {fmt(offset, 1)} m from the line"
        if beyond:
            text += f"; {beyond} {'position lies' if beyond == 1 else 'positions lie'} " \
                    "beyond its ends"
        self.fit_label.setText(text)
        out = []
        if offset > OFF_LINE:
            out.append(f"Some {what} lie up to {fmt(offset, 1)} m from the profile line: is "
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

    def _preset_method(self, provenance: dict, quantity: str, propose: bool = True) -> None:
        """The method the file says (Refrapy, a velocity VTK), else the one of what it holds
        (P-wave velocity: refraction, otherwise ERT), never the previous file's; measured ERT
        data fix it to ERT. ``propose`` False only enables the row. Silent: the preview
        follows in the same refresh."""
        readings = provenance.get("kind") in READINGS_KINDS
        proposed = "ert" if readings else (provenance.get("method") or
                                           ("srt" if quantity == "p_velocity" else "ert"))
        self.method_combo.blockSignals(True)
        if propose or readings:
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
        if self._files:
            try:
                self._accept_files()
            except Exception as exc:                # noqa: BLE001 - a slot never raises
                self._error(plain_error(exc, None, CHOOSE_OTHER, MISSING_FILE))
            return
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
            placement = self._fitted(placement)
            try:
                self.profile, self.dataset = add_data(
                    self.store, placement, Path(path), self._reader(),
                    self._reader_options(), self._name(), self.method_combo.currentData(),
                    self.project, self.provider,
                    self.station_set_combo.currentData() if self._sets else None,
                    result=self._preview_read())
            except NotRefreshed as exc:             # saved: never reported as a failure
                self.profile, self.dataset = exc.saved
                self._warn(str(exc))
            # the preview read a sample: the whole file's count is known only now
            unplaced = unplaced_rows(self.dataset.provenance)
            if unplaced:
                self._warn(f"{_rows_word(unplaced)} of {Path(path).name} "
                           f"{'has' if unplaced == 1 else 'have'} no map position (-9999) "
                           f"and {'was' if unplaced == 1 else 'were'} left out.")
            self.created = placement.profile_id is None
        except Exception as exc:                    # noqa: BLE001 - a slot never raises
            self._error(plain_error(exc, path or None, CHOOSE_OTHER, MISSING_FILE))
            return
        if self._is_table():
            QgsSettings().setValue(SETTINGS_KEY, json.dumps(
                {"names": self._table.names, "table": self.table_options.options().to_dict(),
                 "columns": self.columns_group.columns().to_dict()}))
        elif self._is_segy():
            _remember_segy(self._reader_options())
        elif self._is_radar():
            _remember_radar(self._reader_options())
        self._result = self._read_key = None        # the dialog keeps no copy of the file
        super().accept()

    def _preview_read(self):
        """The radargram the preview read, when it was read as it is added (a radar file is
        read whole for the preview: it is not read again)."""
        if not self._is_radar() or self._result is None:
            return None
        profile = self._draft()[0] if self._on_map() else None
        return self._result if self._read_key == self._key(profile) else None

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
        if self._is_segy():
            if not libs.available(SEGYIO):
                raise ValueError(SEGYIO_MISSING)
            if self._segy_info is None:             # the headers say what is wrong
                raise ValueError(self.summary_label.text() or SEGYIO_MISSING)
            if self._segy_info.volume:
                raise ValueError(segy.volume_message(Path(self._path()).name, self._segy_info))
            problems = self.segy_box.problems()
            if problems:
                raise ValueError(" ".join(problems))
        if self._is_radar():
            if self._radar_info is None:            # the header says what is wrong
                raise ValueError(self.summary_label.text() or "Choose a radar file.")
            problems = self.radar_box.problems()
            if problems:
                raise ValueError(" ".join(problems))
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
        if self._install_task is not None:          # it finishes without the dialog
            try:
                self._install_task.done.disconnect(self._installed)
            except (TypeError, RuntimeError):
                pass
            self._install_task = None
        self.placement.cancel_pick()
        self.placement.clear_overlay()
        super().done(result)
