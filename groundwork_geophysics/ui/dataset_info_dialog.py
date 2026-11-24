"""Dataset info…: what the user knows about a dataset, entered once (method, array, spacing,
date, inversion software and settings, reference, note). Shown next to what the readers
detected; used for the plates' provenance line."""
from __future__ import annotations

from qgis.PyQt.QtWidgets import (QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit,
                                 QPlainTextEdit)

from ..core.dataset_info import INFO_FIELDS, dataset_info, with_info

LABELS = {"method": "Method", "array": "Array", "spacing": "Electrode / geophone spacing",
          "date": "Acquisition date", "software": "Inversion software and settings",
          "reference": "Reference / citation", "note": "Note"}
HINTS = {"method": "e.g. ERT, seismic refraction", "array": "e.g. dipole-dipole, Wenner",
         "spacing": "e.g. 1 m", "date": "e.g. 2024-06-12",
         "software": "e.g. BERT, λ = 100, robust", "reference": "e.g. Pohle et al. 2025"}


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


class DatasetInfoDialog(QDialog):
    def __init__(self, store, dataset_id: str, parent=None):
        super().__init__(parent)
        self.store = store
        self.dataset = next(d for p in store.profiles() for d in store.datasets(p.id)
                            if d.id == dataset_id)
        self.setWindowTitle(f"Dataset info – {self.dataset.name or self.dataset.id}")
        info = dataset_info(self.dataset)
        form = QFormLayout(self)
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
                w.setPlaceholderText(HINTS.get(key, ""))
            form.addRow(LABELS[key], w)
            self.fields[key] = w
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)
        self.resize(520, 360)

    def values(self) -> dict:
        return {k: (w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text())
                for k, w in self.fields.items()}

    def accept(self):
        self.store.save_dataset(with_info(self.dataset, self.values()))
        super().accept()
