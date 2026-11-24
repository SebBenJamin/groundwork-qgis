"""Profile ties panel: every crossing (or near miss) of two profiles, how far their
topmost visible models differ there, and a plot of both columns. The mismatch is an
indication for comparing by eye, not a pass/fail."""
from __future__ import annotations

import re
from dataclasses import dataclass

from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (QAbstractItemView, QDockWidget, QHeaderView, QLabel,
                                 QPushButton, QSplitter, QTableWidget, QTableWidgetItem,
                                 QVBoxLayout, QWidget)

from ..core.ties import TieColumn, TieMismatch, mismatch_text, shown_column, tie_mismatch
from ..section.data import NO_HEIGHTS, SectionDataProvider
from .ties_plot import TiesPlot

NOTE = ("2D profiles in different directions are not expected to match exactly; "
        "the figure is an indication.")
NO_MODEL = "no model at tie"
HEADERS = ("Profiles", "At", "Distance", "Compared", "Mismatch")
REFRESH_MS = 300
SORT_ROLE = Qt.ItemDataRole.UserRole + 1


@dataclass
class TieRow:
    a_id: str
    b_id: str
    a_name: str
    b_name: str
    s_a: float
    s_b: float
    distance: float
    col_a: TieColumn | None         # topmost visible model of A at the tie
    col_b: TieColumn | None
    mismatch: TieMismatch | None
    text: str                       # mismatch column

    @property
    def key(self) -> tuple:
        return (self.a_id, self.b_id, round(self.s_a, 1), round(self.s_b, 1))

    @property
    def crossing(self) -> bool:
        return self.distance < 1e-6

    @property
    def title(self) -> str:
        kind = "crossing" if self.crossing else f"{self.distance:.0f} m near miss"
        return f"{self.a_name} × {self.b_name} ({kind})"


def _natural(name: str) -> list:
    return [(0, int(t)) if t.isdigit() else (1, t.lower()) for t in re.split(r"(\d+)", name) if t]


class SortItem(QTableWidgetItem):
    """Table cell that sorts by a key kept in ``SORT_ROLE`` instead of by its text."""

    def __lt__(self, other):
        a, b = self.data(SORT_ROLE), other.data(SORT_ROLE)
        if a is None or b is None:
            return super().__lt__(other)
        return a < b


def _mismatch(a: TieColumn | None, b: TieColumn | None) -> tuple[TieMismatch | None, str]:
    if a is None or b is None:
        return None, NO_MODEL
    if a.quantity != b.quantity:
        return None, "different quantities"
    m = tie_mismatch(a, b)
    return m, mismatch_text(m)


def build_rows(provider: SectionDataProvider) -> list[TieRow]:
    """One row per unordered profile pair and tie. A's column comes from the tie in B's
    list closest to the same point (s on A, s_other on B)."""
    profiles = sorted(provider.store.profiles(), key=lambda p: _natural(p.name))
    rows = []
    for i, a in enumerate(profiles):
        ties_a = provider.ties(a.id)
        for b in profiles[i + 1:]:
            mine = [t for t in ties_a if t.other_id == b.id]
            theirs = [t for t in provider.ties(b.id) if t.other_id == a.id]
            for t in mine:
                back = min(theirs, default=None,
                           key=lambda u: (u.s_other - t.s) ** 2 + (u.s - t.s_other) ** 2)
                col_a = shown_column(back) if back is not None else None
                col_b = shown_column(t)
                m, text = _mismatch(col_a, col_b)
                rows.append(TieRow(a.id, b.id, a.name, b.name, t.s, t.s_other, t.distance,
                                   col_a, col_b, m, text))
    return rows


def held_back(provider: SectionDataProvider) -> list[str]:
    """``NO_HEIGHTS`` for each profile without heights that meets another profile (where it
    would have had a row): it is not compared until it has a reference height."""
    from ..core.context import profile_ties
    profiles = sorted(provider.store.profiles(), key=lambda p: _natural(p.name))
    out = []
    for p in profiles:
        if not any(profile_ties(p.xy, o.xy, provider.near_miss)
                   for o in profiles if o.id != p.id):
            continue
        if provider.is_local(p.id):
            out.append(NO_HEIGHTS.format(name=p.name or p.id))
    return out


