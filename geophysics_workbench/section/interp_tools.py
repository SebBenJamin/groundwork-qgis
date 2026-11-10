"""Plot tools for drawing interpretation on the section canvas (see spikes/interp_tool).

Coordinates are the canvas's plot coordinates: distance = forward chainage (the dock sets the
profile curve forward), elevation in metres. The readout signal does not fire while a custom
tool is active, so the tools pass hovered plot points to ``on_hover``.
"""
from __future__ import annotations

from typing import Callable

from qgis.gui import QgsPlotTool
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QPointF, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QPainterPath, QPen
from qgis.PyQt.QtWidgets import QGraphicsPathItem, QGraphicsRectItem

SKETCH_RGB = (170, 0, 140)
from ..core.interpretation import MIN_VERTICES as MIN_POINTS  # noqa: E402


def plot_to_canvas(canvas, s: float, z: float) -> QPointF:
    """Canvas pixel of plot point (s, z), linear in the visible ranges, so points outside the
    view map outside the plot area (``plotPointToCanvasPoint`` returns (0, 0) for them)."""
    area = canvas.plotArea()
    d, e = canvas.visibleDistanceRange(), canvas.visibleElevationRange()
    dw, eh = d.upper() - d.lower(), e.upper() - e.lower()
    if area.width() <= 0 or area.height() <= 0 or dw <= 0 or eh <= 0:
        return QPointF(float("nan"), float("nan"))
    x = area.left() + (s - d.lower()) / dw * area.width()
    y = area.bottom() - (z - e.lower()) / eh * area.height()
    return QPointF(x, y)


def plot_tolerance(canvas, pos, mm: float = 3.0) -> tuple[float, float]:
    """(chainage, elevation) extent of ``mm`` millimetres on screen at canvas pixel ``pos``."""
    px = mm * canvas.logicalDpiX() / 25.4
    a = canvas.canvasPointToPlotPoint(QPointF(pos))
    b = canvas.canvasPointToPlotPoint(QPointF(pos) + QPointF(px, px))
    return (max(1e-9, abs(b.distance() - a.distance())),
            max(1e-9, abs(b.elevation() - a.elevation())))


class Panner:
    """Middle-button drag pans the canvas, whatever tool is active."""

    def __init__(self, canvas):
        self.canvas, self.last = canvas, None

    def press(self, event) -> bool:
        if event.button() == Qt.MouseButton.MiddleButton:
            self.last = QPointF(event.pos())
            event.accept()
            return True
        return False

    def move(self, event) -> bool:
        if self.last is None:
            return False
        pos = QPointF(event.pos())
        delta = pos - self.last
        self.canvas.panContentsBy(delta.x(), delta.y())
        self.last = pos
        event.accept()
        return True

    def release(self, event) -> bool:
        if self.last is None or event.button() != Qt.MouseButton.MiddleButton:
            return False
        self.last = None
        event.accept()
        return True


class SketchItem:
    """A path over the plot, in canvas coordinates rebuilt from plot points; redrawn after
    every zoom or pan."""

    def __init__(self, canvas):
        self.canvas = canvas
        self._last = None
        self.item = QGraphicsPathItem()
        pen = QPen(QColor(*SKETCH_RGB), 1.5, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)
        self.item.setPen(pen)
        self.item.setZValue(1001)
        canvas.scene().addItem(self.item)
        canvas.scaleChanged.connect(self._redraw)
        canvas.plotAreaChanged.connect(self._redraw)

    def _redraw(self, *_args) -> None:
        if self._last is not None and not sip.isdeleted(self.item):
            self.show(*self._last)

    def show(self, points, closed: bool = False, extra=None) -> None:
        self._last = (list(points), closed, extra)
        pts = list(points) + ([extra] if extra is not None else [])
        path = QPainterPath()
        for k, (s, z) in enumerate(pts):
            pt = plot_to_canvas(self.canvas, s, z)
            if pt.x() != pt.x():                # no plot area yet
                continue
            if k == 0:
                path.moveTo(pt)
                path.addEllipse(pt, 2, 2)
                path.moveTo(pt)
            else:
                path.lineTo(pt)
        if closed and len(pts) > 2:
            path.closeSubpath()
        self.item.setPath(path)

    def clear(self) -> None:
        self._last = None
        if not sip.isdeleted(self.item):
            self.item.setPath(QPainterPath())

    def remove(self) -> None:
        if self.item.scene() is not None:
            self.item.scene().removeItem(self.item)


