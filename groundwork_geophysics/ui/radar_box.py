"""'Radargram': how a radar file (GSSI .dzt, pulseEKKO .dt1 + .hd) is hung (the radar velocity,
typed as a velocity or as a dielectric constant; time zero; where time zero lies) and how its
traces are placed along the profile (the distances in the file, a trace spacing, or a
coordinate file).

The same public shape as ``segy_box.SegyBox``: used by Add Data, and by Dataset Info with its
vertical rows only (``vertical_only``). The box knows the file only through its
``RadarInfo``; ``set_info`` / ``set_options`` / ``set_estimate`` are silent, ``changed``
follows every edit by the user (typed numbers on ``editingFinished`` only).

Units: ``options()`` and the stored options are in seconds and m/s; the fields show ns, m/ns
and the dielectric constant, typed and shown in QGIS's locale (a decimal comma always works).
A velocity or time zero taken from the file is marked so, until the user edits it; nothing is
assumed: without a dielectric in the header the velocity is empty and needed."""
from __future__ import annotations

import math

import numpy as np
from qgis.core import QgsCoordinateReferenceSystem, QgsProject
from qgis.gui import QgsProjectionSelectionWidget
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (QButtonGroup, QCheckBox, QGridLayout, QGroupBox, QLabel,
                                 QRadioButton, QSizePolicy, QWidget)

from ..core.numbers import fmt_count
from ..core.trace_section import (BAD_DIELECTRIC, BAD_RADAR_VELOCITY, BEYOND_RECORD,
                                  C_M_PER_NS, NOT_A_TIME_ZERO)
from ..readers.radar_info import RadarInfo
from .trace_fields import (NO_CRS, NO_DATUM, NO_SPACING, CoordinateFile, line_edit, note,
                           number, positive, row, show, zero_combo)

TITLE = "Radargram"
NS = 1e-9
LIGHT = C_M_PER_NS * 1e9                    # m/s
FROM_FILE = "from the file"
#: a dielectric in a GSSI header is what the instrument was set to, not a measurement
FROM_HEADER = "from the file's header (an instrument setting; check it)"
ESTIMATED = "estimated from the first arrival (first break of the direct wave)"
NO_WHEEL = "This file was recorded without a distance wheel."
NO_WHEEL_TIP = "The file holds no distances: enter the trace spacing"
NO_VELOCITY = "Enter the velocity or the dielectric constant."
NO_TIME_ZERO = "Enter time zero in ns."
FACTS_LENGTH = "{length} m from the distance wheel"
LENGTH_TEXT = ("The file is {file} m long, the stretch from From to To {line} m "
               "({share} % {word}).")
SAME_LENGTH = "The file and the stretch from From to To are both {file} m long."
FIT_TEXT = "Fit the file between these two points"
FIT_TIP = ("Stretch the file's distances evenly so that its first trace lies at From and its last "
           "trace at To")
FROM_TIP = ("Where the file's first trace lies along the profile, in m; untouched, it follows "
            "\"Distance 0 is at\" and the offset")
TO_TIP = ("Where the file's last trace lies along the profile, in m: smaller than From runs the "
          "file against the profile's direction. Without the tick only From and the direction "
          "count")
NO_SPAN = "Enter From and To in metres along the profile."
#: To smaller than From: From and To decide the direction, whatever "Distance 0 is at" says
AGAINST_NOTE = "The file runs against the profile's direction."
SMOOTHING_TIP = ("Average the ground under the radargram over this length along the profile "
                 "before hanging it, so that steps of the elevation model do not show as "
                 "seams; 0 hangs it on the ground as sampled. The ground line itself is not "
                 "smoothed")
#: m: the ground under a new radargram is averaged over this length
DEFAULT_SMOOTHING = 2.0
BAD_SMOOTHING = "The smoothing length must be 0 m or more."
SAME_POINTS = "From and To must be two different points."
VELOCITY_TIP = ("Radar velocity in the ground, in m/ns (0.1 m/ns is common in dry sand); "
                "Groundwork assumes none")