class TiesPanel(QDockWidget):
    def __init__(self, provider: SectionDataProvider, dock, parent=None):
        super().__init__("Profile ties", parent)
        self.setObjectName("GeophysicsWorkbenchTiesPanel")
        self.provider = provider
        self.section_dock = dock
        self.rows: list[TieRow] = []

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setObjectName("ties_table")
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSortIndicator(0, Qt.SortOrder.AscendingOrder)
        self.table.setSortingEnabled(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.note = QLabel(NOTE)
        self.note.setWordWrap(True)
        #: profiles left out because they have no heights yet, one sentence each
        self.held_back = QLabel()
        self.held_back.setWordWrap(True)
        self.held_back.hide()
        self.show_button = QPushButton("Show in section")
        self.show_button.setObjectName("ties_show")
        self.show_button.setEnabled(False)
        self.show_button.clicked.connect(self.show_in_section)
        self.plot = TiesPlot()
        self.plot.setObjectName("ties_plot")

        top = QWidget()
        lay = QVBoxLayout(top)
        lay.setContentsMargins(0, 0, 0, 0)
        for w in (self.table, self.held_back, self.note, self.show_button):
            lay.addWidget(w)
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(top)
        split.addWidget(self.plot)
        split.setSizes([220, 380])
        self.setWidget(split)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self.refresh)
        provider.on_change.append(self._schedule)
        self.refresh()

    def detach(self) -> None:
        """Stop following the provider (called before the panel is deleted)."""
        self._timer.stop()
        try:
            self.provider.on_change.remove(self._schedule)
        except ValueError:
            pass

    def _schedule(self) -> None:
        self._timer.start()

    def refresh(self) -> None:
        """Rebuild the table from the provider, keeping the selected tie when it still exists."""
        self._timer.stop()
        keep = self.selected_row()
        keep_key = None if keep is None else keep.key
        self.rows = build_rows(self.provider)
        left_out = held_back(self.provider)
        self.held_back.setText("\n".join(left_out))
        self.held_back.setVisible(bool(left_out))
        t = self.table
        t.blockSignals(True)
        t.setSortingEnabled(False)
        t.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            kind = "crossing" if row.crossing else f"{row.distance:.0f} m (near miss)"
            compared = " · ".join(c.dataset_name if c else "–" for c in (row.col_a, row.col_b))
            cells = (f"{row.a_name} × {row.b_name}",
                     f"{row.a_name} {row.s_a:.0f} m · {row.b_name} {row.s_b:.0f} m",
                     kind, compared, row.text)
            m = row.mismatch
            figure = None if m is None else (m.factor if m.factor is not None else m.rel_diff)
            keys = (_natural(f"{row.a_name} {row.b_name}"),
                    (_natural(row.a_name), row.s_a, row.s_b), row.distance,
                    compared.lower(), (figure is None, figure or 0.0, row.text))
            for c, text in enumerate(cells):
                item = SortItem(text)
                item.setData(SORT_ROLE, keys[c])
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, row.key)
                t.setItem(r, c, item)
        t.setSortingEnabled(True)
        t.clearSelection()
        t.blockSignals(False)
        if keep_key is not None:
            for r in range(t.rowCount()):
                if t.item(r, 0).data(Qt.ItemDataRole.UserRole) == keep_key:
                    t.selectRow(r)
                    break
        self._selection_changed()

    def selected_row(self) -> TieRow | None:
        selected = self.table.selectionModel().selectedRows()
        if not selected:
            return None
        key = self.table.item(selected[0].row(), 0).data(Qt.ItemDataRole.UserRole)
        return next((row for row in self.rows if row.key == key), None)

    def _selection_changed(self) -> None:
        row = self.selected_row()
        self.show_button.setEnabled(row is not None)
        self.plot.show_row(row)

    def show_in_section(self) -> None:
        row = self.selected_row()
        if row is None:
            return
        self.section_dock.show()                # a hidden or closed section panel comes back
        self.section_dock.raise_()
        self.section_dock.open_profile(row.a_id)
        self.section_dock.show_cursor(row.s_a)
