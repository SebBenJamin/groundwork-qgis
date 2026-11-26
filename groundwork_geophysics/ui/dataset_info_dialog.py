"""Dataset info…: what the user knows about a dataset, entered once (method, array, spacing,
date, inversion software and settings, reference, note). Shown next to what the readers
detected; used for the plates' provenance line.

A reflection section also shows its traces and samples and how it is hung (the vertical
rows of "SEG-Y Section": samples in time or depth, sample step, velocity, where time zero
lies and its height), which can be changed here; how its traces are placed cannot. When the
change moves the section and the profile has drawings in the shown interpretation version,
the user is asked first (the drawings stay at their heights)."""
from __future__ import annotations

import os

from qgis.PyQt.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
                                 QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
                                 QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..core.dataset_info import INFO_FIELDS, dataset_info, traces_text, with_info
from ..core.dataset_types import is_trace_kind

LABELS = {"method": "Method", "array": "Array", "spacing": "Electrode / geophone spacing",
          "date": "Acquisition date", "software": "Inversion software and settings",
          "reference": "Reference / citation", "note": "Note"}
HINTS = {"method": "e.g. ERT, seismic refraction", "array": "e.g. dipole-dipole, Wenner",
         "spacing": "e.g. 1 m", "date": "e.g. 2024-06-12",
         "software": "e.g. BERT, λ = 100, robust", "reference": "e.g. Pohle et al. 2025"}
#: a reflection section's words for the same info keys (it is processed, not inverted, and
#: has no electrode array); the stored keys stay ``software`` and ``spacing``
SECTION_LABELS = {"software": "Processing software and settings", "spacing": "Trace spacing"}
SECTION_HINTS = {"software": "e.g. migrated stack, contractor, year", "spacing": "e.g. 2 m"}
SECTION_TITLE = "Section"
#: the reader options edited here: how the samples are read (a change reads the file again)
#: and how the section is hung (``section.data.HANG_KEYS``; never read again)
READ_KEYS = ("domain", "sample_step")
MOVE_TEXT = "The section will move. Drawings on this profile stay at their heights. Change it?"
TEXT_TIP = "The 40 lines of text at the start of the file"
NO_TEXT_TIP = "The text header of {name} cannot be shown: {why}"


def _detected(d) -> str:
    p = d.provenance or {}
    parts = [f"File: {d.source_path}"] if d.source_path else []
    for key, label in (("rms_percent", "RMS {:.1f} %"), ("chi2", "χ² {:.2f}"),
                       ("n_readings", "{} readings")):
        value = p.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            parts.append(label.format(value))
    from ..core.dataset_info import averaged_from_text
    if averaged_from_text(d):
        parts.append(averaged_from_text(d))
    return " · ".join(parts) or "nothing detected"


def _edit_keys() -> tuple:
    from ..section.data import HANG_KEYS
    return READ_KEYS + tuple(HANG_KEYS)


def _hanging(options: dict) -> tuple:
    """What decides where a section's samples lie, with the provider's defaults filled in
    (so a stored option that only differs in its spelling counts as no change)."""
    from ..core.trace_section import Velocity
    o = options or {}
    domain = o.get("domain") or "time"
    zero = o.get("zero") or "ground"
    velocity = Velocity.from_options(o) if domain == "time" else None
    return (domain, o.get("sample_step"), velocity, zero,
            o.get("datum") if zero != "ground" else None,
            o.get("replacement_velocity") if zero == "datum_ground" else None)


def _stored_info(d):
    """A ``SegyInfo`` from what the reader recorded when the section was added (the file
    itself is not at hand); None when too little was recorded."""
    from ..readers.segy import SegyInfo
    p = d.provenance or {}
    try:
        return SegyInfo(int(p["n_traces"]), int(p["n_samples"]), float(p.get("step") or 0.0),
                        float(p.get("first") or 0.0), str(p.get("endian") or "big"),
                        int(p.get("sample_format") or 0), str(p.get("text") or ""), {},
                        p.get("velocity"), bool(p.get("unstacked", False)))
    except (KeyError, TypeError, ValueError):
        return None