DIELECTRIC_TIP = "Relative dielectric constant: the velocity is 0.2998 m/ns divided by its root"
TIME_ZERO_TIP = "Samples before time zero are above the ground and are not drawn."
#: the "Time zero is" choices of a radargram (no correction to the ground)
ZEROS = ("ground", "datum")
#: metres: lengths closer than this are the same
SAME = 0.005


def _velocity_text(v_m_s: float) -> str:
    return show(v_m_s / 1e9, 4)


def _dielectric_text(eps: float) -> str:
    return show(eps, 2)


class RadarBox(QGroupBox):
    changed = pyqtSignal()

    def __init__(self, vertical_only: bool = False, parent=None):
        super().__init__(TITLE, parent)
        self.setObjectName("radar_box")
        self.vertical_only = vertical_only
        self.info: RadarInfo | None = None
        self.path = ""                              # the radar file ("" when not known)
        self._busy = True                           # no slot runs before the rows exist
        self._exact: dict = {}                      # field -> (text shown, exact value)
        self._velocity_from = "velocity"            # the field the velocity is taken from
        self._time_zero_from = None                 # "file", "estimate", "stored", "user"
        self._position_chosen = False
        self._span = None                           # (file length, From, To) offered, m
        self._span_typed = False                    # From or To typed by the user
        self._crs_chosen: QgsCoordinateReferenceSystem | None = None
        prj = QgsProject.instance().crs()
        self._default_crs = prj if prj.isValid() else QgsCoordinateReferenceSystem()
        self._build()
        self._busy = False
        self._sync()

    # -- building ----------------------------------------------------------------------------
    def _build(self) -> None:
        self.facts_label = note("radar_facts")
        self.velocity_edit = line_edit("velocity_edit", VELOCITY_TIP, self._velocity_typed)
        self.velocity_edit.setPlaceholderText("m/ns")
        self.dielectric_edit = line_edit("dielectric_edit", DIELECTRIC_TIP,
                                         self._dielectric_typed)
        self.velocity_note = note("velocity_note")
        self.time_zero_edit = line_edit("time_zero_edit", TIME_ZERO_TIP, self._time_zero_typed)
        self.time_zero_edit.setPlaceholderText("ns")
        self.time_zero_note = note("time_zero_note")
        self.zero_combo = zero_combo("radar_zero_combo", ZEROS, self._edited)
        self.datum_edit = line_edit("datum_edit", "Height of time zero above sea level, in m",
                                    self._edited)
        self.smoothing_edit = line_edit("smoothing_edit", SMOOTHING_TIP, self._edited)
        self.smoothing_edit.setText(show(DEFAULT_SMOOTHING, 2))
        group = QButtonGroup(self)
        self.by_file, self.by_spacing, self.by_table = (
            QRadioButton(t) for t in ("Distance in the file", "Trace spacing", "A coordinate file"))
        for r in (self.by_file, self.by_spacing, self.by_table):
            group.addButton(r)
            r.toggled.connect(lambda on: on and self._edited())
            r.clicked.connect(self._position_clicked)
        self.by_file.setChecked(True)
        self.position_note = note("position_note")
        self.from_edit = line_edit("from_edit", FROM_TIP, self._span_edited)
        self.to_edit = line_edit("to_edit", TO_TIP, self._span_edited)
        self.length_label = note("length_label")
        self.direction_note = note("direction_note")
        self.fit_check = QCheckBox(FIT_TEXT)
        self.fit_check.setObjectName("fit_check")
        self.fit_check.setToolTip(FIT_TIP)
        self.fit_check.toggled.connect(lambda _on: self._edited())
        self.spacing_edit = line_edit("spacing_edit", "Distance between two traces along the line",
                                      self._edited)
        self.coords = CoordinateFile(self, "radar", self._trace_numbers, lambda: self.path,
                                     lambda: self._busy)
        self.coords.chosen.connect(self._table_chosen)
        self.coords.changed.connect(self._edited)
        self.crs_widget = QgsProjectionSelectionWidget()
        self.crs_widget.setObjectName("radar_crs")
        self.crs_widget.setToolTip("Coordinate reference system of the trace positions")
        self.crs_widget.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        self.crs_widget.crsChanged.connect(self._crs_edited)

        rows = (("facts", "", self.facts_label),
                ("velocity", "Velocity (m/ns)",
                 row(self.velocity_edit, QLabel("Dielectric constant"), self.dielectric_edit)),
                ("velocity_note", "", self.velocity_note),
                ("time_zero", "Time zero (ns)", row(self.time_zero_edit)),
                ("time_zero_note", "", self.time_zero_note),
                ("zero", "Time zero is", row(self.zero_combo)),
                ("datum", "Height of time zero (m)", row(self.datum_edit)),
                ("smoothing", "Smooth the ground over (m)", row(self.smoothing_edit)),
                ("position", "Traces are placed by",
                 row(self.by_file, self.by_spacing, self.by_table)),
                ("position_note", "", self.position_note),
                ("span", "From (m)", row(self.from_edit, QLabel("To (m)"), self.to_edit)),
                ("direction", "", self.direction_note),
                ("length", "", self.length_label),
                ("fit", "", self.fit_check),
                ("spacing", "Trace spacing (m)", row(self.spacing_edit)),
                ("table_file", "Coordinate file", self.coords.file),
                ("table_options", "", self.coords.options_box),
                ("columns", "", self.coords.columns_row),
                ("table_note", "", self.coords.note),
                ("crs", "CRS", self.crs_widget))
        grid = QGridLayout(self)
        grid.setColumnStretch(1, 1)
        self._rows: dict[str, tuple[QLabel, QWidget]] = {}
        for r, (name, text, widget) in enumerate(rows):
            label = QLabel(text)
            if name == "facts":
                grid.addWidget(widget, r, 0, 1, 2)
            else:
                grid.addWidget(label, r, 0)
                grid.addWidget(widget, r, 1)
            self._rows[name] = (label, widget)
        chain = (self.velocity_edit, self.dielectric_edit, self.time_zero_edit, self.zero_combo,
                 self.datum_edit, self.smoothing_edit, self.by_file, self.by_spacing,
                 self.by_table, self.from_edit, self.to_edit, self.fit_check, self.spacing_edit,
                 self.coords.file, self.coords.number_combo, self.coords.easting_combo,
                 self.coords.northing_combo, self.crs_widget)
        for first, second in zip(chain, chain[1:]):
            QWidget.setTabOrder(first, second)

    # -- in ------------------------------------------------------------------------------------
    def set_default_crs(self, crs: QgsCoordinateReferenceSystem) -> None:
        """The CRS offered for a coordinate file (normally the project's)."""
        self._default_crs = QgsCoordinateReferenceSystem(crs)
        self._preset_crs()

    def _preset_crs(self) -> None:
        was, self._busy = self._busy, True
        self.crs_widget.setCrs(self._crs_chosen or self._default_crs)
        self._busy = was

    def set_info(self, info: RadarInfo, path: str | None = None) -> None:
        """Show what the header of ``path`` says. Another file starts afresh: its velocity
        (only from a dielectric the header states), its time zero (only when stated; else the
        estimate comes later, ``set_estimate``), its height and CRS; the user's choices of
        where time zero lies and how the traces are placed stay. Silent."""
        new_file = self.info is None or str(path or "") != self.path
        self.info, self.path = info, str(path or "")
        self.coords.forget()
        self._busy = True
        try:
            self.facts_label.setText(self._facts())
            if new_file:
                self._crs_chosen = None
                self.datum_edit.clear()
                self.smoothing_edit.setText(show(DEFAULT_SMOOTHING, 2))
                self.spacing_edit.clear()
                self.fit_check.setChecked(False)
                self._span, self._span_typed = None, False
                self._fill_velocity(info.velocity if info.dielectric else None,
                                    FROM_HEADER if info.dielectric else "")
                if info.dielectric:
                    self._velocity_from = "dielectric"
                    self._set_exact(self.dielectric_edit, _dielectric_text(info.dielectric),
                                    float(info.dielectric))
                self._fill_time_zero(info.time_zero, FROM_FILE)
                self._time_zero_from = "file" if info.time_zero is not None else None
            wheel = info.length is not None or info.trace_step is not None
            self.by_file.setEnabled(wheel)
            self.by_file.setToolTip("" if wheel else NO_WHEEL_TIP)
            if not wheel and self.by_file.isChecked():
                self.by_spacing.setChecked(True)
            elif wheel and not self._position_chosen:
                self.by_file.setChecked(True)
            self._preset_crs()
            if self.coords.path_text():
                self.coords.read_columns(keep=True)
        finally:
            self._busy = False
        self._sync()

    def set_estimate(self, time_zero: float) -> None:
        """Time zero estimated from the samples (s), shown only when nothing else gives one
        (the file, stored options or the user's own number win). Silent."""
        if self._time_zero_from is not None or time_zero is None or \
                not math.isfinite(time_zero):
            return
        self._busy = True
        try:
            self._fill_time_zero(float(time_zero), ESTIMATED)
            self._time_zero_from = "estimate"
        finally:
            self._busy = False
        self._sync()

    def set_line_length(self, file_length: float | None, line_length: float | None) -> None:
        """A new line: From 0 and To its length (``set_span``). Silent."""
        self.set_span(file_length, 0.0, line_length)

    def set_span(self, file_length: float | None, start: float | None,
                 end: float | None) -> None:
        """The file's length and where the placement puts its first and last trace along the
        profile (m), offered in From and To while the user has not typed there; None when
        there is no line to fit to (the fields and the tick are then hidden and not given).
        Silent."""
        values = (file_length, start, end)
        ok = all(v is not None and math.isfinite(v) for v in values) and file_length > 0
        self._span = tuple(float(v) for v in values) if ok else None
        if self._span is not None and not self._span_typed:
            self._busy = True
            try:
                self._set_exact(self.from_edit, show(self._span[1], 2), self._span[1])
                self._set_exact(self.to_edit, show(self._span[2], 2), self._span[2])
            finally:
                self._busy = False
        self._sync()

    def set_options(self, options: dict) -> None:
        """Show stored options; keys that are missing keep what is shown. Silent."""
        o = options or {}
        self._busy = True
        try:
            if o.get("velocity") is not None:
                try:
                    v = float(o["velocity"])
                except (TypeError, ValueError):
                    v = None
                self._fill_velocity(v, "")
            if o.get("time_zero") is not None:
                try:
                    self._fill_time_zero(float(o["time_zero"]), "")
                    self._time_zero_from = "stored"
                except (TypeError, ValueError):
                    self.time_zero_edit.setText(str(o["time_zero"]))
            if o.get("zero") in ZEROS:
                self.zero_combo.setCurrentIndex(self.zero_combo.findData(o["zero"]))
            if o.get("datum") is not None:
                self.datum_edit.setText(show(float(o["datum"]), 3))
            if o.get("ground_smoothing") is not None:
                try:
                    self.smoothing_edit.setText(show(float(o["ground_smoothing"]), 2))
                except (TypeError, ValueError):
                    self.smoothing_edit.setText(str(o["ground_smoothing"]))
            if not self.vertical_only:
                self._set_placement(o)
        finally:
            self._busy = False
        self._sync()

    def _set_placement(self, o: dict) -> None:
        position = o.get("position")
        if position == "file" and self.by_file.isEnabled():
            self.by_file.setChecked(True)
        elif position == "spacing":
            self.by_spacing.setChecked(True)
        elif position == "table":
            self.by_table.setChecked(True)
        self._position_chosen = self._position_chosen or position in ("file", "spacing", "table")
        if o.get("spacing") is not None:
            self.spacing_edit.setText(show(float(o["spacing"]), 3))
        if o.get("crs"):
            self._crs_chosen = QgsCoordinateReferenceSystem(str(o["crs"]))
            self._preset_crs()
        if o.get("positions_file"):
            self.coords.set_options(o)

    def set_zero(self, zero: str) -> None:
        i = self.zero_combo.findData(zero)
        if i >= 0:
            self.zero_combo.setCurrentIndex(i)
        self._sync()

    def set_positions_file(self, path: str) -> None:
        """Use the coordinate file ``path`` (as if chosen): its layout and columns guessed."""
        self.coords.set_file(path)

    def _fill_velocity(self, v_m_s: float | None, why: str) -> None:
        """Both velocity fields from ``v_m_s`` (empty for None), with the note ``why``."""
        self._exact.pop(self.velocity_edit, None)
        self._exact.pop(self.dielectric_edit, None)
        self._velocity_from = "velocity"
        if v_m_s is None or not math.isfinite(v_m_s):
            self.velocity_edit.clear()
            self.dielectric_edit.clear()
        else:
            self._set_exact(self.velocity_edit, _velocity_text(v_m_s), v_m_s)
            if 0 < v_m_s <= LIGHT:
                self.dielectric_edit.setText(_dielectric_text((LIGHT / v_m_s) ** 2))
            else:
                self.dielectric_edit.clear()
        self.velocity_note.setText(why if v_m_s is not None else "")

    def _fill_time_zero(self, t: float | None, why: str) -> None:
        self._exact.pop(self.time_zero_edit, None)
        if t is None:
            self.time_zero_edit.clear()
            self.time_zero_note.setText("")
            return
        self._set_exact(self.time_zero_edit, show(t / NS, 2), t)
        self.time_zero_note.setText(why)

    def _set_exact(self, edit, text: str, value: float) -> None:
        """Show ``text`` in ``edit`` but keep ``value`` while the text is not changed (a
        rounded figure never moves a section)."""
        edit.setText(text)
        self._exact[edit] = (text, value)

    def _exact_or(self, edit, scale: float) -> float | None:
        held = self._exact.get(edit)
        if held is not None and held[0] == edit.text():
            return held[1]
        v = number(edit.text())
        return None if v is None else v * scale

    # -- out -----------------------------------------------------------------------------------
    def zero(self) -> str:
        return self.zero_combo.currentData()

    def position(self) -> str:
        if self.by_file.isChecked():
            return "file"
        return "table" if self.by_table.isChecked() else "spacing"

    def warnings(self) -> list[str]:
        """Nothing to warn about without stopping the radargram (the shape of ``SegyBox``)."""
        return []

    def position_warning(self) -> str:
        return ""

    def velocity(self) -> float | None:
        """The velocity (m/s) the fields give, None when it is missing or impossible."""
        if self._velocity_from == "dielectric":
            eps = self._exact_or(self.dielectric_edit, 1.0)
            return LIGHT / math.sqrt(eps) if eps is not None and eps >= 1 else None
        v = self._exact_or(self.velocity_edit, 1e9)
        return v if v is not None and 0 < v <= LIGHT * (1 + 1e-12) else None

    def time_zero(self) -> float | None:
        """Time zero (s) as typed, None when it is not a number."""
        return self._exact_or(self.time_zero_edit, NS)

    def time_zero_source(self) -> str | None:
        """Where the time zero shown comes from: "file", "estimate", "stored", "user", or
        None before there is one."""
        return self._time_zero_from

    def options(self) -> dict:
        """The reader options and the hanging (``velocity`` m/s, ``time_zero`` s, ``zero``,
        ``datum``); ``span`` (From, To in m) when the user typed them and ``fit_length`` when
        the file is to be fitted between them; only the keys that apply, and only values that
        can be read."""
        o: dict = {}
        if not self.vertical_only:
            o.update(self._placement_options())
        v = self.velocity()
        if v is not None:
            o["velocity"] = v
        t = self.time_zero()
        if t is not None:
            o["time_zero"] = t
        o["zero"] = self.zero()
        if o["zero"] != "ground":
            datum = number(self.datum_edit.text())
            if datum is not None:
                o["datum"] = datum
        else:
            smoothing = number(self.smoothing_edit.text())
            if smoothing is not None and smoothing >= 0:
                o["ground_smoothing"] = smoothing
        if self._fit_shown():
            span = self.span()
            if self._span_typed and span is not None:
                o["span"] = span
            if self.fit_check.isChecked():
                o["fit_length"] = True
        return o

    def span(self) -> tuple[float, float] | None:
        """(From, To) in m as shown (typed or offered), None when hidden or unreadable."""
        if not self._fit_shown():
            return None
        a, b = self._exact_or(self.from_edit, 1.0), self._exact_or(self.to_edit, 1.0)
        return None if a is None or b is None else (a, b)

    def _placement_options(self) -> dict:
        position = self.position()
        o: dict = {"position": position}
        if position == "spacing":
            spacing = positive(self.spacing_edit.text())
            if spacing is not None:
                o["spacing"] = spacing
        elif position == "table":
            o.update(self.coords.options())
            crs = self.crs_widget.crs()
            if crs.isValid():
                o["crs"] = crs.authid() or "WKT:" + crs.toWkt()
        return o

    def problems(self) -> list[str]:
        """What must be entered before the radargram can be read and hung."""
        return self.read_problems() + self.hang_problems() + self.span_problems()

    def span_problems(self) -> list[str]:
        """From and To, when shown: two numbers, and two points to fit between."""
        if not self._fit_shown():
            return []
        span = self.span()
        if span is None:
            return [NO_SPAN]
        if self.fit_check.isChecked() and abs(span[1] - span[0]) < SAME:
            return [SAME_POINTS]
        return []

    def read_problems(self) -> list[str]:
        """What the file cannot be read without: the trace positions."""
        if self.vertical_only:
            return []
        position = self.position()
        if position == "spacing":
            return [] if positive(self.spacing_edit.text()) is not None else [NO_SPACING]
        if position == "table":
            out = self.coords.problems()
            return out + ([] if self.crs_widget.crs().isValid() else [NO_CRS])
        return []

    def hang_problems(self) -> list[str]:
        """What the radargram cannot be hung without: velocity, time zero, height."""
        out = self._velocity_problems()
        text = self.time_zero_edit.text().strip()
        t = self.time_zero()
        if not text:
            out.append(NO_TIME_ZERO)
        elif t is None:
            out.append(NOT_A_TIME_ZERO)
        elif self.info is not None:
            end = self.info.first + (max(1, self.info.n_samples) - 1) * self.info.step
            if t > end + 1e-6 * self.info.step:
                out.append(BEYOND_RECORD)
        if self.zero() != "ground" and number(self.datum_edit.text()) is None:
            out.append(NO_DATUM)
        if self.zero() == "ground":
            smoothing = number(self.smoothing_edit.text())
            if smoothing is None or smoothing < 0:
                out.append(BAD_SMOOTHING)
        return out

    def _velocity_problems(self) -> list[str]:
        if self._velocity_from == "dielectric":
            text, scale, edit = self.dielectric_edit.text(), 1.0, self.dielectric_edit
        else:
            text, scale, edit = self.velocity_edit.text(), 1e9, self.velocity_edit
        value = self._exact_or(edit, scale)
        if not text.strip() or value is None:
            return [NO_VELOCITY]
        if self._velocity_from == "dielectric":
            return [] if value >= 1 else [BAD_DIELECTRIC]
        return [] if 0 < value <= LIGHT * (1 + 1e-12) else [BAD_RADAR_VELOCITY]

    # -- texts ---------------------------------------------------------------------------------
    def _facts(self) -> str:
        i = self.info
        parts = [f"{fmt_count(i.n_traces)} traces × {fmt_count(i.n_samples)} samples",
                 f"{show(i.window / NS, 1)} ns"]
        if i.antenna:
            parts.append(i.antenna)
        if i.length is not None:
            parts.append(FACTS_LENGTH.format(length=show(i.length, 2)))
        return " · ".join(parts)

    def _length_text(self) -> str:
        span = self.span()
        if span is None:
            return ""
        file_length, line_length = self._span[0], abs(span[1] - span[0])
        if abs(line_length - file_length) < SAME:
            return SAME_LENGTH.format(file=show(file_length, 2))
        share = abs(line_length - file_length) / file_length * 100.0
        return LENGTH_TEXT.format(file=show(file_length, 2), line=show(line_length, 2),
                                  share=show(round(share, 1), 1),
                                  word="shorter" if line_length < file_length else "longer")

    def _fit_shown(self) -> bool:
        return not self.vertical_only and self.position() == "file" and self._span is not None

    # -- state ---------------------------------------------------------------------------------
    def _trace_numbers(self):
        return None if self.info is None else np.arange(1, self.info.n_traces + 1)

    def _velocity_typed(self) -> None:
        if self._busy:
            return
        held = self._exact.get(self.velocity_edit)
        if held is not None and held[0] == self.velocity_edit.text():
            return                                  # focus left the field, nothing typed
        self._exact.pop(self.velocity_edit, None)
        self._exact.pop(self.dielectric_edit, None)
        self._velocity_from = "velocity"
        v = number(self.velocity_edit.text())
        self.dielectric_edit.setText(_dielectric_text((C_M_PER_NS / v) ** 2)
                                     if v is not None and 0 < v <= C_M_PER_NS else "")
        self.velocity_note.setText("")
        self._edited()

    def _dielectric_typed(self) -> None:
        if self._busy:
            return
        held = self._exact.get(self.dielectric_edit)
        if held is not None and held[0] == self.dielectric_edit.text():
            return
        self._exact.pop(self.velocity_edit, None)
        self._exact.pop(self.dielectric_edit, None)
        self._velocity_from = "dielectric"
        eps = number(self.dielectric_edit.text())
        self.velocity_edit.setText(_velocity_text(LIGHT / math.sqrt(eps))
                                   if eps is not None and eps >= 1 else "")
        self.velocity_note.setText("")
        self._edited()

    def _time_zero_typed(self) -> None:
        if self._busy:
            return
        held = self._exact.get(self.time_zero_edit)
        if held is not None and held[0] == self.time_zero_edit.text():
            return
        self._exact.pop(self.time_zero_edit, None)
        self._time_zero_from = "user"
        self.time_zero_note.setText("")
        self._edited()

    def _span_edited(self) -> None:
        if self._busy:
            return
        if all(self._exact.get(e) is not None and self._exact[e][0] == e.text()
               for e in (self.from_edit, self.to_edit)):
            return                                  # focus left the field, nothing typed
        self._span_typed = True
        self._edited()

    def _crs_edited(self, *_args) -> None:
        if self._busy:
            return
        self._crs_chosen = QgsCoordinateReferenceSystem(self.crs_widget.crs())
        self._edited()

    def _position_clicked(self, *_args) -> None:
        self._position_chosen = True

    def _table_chosen(self) -> None:
        self._busy = True
        try:
            self.by_table.setChecked(True)
            self._position_chosen = True
        finally:
            self._busy = False
        self._edited()

    def _edited(self, *_args) -> None:
        if self._busy:
            return
        self._sync()
        self.changed.emit()

    def _sync(self) -> None:
        place = not self.vertical_only
        position = self.position()
        no_wheel = self.info is not None and not self.by_file.isEnabled()
        self.position_note.setText(NO_WHEEL if place and no_wheel else "")
        fit = self._fit_shown()
        self.length_label.setText(self._length_text() if fit else "")
        span = self.span() if fit else None
        self.direction_note.setText(AGAINST_NOTE if span is not None and span[1] < span[0]
                                    else "")
        shown = {
            "facts": place and bool(self.facts_label.text()),     # Dataset Info has its own
            "velocity": True, "velocity_note": bool(self.velocity_note.text()),
            "time_zero": True, "time_zero_note": bool(self.time_zero_note.text()),
            "zero": True, "datum": self.zero() != "ground",
            "smoothing": self.zero() == "ground",
            "position": place, "position_note": bool(self.position_note.text()),
            "span": fit, "length": fit and bool(self.length_label.text()),
            "direction": fit and bool(self.direction_note.text()),
            "fit": fit,
            "spacing": place and position == "spacing",
            "table_file": place and position == "table",
            "table_options": place and position == "table",
            "columns": place and position == "table",
            "table_note": place and position == "table",
            "crs": place and position == "table"}
        for name, on in shown.items():
            label, widget = self._rows[name]
            label.setVisible(on and bool(label.text()))
            widget.setVisible(on)
        for w in (self.by_file, self.by_spacing, self.by_table):
            w.setVisible(place)
        self.coords.note.setText(self.coords.note_text(
            self.info.n_traces if self.info is not None else None)
            if shown["table_note"] else "")
        self.coords.note.setVisible(bool(self.coords.note.text()))
