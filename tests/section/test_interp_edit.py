"""Editing interpretation: picking, vertex edits, moving, deleting, undo/redo."""
import pytest

from groundwork_geophysics.core.interpretation import (InterpFeature, InterpPiece, new_id,
                                                      normalise)
from groundwork_geophysics.section.interp_edit import (delete_vertex, insert_vertex, move_piece,
                                                      move_vertex, pick_piece)

SQUARE = normalise(InterpPiece("sq", "v", "f", "p", "polygon",
                               [(0, 0), (10, 0), (10, -10), (0, -10)]))
LINE = InterpPiece("ln", "v", "f2", "p", "line", [(20, 0), (30, -5), (40, 0)])


def test_pick_prefers_vertex_over_edge():
    hit = pick_piece([SQUARE, LINE], 10.2, -0.2, 1.0, 1.0)
    assert hit.piece.id == "sq" and hit.vertex is not None and hit.edge is None
    assert SQUARE.vertices[hit.vertex] == (10.0, 0.0)
    edge = pick_piece([SQUARE, LINE], 5.0, 0.3, 1.0, 1.0)
    assert edge.piece.id == "sq" and edge.vertex is None and edge.edge is not None
    inside = pick_piece([SQUARE, LINE], 5.0, -5.0, 1.0, 1.0)
    assert inside.piece.id == "sq" and inside.interior
    assert pick_piece([SQUARE, LINE], 50.0, 20.0, 1.0, 1.0) is None


def test_vertex_operations_keep_valid_pieces():
    moved = move_vertex(LINE, 1, 30.0, -8.0)
    assert moved.vertices[1] == (30.0, -8.0) and LINE.vertices[1] == (30.0, -5.0)
    ins = insert_vertex(SQUARE, 0, 5.0, 0.0)
    assert (5.0, 0.0) in ins.vertices and len(ins.vertices) == len(SQUARE.vertices) + 1
    sq0 = move_vertex(SQUARE, 0, -1.0, -1.0)                 # first vertex of a closed ring
    assert sq0.vertices[0] == sq0.vertices[-1]
    assert delete_vertex(LINE, 1).vertices == [(20.0, 0.0), (40.0, 0.0)]
    assert delete_vertex(delete_vertex(LINE, 1), 0) is None   # too few: caller deletes piece
    shifted = move_piece(LINE, 1.0, -2.0)
    assert shifted.vertices[0] == (21.0, -2.0)


@pytest.fixture
def ctl(qgis_app, store_with_model, make_dock):
    from qgis.PyQt.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    store = store_with_model[0]
    dock = make_dock(store)
    dock.open_profile(store.profiles()[0].id)
    store.ensure_interpretation()
    v = store.current_version()
    f = InterpFeature(new_id(), v.id, type="anomaly", name="A")
    store.save_feature(f)
    p = InterpPiece(new_id(), v.id, f.id, dock.current_profile_id(), "line",
                    [(2.0, 0.0), (6.0, -1.0), (10.0, 0.0)])
    store.save_piece(p)
    yield dock.interp, store, p
    from qgis.core import QgsProject
    QgsProject.instance().removeAllMapLayers()


def test_move_vertex_saves_and_undo_restores(ctl):
    c, store, p = ctl
    c.replace_piece(p, move_vertex(p, 1, 6.0, -3.0))
    assert store.pieces(p.version_id)[0].vertices[1] == (6.0, -3.0)
    c.undo.stack.undo()
    assert store.pieces(p.version_id)[0].vertices[1] == (6.0, -1.0)
    c.undo.stack.redo()
    assert store.pieces(p.version_id)[0].vertices[1] == (6.0, -3.0)


def test_insert_vertex_on_edge(ctl):
    c, store, p = ctl
    c.replace_piece(p, insert_vertex(p, 0, 4.0, -0.5))
    assert (4.0, -0.5) in store.pieces(p.version_id)[0].vertices


def test_delete_piece_then_undo_brings_it_back(ctl):
    c, store, p = ctl
    c.delete_piece(p)
    vid = p.version_id
    assert store.pieces(vid) == [] and store.features(vid) == []
    c.undo.stack.undo()
    [back] = store.pieces(vid)
    [feat] = store.features(vid)
    assert back.id == p.id and back.vertices == p.vertices
    assert (feat.id, feat.name, feat.type) == (p.feature_id, "A", "anomaly")


def test_edit_attributes_with_undo(ctl):
    c, store, p = ctl
    [f] = store.features(p.version_id)
    c.form_factory = lambda feature, s, letters, existing=(): InterpFeature(
        feature.id, feature.version_id, type="fault", name="F", author=feature.author)
    c.edit_feature(f.id)
    assert store.features(p.version_id)[0].name == "F"
    c.undo.stack.undo()
    assert store.features(p.version_id)[0].name == "A"


def test_edit_disabled_on_frozen_version(ctl):
    c, store, p = ctl
    frozen = store.freeze_current("R1")
    c.dock.provider.interp_version_id = frozen.id
    c.start("edit")
    assert c.tool is None and c.buttons["pan"].isChecked()
    c.start("polygon")
    assert c.tool is None
    [fp] = store.pieces(frozen.id)
    with pytest.raises(PermissionError):
        c.delete_piece(fp)


def test_edit_tool_drags_a_vertex(ctl, qgis_app):
    from qgis.core import QgsProfilePoint
    from qgis.PyQt.QtCore import QEvent, QPoint, QPointF, Qt
    from qgis.PyQt.QtGui import QMouseEvent

    import time
    c, store, p = ctl
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:          # let the first fit and generation finish
        qgis_app.processEvents()
        if not c.dock.is_busy():
            break
        time.sleep(0.02)
    c.dock.fit.user_navigated()                 # the view stays put while we map pixels
    c.dock.canvas.setVisiblePlotRange(0.0, 12.0, -5.0, 3.0)
    for _ in range(20):
        qgis_app.processEvents()
    canvas = c.dock.canvas
    vp = canvas.viewport()

    def send(et, pt, buttons=Qt.MouseButton.LeftButton):
        x, y = round(pt.x()), round(pt.y())
        qgis_app.sendEvent(vp, QMouseEvent(et, QPointF(x, y), QPointF(vp.mapToGlobal(QPoint(x, y))),
                                           Qt.MouseButton.LeftButton, buttons,
                                           Qt.KeyboardModifier.NoModifier))

    c.start("edit")
    v = canvas.plotPointToCanvasPoint(QgsProfilePoint(6.0, -1.0))
    target = canvas.plotPointToCanvasPoint(QgsProfilePoint(6.0, -2.0))
    for et in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease):   # select
        send(et, v)
    assert c.tool.selected is not None, ("select", v.x(), v.y(), canvas.visibleDistanceRange()
                                         if hasattr(canvas, "visibleDistanceRange") else "")
    send(QEvent.Type.MouseButtonPress, v)                                      # grab vertex
    assert c.tool._drag is not None, "grab"
    send(QEvent.Type.MouseMove, target)
    send(QEvent.Type.MouseButtonRelease, target, Qt.MouseButton.NoButton)
    s, z = store.pieces(p.version_id)[0].vertices[1]
    assert s == pytest.approx(6.0, abs=0.5) and z == pytest.approx(-2.0, abs=0.3)
    c.stop()
