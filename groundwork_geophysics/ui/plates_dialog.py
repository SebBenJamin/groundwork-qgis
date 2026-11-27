"""Plates…: report plates with stacked section frames, each with its own look.

Left the plates; right the selected plate's number, title, template and its frames (profile,
look, from–to, scale, VE). "Take from Section Panel" copies the panel's current look into a
frame; restyling the panel later does not change the plate. "Create / Update Plates" makes or
refreshes the layouts; "Export Plates…" refreshes them and writes the PDFs."""
from __future__ import annotations

import copy
import datetime
import uuid
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                                 QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
                                 QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox,
                                 QPushButton,
                                 QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout,
                                 QWidget)

from .help import add_help_button
from ..core.plates import FrameLook, FrameSpec, PlateSpec
from ..plates.build import DETAILS, STALE_PROPERTY, TEMPLATES, create_or_update_plate, \
    find_plate_layout, plate_details, plate_logo, plate_name, set_plate_details, set_plate_logo
from ..plates.sources import detach_frame_items, read_plates, write_plates

OWN_TEMPLATE = "__own__"
TEMPLATE_LABELS = {"A4_landscape": "A4 landscape", "A4_portrait": "A4 portrait",
                   "A3_landscape": "A3 landscape", "A3_portrait": "A3 portrait"}
COLUMNS = ("Profile", "Look", "From (m)", "To (m)", "Scale 1:", "VE")


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


def panel_look(provider, profile_id: str) -> FrameLook:
    """The section panel's current look of ``profile_id``, copied (not shared)."""
    from ..section.style_store import look_of
    models = [look_of(d.id, provider.style(d.id)) for d in provider.store.datasets(profile_id)]
    return FrameLook(models, getattr(provider, "interp_version_id", None), True,
                     bool(provider.show_field_notes), True)


def parse_cell(attr: str, text: str):
    """A frame cell as typed: empty = automatic (None). Scales take "2500", "1:2500" or
    "1.000" (dots, commas and spaces in a scale are thousands separators); distances and VE
    take "," or "." as decimal separator. Raises ValueError for anything unusable."""
    import math
    import re

    from ..core.numbers import parse
    t = (text or "").strip()
    if not t:
        return None
    if attr == "scale":
        t = re.sub(r"^1\s*:\s*", "", t)
        # a whole number; separators only between groups of three ("2.500", "1 000 000"),
        # so "2500.0" is refused instead of read as 25000
        if not re.fullmatch(r"\d{1,3}([.,'\s ]\d{3})*|\d+", t):
            raise ValueError(text)
        value = int(re.sub(r"\D", "", t))
        if value < 1:
            raise ValueError(text)
        return value
    value = parse(t)
    if not math.isfinite(value) or (attr == "ve" and value <= 0):
        raise ValueError(text)
    return value


def cell_text(attr: str, value) -> str:
    """How a frame cell shows its value: in QGIS's locale; empty for automatic."""
    from ..core.numbers import fmt_trim
    if value is None:
        return ""
    return str(int(value)) if attr == "scale" else fmt_trim(value, 3)


def look_summary(look: FrameLook, names: dict, traces=frozenset()) -> str:
    """The frame's look in a line; a reflection section (its id in ``traces``) is named as
    its layer row names it ("clip 98 % · AGC"), not by a model's display mode."""
    shown = [m for m in look.models if m.visible]
    parts = []
    for m in shown:
        extra = f", {round(m.opacity * 100)} %" if m.opacity < 1.0 else ""
        mode = _trace_look(m) if m.dataset_id in traces else m.mode
        parts.append(f"{names.get(m.dataset_id, 'missing model')} ({mode}{extra})")
    parts = parts or ["no models"]
    flags = [name for name, on in (("boreholes", look.boreholes), ("notes", look.field_notes),
                                   ("context", look.context)) if on]
    parts.append("interpretation: " + ("frozen version" if look.interp_version else "latest"))
    if flags:
        parts.append(", ".join(flags))
    return " · ".join(parts)


def _trace_look(m) -> str:
    from types import SimpleNamespace

    from ..core.trace_section import DisplayGain
    from ..section.layer_list import trace_look_text
    scale = m.scale if isinstance(m.scale, dict) else {}
    limits = SimpleNamespace(vmin=scale["vmin"], vmax=scale["vmax"]) \
        if all(isinstance(scale.get(k), (int, float)) for k in ("vmin", "vmax")) else None
    return trace_look_text(m.clip_percent, DisplayGain.from_dict(m.gain), limits,
                           getattr(m, "max_depth", None))


