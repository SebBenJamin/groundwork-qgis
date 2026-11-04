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
FILE_FILTER = ("Model and data files (*.dat *.txt *.xyz *.vtk *.data *.ohm);;"
               "All files (*)")
#: readers whose files hold readings and take a model-response file
RESPONSE_READERS = ("bert_data",)
#: response files looked for next to a data file
RESPONSE_NAMES = ("response.vector", "{stem}_response.vector", "{stem}.response",
                  "dcinv.response")


def describe(result: readers.ReaderResult, z_kind: str | None) -> str:
    """One-line summary of a reader result for the preview label."""
    mesh = result.mesh
    r = getattr(mesh, "readings", None)
    if r is not None:
        x0, x1 = float(np.nanmin(r.a)), float(np.nanmax(np.r_[r.b, r.m, r.n]))
        text = f"{len(r)} readings, electrodes x {x0:.1f} – {x1:.1f} m"
        if r.has_calculated:
            rms, chi2 = r.rms_percent(), r.chi2()
            text += f" · misfit RMS {rms:.1f} %" if rms is not None else ""
            text += f", χ² {chi2:.2f}" if chi2 is not None else ""
        else:
            text += " · measured data only (add a response file for the misfit)"
        return text
    xmin, xmax, zmin, zmax = mesh.bounds()
    values = mesh.values[np.isfinite(mesh.values)]
    z_word = {"elevation": "elevation", "depth": "depth"}.get(z_kind, "Z meaning not set")
    text = (f"x {xmin:.1f} – {xmax:.1f} m, z {zmin:.1f} – {zmax:.1f} m ({z_word}) · "
            f"{len(mesh.values)} cells · values {values.min():.3g} – {values.max():.3g} "
            f"{mesh.unit}" if len(values) else "no values")
    n_masked = int(result.provenance.get("n_masked") or 0)
    if n_masked and result.provenance.get("reconstruction") == "delaunay":
        text += f" · {n_masked} fill/NaN values skipped"
    elif n_masked:
        text += f" · {n_masked} {'cell' if n_masked == 1 else 'cells'} without a value (shown blank)"
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
        self._key = None                            # (path, reader, z_kind) of the cached read
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
        self.response_edit = QLineEdit()
        self.response_edit.setPlaceholderText("optional: calculated values of the inversion")
        self.response_edit.setToolTip("Model response (one calculated value per reading), "
                                      "e.g. BERT's response.vector or a pyGIMLi response: "
                                      "with it the layer shows the misfit")
        self.response_edit.editingFinished.connect(self._response_changed)
        response_browse = QPushButton("Browse…")
        response_browse.clicked.connect(self._browse_response)
        self.response_row = QHBoxLayout()
        self.response_row.addWidget(self.response_edit)
        self.response_row.addWidget(response_browse)
        self._response_browse = response_browse
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
        form.addRow("Response file", self.response_row)
        self._form = form
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

    def _response_visible(self) -> bool:
        return self.reader_combo.currentData() in RESPONSE_READERS

    def _sync_response_row(self) -> None:
        self._form.setRowVisible(self.response_row, self._response_visible())

    def _guess_response(self, path: str) -> str:
        data = Path(path)
        for pattern in RESPONSE_NAMES:
            candidate = data.parent / pattern.format(stem=data.stem)
            if candidate.is_file():
                return str(candidate)
        return ""

    def _browse_response(self):
        path, _ = QFileDialog.getOpenFileName(self, "Model response file", "",
                                              "Response (*.vector *.response *.txt);;"
                                              "All files (*)")
        if path:
            self.response_edit.setText(path)
            self._response_changed()

    def _response_changed(self) -> None:
        self._key = None                            # the response changes what is read
        self._update_preview()

    def _reader_options(self) -> dict:
        if self._response_visible() and self.response_edit.text().strip():
            return {"response": self.response_edit.text().strip()}
        return {}

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
            self.response_edit.setText(self._guess_response(path)
                                       if self.reader_combo.currentData() in RESPONSE_READERS
                                       else "")
            if self.name_edit.text() in ("", self._auto_name):
                self._auto_name = Path(path).stem
                self.name_edit.setText(self._auto_name)
        self._update_preview()

    def _update_preview(self) -> None:
        self._sync_response_row()
        path, reader = self.file_edit.text().strip(), self.reader_combo.currentData()
        self._set_warning("")
        if not path:
            self.preview.setText("Choose a model file.")
            return
        new_file = self._key is None or self._key[:2] != (path, reader)
        if new_file:                                # the file's own z hint presets "Z means"
            if not self._read(path, reader, None):
                return
            self.z_combo.blockSignals(True)         # unknown -> choose
            self.z_combo.setCurrentIndex(max(0, self.z_combo.findData(self._result.z_kind)))
            self.z_combo.blockSignals(False)
            self._key = (path, reader, self.z_combo.currentData())
        z_kind = self.z_combo.currentData()
        if self._key[2] != z_kind and not self._read(path, reader, z_kind):
            return                                  # re-read: z decides the top edge
        self.preview.setStyleSheet("")
        self.preview.setText(describe(self._result, self.z_combo.currentData()))
        self._set_warning(self.overhang_warning())

    def _read(self, path: str, reader: str, z_kind: str | None) -> bool:
        """Read ``path`` with the chosen z meaning into the cache; show failures (which
        are not cached, so the next preview reads again)."""
        self._key, self._result = None, None
        options = {"z_kind": z_kind} if z_kind else {}
        options.update(self._reader_options())
        try:
            self._result = readers.read(path, reader=reader, **options)
        except FileNotFoundError:
            self._show_error(f"File not found: {path}")
            return False
        except (ValueError, OSError) as exc:
            self._show_error(str(exc))
            return False
        self._key = (path, reader, z_kind)
        return True

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
            if self._key != (path, self.reader_combo.currentData(), self.z_combo.currentData()):
                self._update_preview()              # the overhang check needs this read
            warning = self.overhang_warning() if self._key is not None else ""
            if warning and QMessageBox.question(
                    self, self.windowTitle(), warning,
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
                return
            options = {"chainage_offset": self.offset_spin.value()}
            response = self._reader_options().get("response")
            if response:                    # stored next to the data file when it is there
                resp, data = Path(response), Path(path)
                options["response"] = (resp.name if resp.parent.resolve() ==
                                       data.parent.resolve() else str(resp))
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
