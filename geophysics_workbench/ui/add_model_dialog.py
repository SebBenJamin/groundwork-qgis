"""'Add ERT model' dialog: pick a model file, check what it contains, save it to a profile."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from qgis.PyQt.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
                                 QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                                 QMessageBox, QPushButton, QVBoxLayout)

from .. import readers
from ..core.coverage import overhang_message
from ..core.model import x_to_chainage
from .project_actions import add_model

Z_ITEMS = [("Choose…", None), ("Elevation", "elevation"), ("Depth below surface", "depth")]
FILE_FILTER = "Model files (*.dat *.txt *.xyz *.vtk);;All files (*)"


def describe(result: readers.ReaderResult, z_kind: str | None) -> str:
    """One-line summary of a reader result for the preview label."""
    mesh = result.mesh
    xmin, xmax, zmin, zmax = mesh.bounds()
    values = mesh.values[np.isfinite(mesh.values)]
    z_word = {"elevation": "elevation", "depth": "depth"}.get(z_kind, "Z meaning not set")
    text = (f"x {xmin:.1f} – {xmax:.1f} m, z {zmin:.1f} – {zmax:.1f} m ({z_word}) · "
            f"{len(mesh.values)} cells · values {values.min():.3g} – {values.max():.3g} "
            f"{mesh.unit}" if len(values) else "no values")
    n_masked = int(result.provenance.get("n_masked") or 0)
    if n_masked:
        text += f" · {n_masked} fill/NaN values skipped"
    return text


class AddModelDialog(QDialog):
    def __init__(self, iface, store, profile_id: str, provider=None, parent=None):
        super().__init__(parent if parent is not None else iface.mainWindow())
        self.iface, self.store, self.profile_id, self.provider = iface, store, profile_id, provider
        profile = store.profile(profile_id)
        self.profile_name = profile.name
        self.setWindowTitle(f"Add ERT model to {profile.name}")
        self.dataset = None
        self.last_error = None
        self._key = None                            # (path, reader) of the cached read
        self._result = None
        self._auto_name = ""

        self.file_edit = QLineEdit()
        self.file_edit.editingFinished.connect(lambda: self.set_file(self.file_edit.text()))
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        file_row = QHBoxLayout()
        file_row.addWidget(self.file_edit)
        file_row.addWidget(browse)

        self.reader_combo = QComboBox()
        for name in readers.names():
            self.reader_combo.addItem(readers.get(name).label, name)
        self.reader_combo.currentIndexChanged.connect(lambda _i: self._update_preview())
        self.z_combo = QComboBox()
        for label, value in Z_ITEMS:
            self.z_combo.addItem(label, value)
        self.z_combo.currentIndexChanged.connect(lambda _i: self._update_preview())
        self.offset_spin = QDoubleSpinBox()
        self.offset_spin.setRange(-1e6, 1e6)
        self.offset_spin.setDecimals(2)
        self.offset_spin.setSuffix(" m")
        self.offset_spin.setToolTip("Added to the file's x (m) to place the model on the profile")
        self.offset_spin.valueChanged.connect(lambda _v: self._update_preview())
        self.set_combo = QComboBox()
        self._sets = {}
        for s in store.station_sets(profile_id):
            self._sets[s.id] = s
            self.set_combo.addItem(s.name or s.id, s.id)
        self.set_combo.currentIndexChanged.connect(lambda _i: self._update_preview())
        self.name_edit = QLineEdit()
        self.preview = QLabel("Choose a model file.")
        self.preview.setWordWrap(True)
        self.warning = QLabel()                     # model reaches far beyond the stations
        self.warning.setWordWrap(True)
        self.warning.setStyleSheet("color: #9a5b00;")
        self.warning.hide()

        form = QFormLayout()
        form.addRow("File", file_row)
        form.addRow("Format", self.reader_combo)
        form.addRow("Z means", self.z_combo)
        form.addRow("Chainage offset", self.offset_spin)
        form.addRow("Station set", self.set_combo)
        form.addRow("Dataset name", self.name_edit)
        form.addRow("Preview", self.preview)
        form.addRow("", self.warning)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.resize(560, self.sizeHint().height())

    # -- file and preview --------------------------------------------------------------------
    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "ERT model file", "", FILE_FILTER)
        if path:
            self.set_file(path)

    def set_file(self, path) -> None:
        path = str(path)
        self.file_edit.setText(path)
        if path:
            found = readers.detect(path)
            if found:
                self.reader_combo.blockSignals(True)
                self.reader_combo.setCurrentIndex(max(0, self.reader_combo.findData(found[0])))
                self.reader_combo.blockSignals(False)
            if self.name_edit.text() in ("", self._auto_name):
                self._auto_name = Path(path).stem
                self.name_edit.setText(self._auto_name)
        self._update_preview()

    def _update_preview(self) -> None:
        path, reader = self.file_edit.text().strip(), self.reader_combo.currentData()
        self._set_warning("")
        if not path:
            self.preview.setText("Choose a model file.")
            return
        key = (path, reader)
        if key != self._key:
            self._key, self._result = key, None
            try:
                self._result = readers.read(path, reader=reader)
            except FileNotFoundError:
                self._key = None                    # failures are not cached: re-read next time
                self._show_error(f"File not found: {path}")
                return
            except (ValueError, OSError) as exc:
                self._key = None
                self._show_error(str(exc))
                return
            self.z_combo.blockSignals(True)         # preset from the file; unknown -> choose
            self.z_combo.setCurrentIndex(max(0, self.z_combo.findData(self._result.z_kind)))
            self.z_combo.blockSignals(False)
        self.preview.setStyleSheet("")
        self.preview.setText(describe(self._result, self.z_combo.currentData()))
        self._set_warning(self.overhang_warning())

    def overhang_warning(self) -> str:
        """Warning when the read model, placed with the chosen station set and offset,
        reaches more than two station spacings before or beyond the stations; else ""."""
        station_set = self._sets.get(self.set_combo.currentData())
        if self._result is None or station_set is None:
            return ""
        xmin, xmax = self._result.mesh.bounds()[:2]
        s = x_to_chainage([xmin, xmax], station_set, self.offset_spin.value())
        return overhang_message(s[0], s[1], station_set, self.profile_name)

    def _set_warning(self, text: str) -> None:
        self.warning.setText(text)
        self.warning.setVisible(bool(text))

    def _show_error(self, message: str) -> None:
        self.preview.setStyleSheet("color: #b00020;")
        self.preview.setText(message)

    # -- saving ------------------------------------------------------------------------------
    def accept(self) -> None:
        path = self.file_edit.text().strip()
        try:
            if not path:
                raise ValueError("Choose a model file")
            if self.set_combo.currentData() is None:
                raise ValueError("This profile has no station set to place the model on")
            if self._key != (path, self.reader_combo.currentData()):
                self._update_preview()              # the overhang check needs this file
            warning = self.overhang_warning() if self._key is not None else ""
            if warning and QMessageBox.question(
                    self, self.windowTitle(), warning,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            options = {"chainage_offset": self.offset_spin.value()}
            if self.z_combo.currentData():
                options["z_kind"] = self.z_combo.currentData()
            self.dataset = add_model(self.store, self.profile_id, self.set_combo.currentData(),
                                     Path(path), self.reader_combo.currentData(), options,
                                     self.name_edit.text().strip(), provider=self.provider)
        except FileNotFoundError:
            self._error(f"File not found: {path}")
            return
        except (ValueError, OSError, RuntimeError) as exc:     # RuntimeError: GDAL write
            self._error(str(exc))
            return
        super().accept()

    def _error(self, message: str) -> None:
        self.last_error = message
        QMessageBox.warning(self, self.windowTitle(), message)