class DatasetInfoDialog(QDialog):
    def __init__(self, store, dataset_id: str, parent=None, provider=None):
        super().__init__(parent)
        self.store = store
        self.provider = provider
        self.dataset = next(d for p in store.profiles() for d in store.datasets(p.id)
                            if d.id == dataset_id)
        #: True after OK saved new vertical settings (the section moved or is read again)
        self.moved = False
        self.segy_box = self.traces_label = self.text_button = None
        self._text = ""
        self.setWindowTitle(f"Dataset info – {self.dataset.name or self.dataset.id}")
        info = dataset_info(self.dataset)
        trace = is_trace_kind(self.dataset.kind)
        page = QWidget() if trace else self         # a section's rows scroll
        form = QFormLayout(page)
        self.detected = QLabel(_detected(self.dataset))
        self.detected.setWordWrap(True)
        form.addRow("Detected", self.detected)
        self.fields = {}
        for key in INFO_FIELDS:
            if key == "note":
                w = QPlainTextEdit(info.get(key, ""))
                w.setMaximumHeight(70)
            else:
                w = QLineEdit(info.get(key, ""))
                w.setPlaceholderText((SECTION_HINTS if trace else {}).get(key, HINTS.get(key, "")))
            form.addRow((SECTION_LABELS if trace else {}).get(key, LABELS[key]), w)
            if trace and key == "array":            # a section has no array: kept, not shown
                form.labelForField(w).hide()
                w.hide()
            self.fields[key] = w
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if not trace:
            form.addRow(buttons)
            self.resize(520, 360)
            return
        form.addRow(self._section_group())
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        outer = QVBoxLayout(self)
        outer.addWidget(scroll, 1)
        outer.addWidget(buttons)
        screen = self.screen().availableGeometry()
        hint = page.sizeHint()
        self.resize(min(max(560, hint.width() + 40), 1000),
                    min(hint.height() + 70, 580, screen.height() - 80))
        self._check()

    # -- a reflection section ------------------------------------------------------------------
    def _path(self) -> str:
        d = self.dataset
        if self.provider is not None:
            return self.provider.source_path(d)
        if os.path.isabs(d.source_path):
            return d.source_path
        return os.path.normpath(os.path.join(str(self.store.path.parent), d.source_path))

    def _file_info(self):
        """(``SegyInfo`` of the file, why it could not be read): the file's headers when it
        and segyio are there, else what was recorded when it was added."""
        from .. import libs
        path = self._path()
        name = os.path.basename(path) or self.dataset.name
        if not os.path.isfile(path):
            why = f"the file is not at {path}."
        elif not libs.available("segyio"):
            why = "reading SEG-Y needs the library segyio, which is not installed."
        else:
            from ..readers import segy
            try:
                return segy.inspect(path), ""
            except (OSError, ValueError) as exc:
                why = f"{exc}"
        return _stored_info(self.dataset), NO_TEXT_TIP.format(name=name, why=why)

    def _section_group(self) -> QGroupBox:
        from .segy_box import SegyBox
        group = QGroupBox(SECTION_TITLE)
        box_layout = QVBoxLayout(group)
        self.traces_label = QLabel(traces_text(self.dataset))
        self.traces_label.setWordWrap(True)
        box_layout.addWidget(self.traces_label)
        self.segy_box = SegyBox(vertical_only=True)
        self.segy_box.setTitle("")                  # its rows sit in this group, unframed
        self.segy_box.setStyleSheet("QGroupBox#segy_box { border: none; margin: 0; "
                                    "padding: 0; }")
        self.segy_box.layout().setContentsMargins(0, 0, 0, 0)
        info, why = self._file_info()
        if info is not None:
            self.segy_box.set_info(info, self._path())
        self.segy_box.set_options(self.dataset.reader_options or {})
        self.segy_box.changed.connect(self._check)
        box_layout.addWidget(self.segy_box)
        self.problems = QLabel()
        self.problems.setObjectName("segy_problems")
        self.problems.setWordWrap(True)
        box_layout.addWidget(self.problems)
        self.text_button = QPushButton("Text Header…")
        self._text = info.text if info is not None else ""
        self.text_button.setEnabled(bool(self._text))
        self.text_button.setToolTip(TEXT_TIP if self._text else why or
                                    NO_TEXT_TIP.format(name=self.dataset.name,
                                                       why="the file has none."))
        self.text_button.clicked.connect(self._show_text)
        row = QHBoxLayout()
        row.addWidget(self.text_button)
        row.addStretch(1)
        box_layout.addLayout(row)
        return group

    def _show_text(self) -> None:
        from .segy_box import TextHeaderDialog
        dialog = getattr(self, "text_dialog", None)
        if dialog is None:
            self.text_dialog = dialog = TextHeaderDialog(self._text, self)
        dialog.show()
        dialog.raise_()

    def _check(self) -> None:
        """OK waits for what the section cannot be hung without (said below the rows)."""
        problems = self.segy_box.problems() if self.segy_box is not None else []
        self.problems.setText(" ".join(problems))
        self.problems.setVisible(bool(problems))
        self.ok_button.setEnabled(not problems)
        self.ok_button.setToolTip(" ".join(problems))

    def new_options(self) -> dict:
        """The dataset's reader options with the vertical rows' values (placement kept)."""
        keys = _edit_keys()
        old = dict(self.dataset.reader_options or {})
        out = {k: v for k, v in old.items() if k not in keys}
        out.update({k: v for k, v in self.segy_box.options().items() if k in keys})
        return out

    def _drawings_here(self) -> bool:
        """True when the dataset's profile has interpretation pieces in the version the
        section shows (the current one unless a frozen one is shown)."""
        store = self.store
        try:
            if not store.has_interpretation():
                return False
            version = self.provider.shown_interp_version() if self.provider is not None \
                else store.current_version().id
            return version is not None and bool(store.pieces(version,
                                                             self.dataset.profile_id))
        except Exception:                       # noqa: BLE001 - an unreadable store: ask
            return True

    # -- out -------------------------------------------------------------------------------------
    def values(self) -> dict:
        return {k: (w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text())
                for k, w in self.fields.items()}

    def accept(self):
        d = with_info(self.dataset, self.values())
        if self.segy_box is not None:
            from dataclasses import replace
            options = self.new_options()
            moves = _hanging(options) != _hanging(self.dataset.reader_options)
            if moves and self._drawings_here():
                answer = QMessageBox.question(
                    self, "Dataset Info", MOVE_TEXT,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No)
                if answer != QMessageBox.StandardButton.Yes:
                    return                      # nothing saved; the dialog stays open
            if moves:
                d = replace(d, reader_options=options)
                self.moved = True
        self.store.save_dataset(d)
        super().accept()
