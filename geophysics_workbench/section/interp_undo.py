"""Undo/redo for interpretation edits: each command stores (feature, piece) before and after,
or, for regrouping, lists of features and pieces (``push_rows``).

``None`` for a piece means "no piece" (created or deleted); a feature in a state is saved when
the state is applied, which restores attributes and brings back a feature deleted with its
last piece.
"""
from __future__ import annotations

import copy

from qgis.PyQt.QtGui import QUndoCommand, QUndoStack


class _Command(QUndoCommand):
    """``apply(state, other)``; when it returns False the step did not happen, and the
    command is made obsolete, so the stack drops it instead of claiming the change."""

    def __init__(self, apply, text, before, after):
        super().__init__(text)
        self._apply, self.before, self.after = apply, before, after

    def redo(self):
        if self._apply(self.after, self.before) is False:
            self.setObsolete(True)

    def undo(self):
        if self._apply(self.before, self.after) is False:
            self.setObsolete(True)


class InterpUndo:
    def __init__(self, parent, apply, apply_rows=None):
        self.stack = QUndoStack(parent)
        self._apply = apply
        self._apply_rows = apply_rows

    def push(self, text: str, before: tuple, after: tuple) -> None:
        self.stack.push(_Command(self._apply, text, copy.deepcopy(before),
                                 copy.deepcopy(after)))

    def push_with(self, apply, text: str, before: tuple, after: tuple) -> None:
        """A command applied by ``apply(state, other)`` (e.g. field notes)."""
        self.stack.push(_Command(apply, text, copy.deepcopy(before), copy.deepcopy(after)))

    def push_rows(self, text: str, before: tuple, after: tuple) -> None:
        """Several rows at once: ``(features, pieces)`` before and after. Applying a state
        saves its rows and deletes the rows only the other state has."""
        self.stack.push(_Command(self._apply_rows, text, copy.deepcopy(before),
                                 copy.deepcopy(after)))

    def clear(self) -> None:
        self.stack.clear()