class DrawTool(QgsPlotTool):
    """Click adds a vertex, double-click or Enter finishes, Backspace removes the last vertex,
    Esc clears the sketch (on an empty sketch: ``on_cancel``). A point finishes on its click."""

    def __init__(self, canvas, kind: str, on_finished: Callable[[list], None],
                 on_cancel: Callable[[], None] | None = None,
                 on_hover: Callable[[object], None] | None = None,
                 snap: Callable[[float, float, object], tuple] | None = None):
        super().__init__(canvas, f"interp-{kind}")
        # the canvas owns its tools: without this a late Python garbage collection deletes a
        # tool the canvas already deleted with itself (hard crash at teardown)
        sip.transferto(self, canvas)
        self.kind = kind
        self.on_finished, self.on_cancel, self.on_hover = on_finished, on_cancel, on_hover
        #: (s, z, canvas pos) -> snapped (s, z)
        self.snap = snap
        self.points: list[tuple[float, float]] = []
        self.sketch = SketchItem(canvas)
        self.panner = Panner(canvas)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def _plot(self, event):
        pp = self.canvas().canvasPointToPlotPoint(QPointF(event.pos()))
        if pp.isEmpty():
            return None, pp
        xy = (float(pp.distance()), float(pp.elevation()))
        if self.snap is not None:
            xy = self.snap(*xy, event.pos())
        return xy, pp

    def plotPressEvent(self, event):
        if event.button() == Qt.MouseButton.RightButton and self.kind != "point":
            event.accept()                      # as in QGIS: right-click finishes the shape
            self._finish()
            return
        if self.panner.press(event) or event.button() != Qt.MouseButton.LeftButton:
            return
        xy, _ = self._plot(event)
        if xy is None:
            return
        self.points.append(xy)
        event.accept()
        if self.kind == "point":
            self._finish()
        else:
            self.sketch.show(self.points, self.kind == "polygon")

    def plotReleaseEvent(self, event):
        self.panner.release(event)

    def plotMoveEvent(self, event):
        if self.panner.move(event):
            return
        xy, pp = self._plot(event)
        if self.on_hover is not None and xy is not None:
            self.on_hover(pp)
        if self.points and xy is not None:
            self.sketch.show(self.points, self.kind == "polygon", extra=xy)

    def plotDoubleClickEvent(self, event):
        event.accept()
        self._finish()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._finish()
        elif key == Qt.Key.Key_Backspace and self.points:
            self.points.pop()
            self.sketch.show(self.points, self.kind == "polygon")
        elif key == Qt.Key.Key_Escape:
            if self.points:
                self.reset()
            elif self.on_cancel is not None:
                self.on_cancel()
        else:
            return
        event.accept()

    def _finish(self) -> None:
        pts = _dedup(self.points)
        self.reset()
        if len(pts) >= MIN_POINTS[self.kind]:
            self.on_finished(pts)

    def reset(self) -> None:
        self.points = []
        self.sketch.clear()

    def deactivate(self):
        self.reset()
        super().deactivate()


def _dedup(points):
    out = []
    for p in points:
        if not out or out[-1] != p:
            out.append(p)
    return out


