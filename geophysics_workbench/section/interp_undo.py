"""Undo/redo for interpretation edits: each command stores (feature, piece) before and after.

``None`` for a piece means "no piece" (created or deleted); a feature in a state is saved when
the state is applied, which restores attributes and brings back a feature deleted with its
last piece.
"""
from __future__ import annotations

import copy

from qgis.PyQt.QtGui import QUndoCommand, QUndoStack


class _Command(QUndoCommand):
    def __init__(self, apply, text, before, after):
        super().__init__(text)
        self._apply, self.before, self.after = apply, before, after

    def redo(self):
        self._apply(self.after, self.before)

    def undo(self):
        self._apply(self.before, self.after)


class InterpUndo:
    def __init__(self, parent, apply):
        self.stack = QUndoStack(parent)
        self._apply = apply

    def push(self, text: str, before: tuple, after: tuple) -> None:
        self.stack.push(_Command(self._apply, text, copy.deepcopy(before),
                                 copy.deepcopy(after)))

    def clear(self) -> None:
        self.stack.clear()
