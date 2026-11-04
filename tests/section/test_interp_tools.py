"""Drawing interpretation on the section: tools, form, saving."""
import pytest
from qgis.PyQt.QtCore import QEvent, QPoint, QPointF, Qt


def _click(app, canvas, x, y, double=False):
    from qgis.PyQt.QtGui import QMouseEvent
    vp = canvas.viewport()
    pos, glob = QPointF(x, y), QPointF(vp.mapToGlobal(QPoint(x, y)))
    kinds = ((QEvent.Type.MouseButtonDblClick,) if double else
             (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease))
    for et in kinds:
        app.sendEvent(vp, QMouseEvent(et, pos, glob, Qt.MouseButton.LeftButton,
                                      Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))


def _key(app, canvas, key):
    from qgis.PyQt.QtGui import QKeyEvent
    app.sendEvent(canvas, QKeyEvent(QEvent.Type.KeyPress, key, Qt.KeyboardModifier.NoModifier))


@pytest.fixture
def dock(qgis_app, store_with_model, make_dock):
    from qgis.PyQt.QtCore import QCoreApplication
    # docks of earlier tests are only deleteLater()-ed; their canvases still follow
    # QgsProject.instance() until the deferred deletes run
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qgis_app.processEvents()
    store = store_with_model[0]
    d = make_dock(store)
    d.open_profile(store.profiles()[0].id)
    for _ in range(50):
        qgis_app.processEvents()
        if not d.is_busy():
            break
    return d


def test_draw_tool_collects_and_finishes(qgis_app, dock):
    from geophysics_workbench.section.interp_tools import DrawTool

    got = []
    tool = DrawTool(dock.canvas, "line", got.append)
    dock.canvas.setTool(tool)
    _click(qgis_app, dock.canvas, 300, 200)
    _click(qgis_app, dock.canvas, 500, 240)
    _click(qgis_app, dock.canvas, 500, 240, double=True)
    assert len(got) == 1 and len(got[0]) >= 2
    pp = dock.canvas.canvasPointToPlotPoint(QPointF(300, 200))
    assert got[0][0] == pytest.approx((pp.distance(), pp.elevation()))
    dock.canvas.setTool(dock._pan_tool)


def test_backspace_and_escape(qgis_app, dock):
    from geophysics_workbench.section.interp_tools import DrawTool

    got, cancelled = [], []
    tool = DrawTool(dock.canvas, "polygon", got.append, on_cancel=lambda: cancelled.append(1))
    dock.canvas.setTool(tool)
    for x in (300, 400, 500):
        _click(qgis_app, dock.canvas, x, 220)
    _key(qgis_app, dock.canvas, Qt.Key.Key_Backspace)
    assert len(tool.points) == 2
    _key(qgis_app, dock.canvas, Qt.Key.Key_Escape)               # clears the sketch
    assert tool.points == [] and not cancelled
    _key(qgis_app, dock.canvas, Qt.Key.Key_Escape)               # empty sketch: leave the tool
    assert cancelled == [1] and got == []
    dock.canvas.setTool(dock._pan_tool)


def test_tool_stores_true_chainage_when_mirrored(qgis_app, store_with_model):
    """Pieces are stored in forward chainage; a reversed snapshot mirrors them like the rest."""
    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id
    from geophysics_workbench.section.data import SectionDataProvider

    store = store_with_model[0]
    prof = store.profiles()[0]
    store.ensure_interpretation()
    v = store.current_version()
    f = InterpFeature(new_id(), v.id)
    store.save_feature(f)
    store.save_piece(InterpPiece(new_id(), v.id, f.id, prof.id, "point", [(10.0, 1.0)]))
    prov = SectionDataProvider(store)
    assert prov.snapshot(prof.id).interpretation[0].vertices == [(10.0, 1.0)]
    length = prof.chainage.length
    assert prov.snapshot(prof.id, reverse=True).interpretation[0].vertices == [
        (pytest.approx(length - 10.0), 1.0)]


def test_finished_polygon_saved_and_shown(qgis_app, dock):
    from geophysics_workbench.core.interpretation import InterpFeature

    ctl = dock.interp
    ctl.form_factory = lambda feature, suggestions, letters: InterpFeature(
        feature.id, feature.version_id, type="anomaly", letter="A")
    ctl.start("polygon")
    for x, y in ((300, 230), (450, 230), (450, 300), (300, 300)):
        _click(qgis_app, dock.canvas, x, y)
    _click(qgis_app, dock.canvas, 300, 300, double=True)
    store = dock.provider.store
    [piece] = store.pieces(store.current_version().id)
    assert piece.kind == "polygon" and piece.profile_id == dock.current_profile_id()
    [feat] = store.features(store.current_version().id)
    assert feat.letter == "A" and feat.author != ""
    snap = dock.provider.snapshot(dock.current_profile_id())
    assert len(snap.interpretation) == 1
    from qgis.core import QgsProject
    QgsProject.instance().removeAllMapLayers()


def test_cancelled_form_discards_piece(qgis_app, dock):
    ctl = dock.interp
    ctl.form_factory = lambda feature, suggestions, letters: None
    ctl.start("point")
    _click(qgis_app, dock.canvas, 400, 250)
    store = dock.provider.store
    assert not store.has_interpretation() or store.pieces(store.current_version().id) == []
