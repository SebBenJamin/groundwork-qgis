"""Patterns…: give each class of a categorized borehole style a colour and an FGDC pattern in
one table, instead of opening every class's symbol in QGIS's editor.

The result is an ordinary QGIS renderer: each changed class becomes a fill symbol with a
simple fill (the colour) and, when a pattern is chosen, an SVG fill on top. Classes left alone
keep their symbol. Nothing is chosen automatically: every row starts with what the class has
now (its colour, and its pattern if it already uses a shipped one)."""
from __future__ import annotations

from qgis.core import Qgis, QgsFillSymbol, QgsSimpleFillSymbolLayer, QgsSVGFillSymbolLayer
from qgis.gui import QgsColorButton
from qgis.PyQt.QtCore import QSize, Qt
from qgis.PyQt.QtGui import QColor, QIcon
from qgis.PyQt.QtWidgets import (QComboBox, QCompleter, QDialog, QDialogButtonBox, QLabel,
                                 QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..patterns import Pattern, catalogue, pattern_for

PATTERN_MM = 8.0                      # width of one pattern tile on the column
PREVIEW_PX = 28                       # pattern preview in the list
NO_PATTERN = "(no pattern)"


def _svg_indices(symbol) -> list[int]:
    return [i for i in range(symbol.symbolLayerCount())
            if isinstance(symbol.symbolLayer(i), QgsSVGFillSymbolLayer)]


def _first_colour(symbol) -> QColor:
    for i in range(symbol.symbolLayerCount()):
        layer = symbol.symbolLayer(i)
        if not isinstance(layer, QgsSVGFillSymbolLayer):
            return QColor(layer.color())
    return QColor(symbol.color())


class PatternTable(QDialog):
    def __init__(self, renderer, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Patterns")
        self._renderer = renderer.clone()
        self._patterns = catalogue()
        self._by_label = {p.label: p for p in self._patterns}
        self._touched: set[str] = set()
        cats = self._renderer.categories()
        self._values = [str(c.value()) for c in cats]
        self.table = QTableWidget(len(cats), 3)
        self.table.setHorizontalHeaderLabels(["Class", "Colour", "Pattern"])
        self.table.verticalHeader().setVisible(False)
        self._colour_buttons: dict[str, QgsColorButton] = {}
        self._combos: dict[str, QComboBox] = {}
        for row, cat in enumerate(cats):
            value = str(cat.value())
            item = QTableWidgetItem(cat.label() or value)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.table.setItem(row, 0, item)
            button = QgsColorButton()
            button.setColor(_first_colour(cat.symbol()))
            button.colorChanged.connect(lambda _c, v=value: self._touched.add(v))
            self.table.setCellWidget(row, 1, button)
            self._colour_buttons[value] = button
            combo = self._pattern_combo()
            current = next((pattern_for(cat.symbol().symbolLayer(i).svgFilePath())
                            for i in _svg_indices(cat.symbol())), None)
            combo.setCurrentIndex(combo.findText(current.label) if current else 0)
            combo.currentIndexChanged.connect(lambda _i, v=value: self._touched.add(v))
            self.table.setCellWidget(row, 2, combo)
            self._combos[value] = combo
        self.table.verticalHeader().setDefaultSectionSize(PREVIEW_PX + 8)
        self.table.resizeColumnsToContents()
        self.table.setColumnWidth(2, 340)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                                   | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("A colour and an FGDC pattern per class. Type in a pattern box "
                                "to search, e.g. “sand” or “607”."))
        layout.addWidget(self.table)
        layout.addWidget(buttons)
        self.resize(620, 480)

    def _pattern_combo(self) -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        combo.setIconSize(QSize(PREVIEW_PX, PREVIEW_PX))
        combo.addItem(NO_PATTERN)
        for p in self._patterns:
            combo.addItem(QIcon(str(p.path)), p.label)
        completer = QCompleter([NO_PATTERN] + [p.label for p in self._patterns], combo)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        combo.setCompleter(completer)
        return combo

    # -- reading and setting rows --------------------------------------------------------------
    def values(self) -> list[str]:
        return list(self._values)

    def colour(self, value: str) -> QColor:
        return self._colour_buttons[value].color()

    def set_colour(self, value: str, colour: QColor) -> None:
        self._colour_buttons[value].setColor(colour)
        self._touched.add(value)

    def pattern(self, value: str) -> Pattern | None:
        return self._by_label.get(self._combos[value].currentText())

    def set_pattern(self, value: str, pattern: Pattern | None) -> None:
        combo = self._combos[value]
        combo.setCurrentIndex(combo.findText(pattern.label) if pattern else 0)
        self._touched.add(value)

    def search(self, text: str) -> list[Pattern]:
        needle = text.strip().lower()
        return [p for p in self._patterns if needle in p.label.lower()]

    # -- result --------------------------------------------------------------------------------
    def result(self):
        """A copy of the renderer with the changed classes' symbols rebuilt."""
        out = self._renderer.clone()
        for index, cat in enumerate(out.categories()):
            value = str(cat.value())
            if value not in self._touched:
                continue
            out.updateCategorySymbol(index, self._symbol(cat.symbol(), self.colour(value),
                                                         self.pattern(value)))
        return out

    @staticmethod
    def _symbol(old, colour: QColor, pattern: Pattern | None):
        return pattern_symbol(colour, pattern, old)


def pattern_symbol(colour: QColor, pattern: Pattern | None, old=None):
    """A fill symbol: ``old`` (or a new simple fill) without its SVG fills, its first fill in
    ``colour``, and ``pattern`` as an SVG fill on top."""
    sym = old.clone() if isinstance(old, QgsFillSymbol) else QgsFillSymbol.createSimple({})
    for i in reversed(_svg_indices(sym)):
        sym.deleteSymbolLayer(i)
    if sym.symbolLayerCount() == 0:
        sym.appendSymbolLayer(QgsSimpleFillSymbolLayer())
    sym.symbolLayer(0).setColor(colour)
    if pattern is not None:
        svg = QgsSVGFillSymbolLayer(str(pattern.path), PATTERN_MM, 0.0)
        svg.setPatternWidthUnit(Qgis.RenderUnit.Millimeters)
        sym.appendSymbolLayer(svg)
    return sym