class EditTool(QgsPlotTool):
    """Select a piece (click), drag a vertex, click an edge to insert a vertex, drag inside a
    polygon (or Shift+drag a line) to move it, Delete removes the selected vertex or the
    piece, double-click edits the feature's attributes, right-click regroups (move the piece
    to another feature, merge features), Esc deselects (then leaves)."""

    TOLERANCE_MM = 3.0

    def __init__(self, canvas, ctl):
        super().__init__(canvas, "interp-edit")
        sip.transferto(self, canvas)
        self.ctl = ctl
        self.selected = None            # InterpPiece
        self.vertex = None              # selected vertex index
        self._drag = None               # ("vertex", index) | ("move", s0, z0)
        self._preview = None
        self.sketch = SketchItem(canvas)
        self.panner = Panner(canvas)

    # -- helpers ---------------------------------------------------------------------------
    def _plot(self, pos):
        pp = self.canvas().canvasPointToPlotPoint(QPointF(pos))
        return None if pp.isEmpty() else (float(pp.distance()), float(pp.elevation()))

    def _tolerance(self, pos):
        return plot_tolerance(self.canvas(), pos, self.TOLERANCE_MM)

    def _show(self, piece) -> None:
        if piece is None:
            self.sketch.clear()
        else:
            self.sketch.show(piece.vertices, piece.kind == "polygon")

    def select(self, piece, vertex=None) -> None:
        self.selected, self.vertex = piece, vertex
        self._show(piece)

    # -- events ----------------------------------------------------------------------------
    def menu_actions(self, piece) -> list:
        """(label, callable or submenu list) for the right-click menu on ``piece``."""
        from ..ui.interp_layers import entity_label
        ctl = self.ctl
        store = ctl.dock.provider.store
        # interpretation stays per profile: only features with a piece on this profile
        here = {p.feature_id for p in store.pieces(piece.version_id, piece.profile_id)}
        feats = store.features(piece.version_id)
        others = sorted((f for f in feats if f.id != piece.feature_id and f.id in here),
                        key=lambda f: (f.letter.lower(), f.type.lower()))

        def then_deselect(fn):
            return lambda: (fn(), self.select(None))

        move = [("New feature", then_deselect(lambda: ctl.move_piece_to(piece, None)))]
        move += [(entity_label(f), then_deselect(lambda f=f: ctl.move_piece_to(piece, f.id)))
                 for f in others]
        merge = [(entity_label(f),
                  then_deselect(lambda f=f: ctl.merge_features(piece.feature_id, f.id)))
                 for f in others]
        return [("Attributes…", lambda: ctl.edit_feature(piece.feature_id)),
                ("Move piece to", move),
                ("Merge this feature into", merge),
                ("Delete piece", lambda: self._delete_piece(piece))]

    def _delete_piece(self, piece) -> None:
        if self.ctl.confirm("Delete this interpretation piece?"):
            self.ctl.delete_piece(piece)
            self.select(None)

    def _context_menu(self, event, xy) -> None:
        from qgis.PyQt.QtWidgets import QMenu

        from .interp_edit import pick_piece
        hit = pick_piece(self.ctl.current_pieces(), *xy, *self._tolerance(event.pos()))
        if hit is None:
            return
        self.select(hit.piece)
        enabled = self.ctl.writable()

        def fill(menu, actions):
            for label, target in actions:
                if isinstance(target, list):
                    sub = menu.addMenu(label)
                    sub.setEnabled(enabled and bool(target))
                    fill(sub, target)
                else:
                    act = menu.addAction(label)
                    act.setEnabled(enabled)
                    act.triggered.connect(lambda _=False, fn=target: fn())

        menu = QMenu(self.canvas())
        fill(menu, self.menu_actions(hit.piece))
        menu.exec(self.canvas().mapToGlobal(event.pos()))

    def plotPressEvent(self, event):
        from .interp_edit import insert_vertex, pick_piece
        if self.panner.press(event):
            return
        if event.button() == Qt.MouseButton.RightButton:
            xy = self._plot(event.pos())
            if xy is not None:
                event.accept()
                self._context_menu(event, xy)
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        xy = self._plot(event.pos())
        if xy is None:
            return
        event.accept()
        pieces = self.ctl.current_pieces()
        if self.selected is not None:
            pieces = [p for p in pieces if p.id == self.selected.id] + \
                     [p for p in pieces if p.id != self.selected.id]
        hit = pick_piece(pieces, *xy, *self._tolerance(event.pos()))
        if hit is None:
            self.select(None)
            return
        if self.selected is None or hit.piece.id != self.selected.id:
            self.select(hit.piece)
            return
        shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if hit.vertex is not None:
            self.vertex = hit.vertex
            self._drag = ("vertex", hit.vertex)
        elif hit.edge is not None and not shift:
            self._preview = insert_vertex(hit.piece, hit.edge, *xy)
            self.vertex = hit.edge + 1
            self._drag = ("vertex", hit.edge + 1)
        elif hit.interior or shift:
            self._drag = ("move", xy[0], xy[1])
        self._base = self._preview or hit.piece

    def plotMoveEvent(self, event):
        from .interp_edit import move_piece, move_vertex
        if self.panner.move(event):
            return
        xy = self._plot(event.pos())
        if xy is None:
            return
        pp = self.canvas().canvasPointToPlotPoint(QPointF(event.pos()))
        self.ctl.hover(pp)
        if self._drag is None:
            return
        if self._drag[0] == "vertex":
            xy = self.ctl.snap(*xy, *self._tolerance(event.pos()), exclude=self._base.id)
            self._preview = move_vertex(self._base, self._drag[1], *xy)
        else:
            self._preview = move_piece(self._base, xy[0] - self._drag[1], xy[1] - self._drag[2])
        self._show(self._preview)

    def plotReleaseEvent(self, event):
        if self.panner.release(event) or self._drag is None:
            return
        self._drag = None
        new, self._preview = self._preview, None
        if new is not None and self.selected is not None:
            saved = self.ctl.replace_piece(self.selected, new)
            self.select(saved, self.vertex)

    def plotDoubleClickEvent(self, event):
        event.accept()
        if self.selected is not None:
            self.ctl.edit_feature(self.selected.feature_id)

    def keyPressEvent(self, event):
        from .interp_edit import delete_vertex
        key = event.key()
        if key == Qt.Key.Key_Delete and self.selected is not None:
            piece = self.selected
            if self.vertex is not None:
                rest = delete_vertex(piece, self.vertex)
                if rest is not None:
                    self.select(self.ctl.replace_piece(piece, rest))
                    event.accept()
                    return
            self._delete_piece(piece)
        elif key == Qt.Key.Key_Escape:
            if self.selected is not None:
                self.select(None)
            else:
                self.ctl.stop()
        else:
            return
        event.accept()

    def deactivate(self):
        self.select(None)
        super().deactivate()


