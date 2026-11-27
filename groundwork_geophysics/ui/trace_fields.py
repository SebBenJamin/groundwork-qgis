"""Field pieces shared by the boxes that say how a trace section is read, hung and placed
("SEG-Y Section", "Radargram"): numbers typed and shown in QGIS's locale (a decimal comma
always works), a row of widgets, a note, the "Time zero is" combo, and the rows of a
coordinate file (a text table with each listed trace's number, easting and northing).

The coordinate-file rows know the file only through two callables of their box: the trace
numbers the file's traces have, and the path of the section file (a coordinate file beside it
is stored by its name)."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Callable

from qgis.gui import QgsFileWidget
from qgis.PyQt.QtCore import QObject, pyqtSignal
from qgis.PyQt.QtWidgets import QComboBox, QHBoxLayout, QLabel, QLineEdit, QWidget

from ..core.numbers import fmt_count, fmt_trim, parse
from ..readers.texttable import TableOptions, guess_options, read_table, select_rows
from .table_widgets import TableOptionsBox

ZERO_ITEMS = (("On the ground line", "ground"), ("At a fixed height", "datum"),
              ("At a fixed height, corrected to the ground", "datum_ground"))
NO_SPACING = "Enter the trace spacing in metres."
NO_DATUM = "Enter the height of time zero."
NO_CRS = "Choose the CRS of the positions."
NO_TABLE = "Choose the coordinate file with the trace positions."
NO_COLUMNS = "Choose the trace number, easting and northing columns."
FEW_LISTED = "Fewer than two of the file's trace numbers are in the coordinate file."
LISTED = "{k} of {n} traces listed; the rest are placed between them."
ALL_LISTED = "All {n} traces listed."
#: column names guessed for a coordinate file (whole name, case ignored)
GUESS = {"number": r"cdp|trace|tr|shot|sp|fldr|nr|no|num|number|station|ffid|cmp",
         "easting": r"x|east|easting|e|rechts|rechtswert|lon|longitude|cdp_?x",
         "northing": r"y|north|northing|n|hoch|hochwert|lat|latitude|cdp_?y"}


def number(text: str) -> float | None:
    """The finite number typed (either decimal separator), else None."""
    try:
        v = parse(text)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def positive(text: str) -> float | None:
    v = number(text)
    return v if v is not None and v > 0 else None


def show(v: float, decimals: int = 6) -> str:
    return fmt_trim(v, decimals)


def row(*widgets, stretch: int | None = None) -> QWidget:
    """The widgets side by side; the one at ``stretch`` takes the room, else a stretch after."""
    out = QWidget()
    box = QHBoxLayout(out)
    box.setContentsMargins(0, 0, 0, 0)
    for i, w in enumerate(widgets):
        box.addWidget(w, 1 if i == stretch else 0)
    if stretch is None:
        box.addStretch(1)
    return out


def note(name: str) -> QLabel:
    label = QLabel()
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def line_edit(name: str, tip: str, edited: Callable) -> QLineEdit:
    """A number field that tells ``edited`` when the user finished typing."""
    e = QLineEdit()
    e.setObjectName(name)
    e.setToolTip(tip)
    e.editingFinished.connect(edited)
    return e


def zero_combo(name: str, values: tuple, changed: Callable) -> QComboBox:
    """"Time zero is": the ``ZERO_ITEMS`` whose value is in ``values``."""
    combo = QComboBox()
    combo.setObjectName(name)
    for text, value in ZERO_ITEMS:
        if value in values:
            combo.addItem(text, value)
    combo.setToolTip("Where the first sample's time zero lies on the section")
    combo.currentIndexChanged.connect(lambda *_a: changed())
    return combo


def split_rows(text: str) -> list[list[str]]:
    """Pasted lines split into cells: by tab, else semicolon, else comma, else blanks."""
    out = []
    for line in str(text).splitlines():
        if not line.strip():
            continue
        for sep in ("\t", ";", ","):
            if sep in line:
                out.append([c.strip() for c in line.split(sep)])
                break
        else:
            out.append(line.split())
    return out


def guess_column(names: list[str], role: str, taken=()) -> int | None:
    """The column whose name says ``role`` (number, easting, northing), or None."""
    pattern = re.compile(rf"(?i)^\s*(?:{GUESS[role]})\s*$")
    for i, name in enumerate(names):
        if i not in taken and pattern.match(name or ""):
            return i
    return None


class CoordinateFile(QObject):
    """The coordinate-file rows of a trace box: the file, its layout, the trace number /
    easting / northing columns and a note how many of the section's traces it lists.

    ``numbers()``: the trace numbers of the section's traces (None when unknown); ``path()``:
    the section file; ``busy()``: the box is filling its rows (a file set then is not "chosen").
    ``chosen`` follows a file the user picks; ``changed`` every other edit."""
    chosen = pyqtSignal()
    changed = pyqtSignal()

    def __init__(self, owner: QWidget, prefix: str, numbers: Callable, path: Callable,
                 busy: Callable):
        super().__init__(owner)
        self._numbers, self._path, self._busy_owner = numbers, path, busy
        self._busy = False
        self.names: list[str] = []
        self.error = ""
        self._listed = None                         # (key, listed count or what is wrong)
        self.file = QgsFileWidget()
        self.file.setObjectName(f"{prefix}_table_file")
        self.file.setFilter("Text tables (*.csv *.txt *.dat *.xyz);;All files (*)")
        self.file.setToolTip("A text table with each listed trace's number, easting and northing")
        self.file.fileChanged.connect(self._file_chosen)
        self.options_box = TableOptionsBox()
        self.options_box.setObjectName(f"{prefix}_table_options")
        self.options_box.changed.connect(self._layout_changed)
        self.number_combo, self.easting_combo, self.northing_combo = (
            self._combo(n) for n in ("number_combo", "easting_combo", "northing_combo"))
        self.note = note("table_note")
        self.columns_row = row(QLabel("Trace or CDP number"), self.number_combo, QLabel("Easting"),
                               self.easting_combo, QLabel("Northing"), self.northing_combo)

    def _combo(self, name: str) -> QComboBox:
        combo = QComboBox()
        combo.setObjectName(name)
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        combo.currentIndexChanged.connect(lambda *_a: self._edited())
        return combo

    def combos(self) -> dict[str, QComboBox]:
        return {"number": self.number_combo, "easting": self.easting_combo,
                "northing": self.northing_combo}

    def _edited(self) -> None:
        if not self._busy and not self._busy_owner():
            self.changed.emit()

    # -- in ------------------------------------------------------------------------------------
    def forget(self) -> None:
        """The section file changed: the listed count is worked out again."""
        self._listed = None

    def path_text(self) -> str:
        return self.file.filePath().strip()

    def set_file(self, path: str) -> None:
        """Use ``path`` as if the user chose it: its layout and columns guessed."""
        self.file.setFilePath(str(path))

    def _file_chosen(self, *_args) -> None:
        if self._busy_owner() or self._busy:
            return
        path = self.path_text()
        self._busy = True
        try:
            if path:
                try:
                    self.options_box.set_options(guess_options(path))
                except (OSError, ValueError):
                    pass                            # read_columns says what is wrong
            self.read_columns(keep=False)
        finally:
            self._busy = False
        self.chosen.emit()

    def _layout_changed(self) -> None:
        self._busy = True
        try:
            self.read_columns(keep=True)
        finally:
            self._busy = False
        self._edited()

    def set_options(self, o: dict) -> None:
        """A stored coordinate file (``positions_file``, relative to the section file),
        its layout and columns. Silent when the owner is busy."""
        path = Path(str(o["positions_file"]))
        if not path.is_absolute() and self._path():
            path = Path(self._path()).parent / path
        self.file.setFilePath(str(path))
        if o.get("positions_table"):
            try:
                self.options_box.set_options(TableOptions.from_dict(o["positions_table"]))
            except (TypeError, ValueError, AttributeError):
                pass
        self.read_columns(keep=False)
        columns = o.get("positions_columns") or {}
        for role, combo in self.combos().items():
            if columns.get(role) is not None:
                combo.setCurrentIndex(max(0, combo.findData(int(columns[role]))))

    def read_columns(self, keep: bool) -> None:
        """Fill the column combos from the coordinate file's names, guessed by name (``keep``:
        the choices stay when the names are the same)."""
        self.error, self._listed = "", None
        path = self.path_text()
        names: list[str] = []
        if path:
            try:
                table = read_table(path, self.options_box.options(), max_rows=200)
                names = [n for n in table.names]
            except (OSError, ValueError) as exc:
                self.error = f"{Path(path).name}: {exc}"
        same = keep and names == self.names
        self.names = names
        chosen = {role: c.currentData() for role, c in self.combos().items()}
        taken: list[int] = []
        for role, combo in self.combos().items():
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Choose…", None)
            for i, name in enumerate(names):
                combo.addItem(name or f"Column {i + 1}", i)
            pick = chosen[role] if same else guess_column(names, role, taken)
            if pick is not None:
                taken.append(pick)
            combo.setCurrentIndex(max(0, combo.findData(pick)))
            combo.blockSignals(False)

    # -- out -----------------------------------------------------------------------------------
    def options(self) -> dict:
        """``positions_file`` (by name when beside the section file), ``positions_table`` and
        ``positions_columns`` (when all three are chosen); {} without a file."""
        path = self.path_text()
        if not path:
            return {}
        o = {"positions_file": self._stored_path(path),
             "positions_table": self.options_box.options().to_dict()}
        columns = {role: combo.currentData() for role, combo in self.combos().items()}
        if all(v is not None for v in columns.values()):
            o["positions_columns"] = columns
        return o

    def _stored_path(self, path: str) -> str:
        p = Path(path)
        if self._path():
            try:
                if p.parent.resolve() == Path(self._path()).parent.resolve():
                    return p.name
            except OSError:
                pass
        return str(p)

    def problems(self) -> list[str]:
        if not self.path_text():
            return [NO_TABLE]
        if not self.names:
            return [self.error or NO_TABLE]
        if any(c.currentData() is None for c in self.combos().values()):
            return [NO_COLUMNS]
        listed = self.listed_count()
        if isinstance(listed, str):
            return [listed]
        return [FEW_LISTED] if listed is not None and listed < 2 else []

    def listed_count(self) -> int | str | None:
        """How many of the section's traces the coordinate file lists (or what is wrong)."""
        columns = {r: c.currentData() for r, c in self.combos().items()}
        path = self.path_text()
        key = (path, self.options_box.options(), tuple(columns.values()), self._path())
        if self._listed is not None and self._listed[0] == key:
            return self._listed[1]
        numbers = self._numbers()
        try:
            table = read_table(path, self.options_box.options())
            rows, _skipped, _first = select_rows(table, list(columns.values()))
            count = None if numbers is None else \
                len({float(v) for v in rows[:, 0]} & {float(v) for v in numbers})
        except (OSError, ValueError) as exc:
            count = f"{Path(path).name}: {exc}"
        self._listed = (key, count)
        return count

    def note_text(self, n_traces: int | None) -> str:
        """"12 of 30 traces listed; …" (or what is wrong with the file); "" before a file
        and its columns are chosen."""
        if not self.path_text() or not self.names or \
                any(c.currentData() is None for c in self.combos().values()):
            return self.error if self.path_text() else ""
        listed = self.listed_count()
        if not isinstance(listed, int) or n_traces is None:
            return listed if isinstance(listed, str) else ""
        return ALL_LISTED.format(n=fmt_count(n_traces)) if listed >= n_traces else \
            LISTED.format(k=fmt_count(listed), n=fmt_count(n_traces))