class PlateDetailsDialog(QDialog):
    """Project-wide title block values, shown on every plate."""

    def __init__(self, project, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plate details")
        self.setMinimumWidth(440)                   # room for the logo's path
        self.project = project
        values = plate_details(project)
        if not values.get("date"):
            values["date"] = datetime.date.today().isoformat()
        form = QFormLayout()
        self.fields = {}
        for key, caption in DETAILS:
            edit = QLineEdit(values.get(key, ""))
            self.fields[key] = edit
            form.addRow(caption, edit)
        self.logo = QLineEdit(plate_logo(project))
        self.logo.setReadOnly(True)
        self.logo.setPlaceholderText("No logo")
        self.logo.setToolTip("An image shown in the logo cell of the title block")
        choose = QPushButton("Choose…")
        choose.clicked.connect(self._choose_logo)
        self.logo_clear = QPushButton("Clear")
        self.logo_clear.clicked.connect(self.logo.clear)
        row = QHBoxLayout()
        row.addWidget(self.logo, 1)
        row.addWidget(choose)
        row.addWidget(self.logo_clear)
        form.addRow("Logo", row)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        add_help_button(buttons, "plate_details")
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Shown in the title block of every plate of this project."))
        layout.addLayout(form)
        layout.addWidget(buttons)

    def accept(self):
        set_plate_details(self.project, **{k: e.text().strip() for k, e in self.fields.items()})
        set_plate_logo(self.project, self.logo.text())
        super().accept()

    def _choose_logo(self):
        start = self.project.absolutePath() or str(Path.home())
        path, _ = QFileDialog.getOpenFileName(self, "Choose a Logo", start,
                                              "Images (*.png *.jpg *.jpeg *.svg)")
        if path:
            self.logo.setText(path)


class PlatesDialog(QDialog):
    def __init__(self, project, store, provider, panel_profile=lambda: None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plates")
        self.resize(980, 520)
        self.project, self.store, self.provider = project, store, provider
        self.panel_profile = panel_profile
        self.plates: list[PlateSpec] = read_plates(project)
        self._filling = False
        self.failed: list[str] = []

        self.plate_list = QListWidget()
        self.plate_list.setObjectName("plate_list")
        self.plate_list.currentRowChanged.connect(self._show_plate)
        add, dup, delete = (QPushButton(t) for t in ("Add", "Duplicate", "Delete"))
        add.clicked.connect(lambda: self.add_plate())
        dup.clicked.connect(lambda: self.duplicate_plate())
        delete.clicked.connect(lambda: self.delete_plate())
        left = QVBoxLayout()
        left.addWidget(QLabel("Plates"))
        left.addWidget(self.plate_list)
        row = QHBoxLayout()
        for b in (add, dup, delete):
            row.addWidget(b)
        left.addLayout(row)

        self.number, self.title = QLineEdit(), QLineEdit()
        self.number.setObjectName("plate_number")
        self.number.editingFinished.connect(self._header_edited)
        self.title.editingFinished.connect(self._header_edited)
        self.template = QComboBox()
        for key in TEMPLATES:
            self.template.addItem(TEMPLATE_LABELS[key], key)
        self.template.addItem("Own template…", OWN_TEMPLATE)
        self.template.setToolTip("The page the plate's layout is made from. Choosing another "
                                 "for a plate that has a layout makes it again (asks first).")
        self.template.currentIndexChanged.connect(self._template_changed)
        head = QFormLayout()
        head.addRow("Number", self.number)
        head.addRow("Title", self.title)
        head.addRow("Template", self.template)

        self.frames = QTableWidget(0, len(COLUMNS))
        self.frames.setObjectName("frames")
        self.frames.setHorizontalHeaderLabels(COLUMNS)
        self.frames.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.frames.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.frames.setToolTip("Frames are stacked top to bottom. Empty from/to, scale and VE "
                               "fit the page; frames of one profile share them.")
        self.frames.cellChanged.connect(self._cell_changed)
        add_frame, remove_frame, take = (QPushButton(t) for t in (
            "Add Frame", "Remove Frame", "Take from Section Panel"))
        add_frame.clicked.connect(lambda: self.add_frame())
        remove_frame.clicked.connect(lambda: self.remove_frame(self.frames.currentRow()))
        take.setObjectName("take_from_panel")
        take.clicked.connect(lambda: self.take_from_panel(max(self.frames.currentRow(), 0)))
        take.setToolTip("Copy the section panel's profile and current look (models, colour "
                        "scales, display, opacity, interpretation version, field notes) into "
                        "the selected frame.")
        frame_buttons = QHBoxLayout()
        for b in (add_frame, remove_frame, take):
            frame_buttons.addWidget(b)
        frame_buttons.addStretch(1)

        right = QVBoxLayout()
        right.addLayout(head)
        right.addWidget(QLabel("Section frames"))
        right.addWidget(self.frames)
        right.addLayout(frame_buttons)
        self.editor = QWidget()
        self.editor.setLayout(right)

        split = QSplitter()
        lw = QWidget()
        lw.setLayout(left)
        split.addWidget(lw)
        split.addWidget(self.editor)
        split.setStretchFactor(1, 3)

        details = QPushButton("Plate Details…")
        details.setObjectName("plate_details")
        details.clicked.connect(self.edit_details)
        create = QPushButton("Create / Update Plates")
        create.setObjectName("create_plates")
        create.clicked.connect(lambda: self.create_plates())
        export = QPushButton("Export Plates…")
        export.setObjectName("export_plates")
        export.clicked.connect(lambda: self.export_dialog())
        self.combined = QCheckBox("One combined PDF")
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bottom = QHBoxLayout()
        for w in (details, create, export, self.combined):
            bottom.addWidget(w)
        bottom.addStretch(1)
        help_box = QDialogButtonBox()
        add_help_button(help_box, "plates")
        bottom.addWidget(help_box)
        bottom.addWidget(close)
        self.message = QLabel("")
        self.message.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.addWidget(split, 1)
        layout.addWidget(self.message)
        layout.addLayout(bottom)
        self._fill_list()

    # -- helpers ---------------------------------------------------------------------------
    def _profiles(self) -> list:
        return self.store.profiles()

    def _dataset_names(self) -> dict:
        names = {}
        for p in self._profiles():
            for d in self.store.datasets(p.id):
                names[d.id] = d.name
        return names

    def _trace_ids(self) -> set:
        """The reflection sections among the datasets (named by their clip, not a mode)."""
        from ..core.dataset_types import is_trace_kind
        return {d.id for p in self._profiles() for d in self.store.datasets(p.id)
                if is_trace_kind(d.kind)}

    def _save(self) -> None:
        write_plates(self.project, self.plates)

    def current_plate(self) -> PlateSpec | None:
        row = self.plate_list.currentRow()
        return self.plates[row] if 0 <= row < len(self.plates) else None

    def _fill_list(self, select: int | None = None) -> None:
        self.plate_list.blockSignals(True)
        self.plate_list.clear()
        for plate in self.plates:
            self.plate_list.addItem(plate_name(plate))
        self.plate_list.blockSignals(False)
        if self.plates:
            row = select if select is not None else 0
            self.plate_list.setCurrentRow(min(max(row, 0), len(self.plates) - 1))
        self._show_plate(self.plate_list.currentRow())

    def _show_plate(self, row: int) -> None:
        plate = self.current_plate()
        self.editor.setEnabled(plate is not None)
        self._filling = True
        try:
            self.number.setText(plate.number if plate else "")
            self.title.setText(plate.title if plate else "")
            if plate is not None:
                index = self.template.findData(plate.template)
                if index < 0:
                    self.template.insertItem(self.template.count() - 1,
                                             Path(plate.template).name, plate.template)
                    index = self.template.findData(plate.template)
                self.template.setCurrentIndex(index)
            self._fill_frames()
        finally:
            self._filling = False

    def _fill_frames(self) -> None:
        plate = self.current_plate()
        was = self._filling
        self._filling = True
        try:
            self.frames.setRowCount(0)
            if plate is None:
                return
            profiles = self._profiles()
            names, traces = self._dataset_names(), self._trace_ids()
            for r, f in enumerate(plate.frames):
                self.frames.insertRow(r)
                combo = QComboBox()
                for p in profiles:
                    combo.addItem(p.name, p.id)
                if combo.findData(f.profile_id) < 0:
                    combo.addItem(f"(missing profile {f.profile_id})", f.profile_id)
                combo.setCurrentIndex(combo.findData(f.profile_id))
                combo.currentIndexChanged.connect(
                    lambda _i, c=combo, frame=f: self._profile_changed(frame, c.currentData()))
                self.frames.setCellWidget(r, 0, combo)
                look = QTableWidgetItem(look_summary(f.look, names, traces))
                look.setFlags(look.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.frames.setItem(r, 1, look)
                for c, attr in ((2, "s_from"), (3, "s_to"), (4, "scale"), (5, "ve")):
                    self.frames.setItem(r, c, QTableWidgetItem(cell_text(attr,
                                                                         getattr(f, attr))))
        finally:
            self._filling = was

    # -- plates ------------------------------------------------------------------------------
    def add_plate(self) -> PlateSpec:
        numbers = {p.number for p in self.plates}
        n = len(self.plates) + 1
        while str(n) in numbers:
            n += 1
        plate = PlateSpec(_new_id(), str(n), "New plate", "A3_landscape", [])
        profile_id = self.panel_profile()
        if profile_id and any(p.id == profile_id for p in self._profiles()):
            plate.title = self.store.profile(profile_id).name
            plate.frames.append(FrameSpec(_new_id(), profile_id,
                                          panel_look(self.provider, profile_id)))
        self.plates.append(plate)
        self._save()
        self._fill_list(len(self.plates) - 1)
        return plate

    def duplicate_plate(self) -> PlateSpec | None:
        plate = self.current_plate()
        if plate is None:
            return None
        twin = copy.deepcopy(plate)
        twin.plate_id = _new_id()
        twin.title = f"{plate.title} (copy)"
        for f in twin.frames:
            f.frame_id = _new_id()
        self.plates.append(twin)
        self._save()
        self._fill_list(len(self.plates) - 1)
        return twin

    def delete_plate(self) -> None:
        row = self.plate_list.currentRow()
        if not 0 <= row < len(self.plates):
            return
        name = plate_name(self.plates.pop(row))
        self._save()
        self._fill_list(row)
        self.message.setText(f"{name} removed from the plates. Its layout stays in the "
                             f"project; delete it in the Layout Manager if not needed.")

    def _header_edited(self) -> None:
        plate = self.current_plate()
        if plate is None or self._filling:
            return
        plate.number = self.number.text().strip() or plate.number
        plate.title = self.title.text().strip() or plate.title
        self.plate_list.currentItem().setText(plate_name(plate))
        self._save()

    def _template_changed(self, index: int) -> None:
        plate = self.current_plate()
        if plate is None or self._filling:
            return
        key = self.template.itemData(index)
        if key == OWN_TEMPLATE:
            path, _ = QFileDialog.getOpenFileName(self, "Own plate template", "",
                                                  "QGIS layout templates (*.qpt)")
            if not path:
                self._filling = True
                self.template.setCurrentIndex(max(self.template.findData(plate.template), 0))
                self._filling = False
                return
            self.template.insertItem(self.template.count() - 1, Path(path).name, path)
            key = path
            self._filling = True
            self.template.setCurrentIndex(self.template.findData(path))
            self._filling = False
        layout = find_plate_layout(self.project, plate)
        if layout is not None and key != plate.template:
            if not self.confirm_remake(plate):  # keep the layout, and the setting that made it
                self._filling = True
                self.template.setCurrentIndex(max(self.template.findData(plate.template), 0))
                self._filling = False
                return
            detach_frame_items(self.project)
            self.project.layoutManager().removeLayout(layout)
            plate.template = key
            self._save()
            try:
                create_or_update_plate(self.project, self.store, self.provider, plate)
            except Exception as exc:            # the message says it; Update tries again
                self.message.setText(f"{plate_name(plate)}: {exc}")
                return
            self.message.setText(f"{plate_name(plate)} made again from the template "
                                 f"{self.template.currentText()}.")
            return
        plate.template = key
        self._save()

    def confirm_remake(self, plate: PlateSpec) -> bool:
        """Ask before a new template replaces a plate's existing layout."""
        answer = QMessageBox.question(
            self, "Change template",
            f"{plate_name(plate)} already has a layout. Make it again from the new template?"
            "\n\nChanges made to it in QGIS's layout designer are lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        return answer == QMessageBox.StandardButton.Yes

    # -- frames ------------------------------------------------------------------------------
    def add_frame(self) -> FrameSpec | None:
        plate = self.current_plate()
        profiles = self._profiles()
        if plate is None or not profiles:
            return None
        pid = self.panel_profile() or profiles[0].id
        frame = FrameSpec(_new_id(), pid, panel_look(self.provider, pid))
        plate.frames.append(frame)
        self._save()
        self._fill_frames()
        return frame

    def remove_frame(self, row: int) -> None:
        plate = self.current_plate()
        if plate is None or not 0 <= row < len(plate.frames):
            return
        plate.frames.pop(row)
        self._save()
        self._fill_frames()

    def take_from_panel(self, row: int) -> None:
        plate = self.current_plate()
        pid = self.panel_profile()
        if plate is None or not 0 <= row < len(plate.frames):
            return
        if not pid:
            self.message.setText("Open a profile in the section panel first.")
            return
        frame = plate.frames[row]
        frame.profile_id = pid
        frame.look = panel_look(self.provider, pid)
        self._save()
        self._fill_frames()
        self.message.setText("Frame look taken from the section panel.")

    def _profile_changed(self, frame: FrameSpec, profile_id) -> None:
        if self._filling or not profile_id or profile_id == frame.profile_id:
            return
        frame.profile_id = profile_id
        frame.look = panel_look(self.provider, profile_id)
        frame.s_from = frame.s_to = None
        self._save()
        self._fill_frames()

    def _cell_changed(self, row: int, column: int) -> None:
        plate = self.current_plate()
        if self._filling or plate is None or not 0 <= row < len(plate.frames) or column < 2:
            return
        frame = plate.frames[row]
        text = self.frames.item(row, column).text()
        attr = {2: "s_from", 3: "s_to", 4: "scale", 5: "ve"}[column]
        try:
            value = parse_cell(attr, text)
        except ValueError:
            self.message.setText(f"{COLUMNS[column].rstrip(':')}: “{text.strip()}” is not a "
                                 "usable number. Type e.g. 2500 for 1:2500, or leave the cell "
                                 "empty for automatic.")
            self._fill_frames()
            return
        self.message.setText("")
        setattr(frame, attr, value)
        self._save()

    # -- actions -------------------------------------------------------------------------------
    def edit_details(self) -> None:
        PlateDetailsDialog(self.project, self).exec()

    def create_plates(self) -> list:
        layouts, failed = [], []
        for plate in self.plates:
            try:
                layouts.append(create_or_update_plate(self.project, self.store, self.provider,
                                                      plate))
            except Exception as exc:            # one bad plate must not stop the others
                failed.append(f"{plate_name(plate)}: {exc}")
        self.plates = read_plates(self.project)
        self._fill_list(self.plate_list.currentRow())
        text = f"{len(layouts)} plate(s) created or updated – open them from the Layout Manager."
        tight = [f"{layout.name()}: {layout.customProperty('wb_not_fitting')}"
                 for layout in layouts if layout.customProperty("wb_not_fitting")]
        if tight:
            text += (" Does not fit even at the smallest scale (set a From/To range or a "
                     "scale): " + "; ".join(tight) + ".")
        if any("field notes" in (layout.customProperty(STALE_PROPERTY) or [])
               for layout in layouts):
            text += (" Your edited field-notes text was kept, but the notes have changed. To "
                     "get the new text, delete the label's text and press Update.")
        if failed:
            text += " Failed: " + "; ".join(failed)
        self.failed = failed
        self.message.setText(text)
        return layouts

    def export_dialog(self) -> None:
        from ..plates.export import export_plates
        folder = QFileDialog.getExistingDirectory(self, "Export plates to folder")
        if not folder:
            return
        self.create_plates()
        if self.failed:                         # never export plates that failed to update
            self.message.setText(self.message.text() + " Nothing was exported.")
            return
        try:
            paths = export_plates(self.project, Path(folder), self.combined.isChecked())
        except OSError as exc:
            self.message.setText(f"Export failed: {exc}")
            return
        self.message.setText(f"{self.message.text()} Exported {len(paths)} PDF file(s) to "
                             f"{folder}.")