class NoteTool(QgsPlotTool):
    """Field notes: a click gives a note at one chainage, a drag along the section a stretch;
    ``on_finished(s_from, s_to)`` (``s_to`` None for a click). Middle-drag pans."""

    DRAG_PX = 4

    def __init__(self, canvas, on_finished: Callable[[float, float | None], None],
                 on_cancel: Callable[[], None] | None = None):
        super().__init__(canvas, "field-note")
        sip.transferto(self, canvas)            # the canvas owns its tools (see DrawTool)
        self.on_finished, self.on_cancel = on_finished, on_cancel
        self.panner = Panner(canvas)
        self._start = None                      # (canvas x, chainage) of the press
        self.setCursor(Qt.CursorShape.CrossCursor)
        # the stretch being dragged, shown before release (field-note colour, translucent)
        from .field_notes_render import NOTE_RGB
        self.preview = QGraphicsRectItem()
        self.preview.setPen(QPen(Qt.PenStyle.NoPen))
        self.preview.setBrush(QBrush(QColor(*NOTE_RGB, 60)))
        self.preview.setZValue(1000)
        self.preview.hide()
        self.preview_range = None

    def activate(self):
        if self.preview.scene() is None:
            self.canvas().scene().addItem(self.preview)
        super().activate()

    def _show_preview(self, x0: float, x1: float, s0: float, s1: float) -> None:
        top, height = 0.0, float(self.canvas().viewport().height())
        self.preview.setRect(min(x0, x1), top, abs(x1 - x0), height)
        self.preview.show()
        self.preview_range = (min(s0, s1), max(s0, s1))

    def _hide_preview(self) -> None:
        self.preview.hide()
        self.preview_range = None

    def deactivate(self):
        self._hide_preview()
        if self.preview.scene() is not None:
            self.preview.scene().removeItem(self.preview)
        super().deactivate()

    def _s(self, event):
        pp = self.canvas().canvasPointToPlotPoint(QPointF(event.pos()))
        return None if pp.isEmpty() else float(pp.distance())

    def plotPressEvent(self, event):
        if self.panner.press(event) or event.button() != Qt.MouseButton.LeftButton:
            return
        s = self._s(event)
        if s is not None:
            self._start = (float(event.pos().x()), s)
            event.accept()

    def plotMoveEvent(self, event):
        if self.panner.move(event) or self._start is None:
            return
        x0, s0 = self._start
        x1, s1 = float(event.pos().x()), self._s(event)
        if s1 is not None and abs(x1 - x0) >= self.DRAG_PX:
            self._show_preview(x0, x1, s0, s1)

    def plotReleaseEvent(self, event):
        self._hide_preview()
        if self.panner.release(event) or self._start is None:
            return
        x0, s0 = self._start
        self._start = None
        s1 = self._s(event)
        if s1 is None or abs(float(event.pos().x()) - x0) < self.DRAG_PX:
            self.on_finished(s0, None)
        else:
            self.on_finished(min(s0, s1), max(s0, s1))
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.on_cancel is not None:
            self.on_cancel()
            event.accept()
