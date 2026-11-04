"""Drawing interpretation on the section: tools, form, saving."""
import numpy as np
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
    ctl.form_factory = lambda feature, suggestions, letters, existing=(): InterpFeature(
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


def test_finished_piece_joins_existing_feature(qgis_app, dock):
    from geophysics_workbench.core.interpretation import InterpFeature, new_id

    ctl = dock.interp
    store = dock.provider.store
    store.ensure_interpretation()
    v = store.current_version().id
    a = InterpFeature(new_id(), v, type="anomaly", letter="A")
    store.save_feature(a)
    seen = []
    ctl.form_factory = lambda f, s, letters, existing: (seen.append(existing), existing[0])[1]
    ctl._finished("line", [(1.0, 90.0), (5.0, 89.0)])
    ctl._finished("line", [(10.0, 90.0), (15.0, 89.0)])
    assert [f.id for f in seen[0]] == [a.id]
    assert [f.id for f in store.features(v)] == [a.id]
    assert {p.feature_id for p in store.pieces(v)} == {a.id} and len(store.pieces(v)) == 2
    from qgis.core import QgsProject
    QgsProject.instance().removeAllMapLayers()


def test_cancelled_form_discards_piece(qgis_app, dock):
    ctl = dock.interp
    ctl.form_factory = lambda feature, suggestions, letters, existing=(): None
    ctl.start("point")
    _click(qgis_app, dock.canvas, 400, 250)
    store = dock.provider.store
    assert not store.has_interpretation() or store.pieces(store.current_version().id) == []


def test_sketch_mapping_outside_view_is_not_origin(qgis_app, dock):
    from geophysics_workbench.section.interp_tools import plot_to_canvas
    dock.canvas.setVisiblePlotRange(0.0, 10.0, -5.0, 5.0)
    qgis_app.processEvents()
    from qgis.core import QgsProfilePoint
    upper = dock.canvas.visibleDistanceRange().upper()      # locked axis scales widen ranges
    inside = plot_to_canvas(dock.canvas, 5.0, 0.0)
    ref = dock.canvas.plotPointToCanvasPoint(QgsProfilePoint(5.0, 0.0))
    assert abs(inside.x() - ref.x()) < 1 and abs(inside.y() - ref.y()) < 1
    outside = plot_to_canvas(dock.canvas, upper + 20.0, 0.0)
    area = dock.canvas.plotArea()
    assert area.contains(inside)
    assert outside.x() > area.right() and abs(outside.y() - inside.y()) < 1


def test_middle_drag_pans_while_drawing(qgis_app, dock):
    from qgis.PyQt.QtGui import QMouseEvent
    from geophysics_workbench.section.interp_tools import DrawTool
    dock.fit.user_navigated()
    dock.canvas.setVisiblePlotRange(0.0, 10.0, -5.0, 5.0)
    qgis_app.processEvents()
    tool = DrawTool(dock.canvas, "line", lambda pts: None)
    dock.canvas.setTool(tool)
    _click(qgis_app, dock.canvas, 300, 200)                       # a sketch in progress
    vp = dock.canvas.viewport()
    before = dock.canvas.visibleDistanceRange().lower()
    for et, x, buttons in ((QEvent.Type.MouseButtonPress, 400, Qt.MouseButton.MiddleButton),
                           (QEvent.Type.MouseMove, 300, Qt.MouseButton.MiddleButton),
                           (QEvent.Type.MouseButtonRelease, 300, Qt.MouseButton.NoButton)):
        vp_pos = QPointF(x, 220)
        qgis_app.sendEvent(vp, QMouseEvent(et, vp_pos, QPointF(vp.mapToGlobal(QPoint(x, 220))),
                                           Qt.MouseButton.MiddleButton, buttons,
                                           Qt.KeyboardModifier.NoModifier))
    assert dock.canvas.visibleDistanceRange().lower() > before   # dragged left: view moves right
    assert len(tool.points) == 1                                 # the sketch survived
    dock.canvas.setTool(dock._pan_tool)


def test_drawn_vertices_above_ground_snap_to_it(qgis_app, dock):
    from geophysics_workbench.core.interpretation import InterpFeature
    ctl = dock.interp
    ctl.form_factory = lambda feature, s, l, existing=(): InterpFeature(feature.id, feature.version_id)
    surface = ctl.surface()
    assert surface is not None
    s_mid = float(surface[0][len(surface[0]) // 2])
    ground = float(np.interp(s_mid, *surface))
    ctl._finished("line", [(s_mid, ground + 50.0), (s_mid + 2.0, ground - 3.0)])
    store = dock.provider.store
    [p] = store.pieces(store.current_version().id)
    assert p.vertices[0][1] == pytest.approx(ground)
    from qgis.core import QgsProject
    QgsProject.instance().removeAllMapLayers()


def test_click_shows_borehole_and_interpretation_details(qgis_app, dock):
    from geophysics_workbench.core.context import ContextItems, LogInterval, ProjectedPoint
    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id
    from geophysics_workbench.section.dock_context import click_details
    dock.fit.user_navigated()
    dock.canvas.setVisiblePlotRange(0.0, 20.0, -10.0, 5.0)
    qgis_app.processEvents()
    bh = ProjectedPoint(5.0, 1.5, "RK1", "borehole", 0.0,
                        [LogInterval(0.0, 1.0, "peat"), LogInterval(1.0, 3.0, "sand")])
    dock._ctx = (ContextItems(points=[bh]), None)
    lines = click_details(dock, 5.0, -2.0)
    assert lines[0].startswith("Borehole RK1") and any("sand" in x for x in lines)
    store = dock.provider.store
    store.ensure_interpretation()
    v = store.current_version()
    f = InterpFeature(new_id(), v.id, type="clay lens", letter="C", note="check")
    store.save_feature(f)
    store.save_piece(InterpPiece(new_id(), v.id, f.id, dock.current_profile_id(), "polygon",
                                 [(10, 0), (15, 0), (15, -5), (10, -5)]))
    lines = click_details(dock, 12.0, -2.0)
    assert lines[0] == "Interpretation C \u00b7 clay lens (polygon)" and "  Note: check" in lines


def _below_ground_point(dock):
    rng, erng = dock.canvas.visibleDistanceRange(), dock.canvas.visibleElevationRange()
    return ((rng.lower() + rng.upper()) / 2,
            erng.lower() + 0.2 * (erng.upper() - erng.lower()))


def test_draw_tool_snaps_to_existing_vertex(qgis_app, dock):
    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id
    from geophysics_workbench.section.interp_tools import plot_to_canvas

    store = dock.provider.store
    store.ensure_interpretation()
    v = store.current_version().id
    f = InterpFeature(new_id(), v, type="x")
    store.save_feature(f)
    s0, z0 = _below_ground_point(dock)
    store.save_piece(InterpPiece(new_id(), v, f.id, dock.current_profile_id(), "line",
                                 [(s0, z0), (s0 + 5, z0)]))
    ctl = dock.interp
    ctl.form_factory = lambda feature, s, letters, existing=(): InterpFeature(
        feature.id, feature.version_id)
    ctl.start("point")
    px = plot_to_canvas(dock.canvas, s0, z0)
    _click(qgis_app, dock.canvas, int(px.x()) + 2, int(px.y()) + 1)
    new = [p for p in store.pieces(v) if p.kind == "point"]
    assert len(new) == 1 and new[0].vertices[0] == pytest.approx((s0, z0))
    ctl.buttons["snap"].setChecked(False)
    assert ctl.snap(s0 + 0.01, z0, 1.0, 1.0) == (s0 + 0.01, z0)
    ctl.stop()
    from qgis.core import QgsProject
    QgsProject.instance().removeAllMapLayers()


def test_snap_targets_include_borehole_boundaries(qgis_app, dock):
    from geophysics_workbench.core.context import ContextItems, LogInterval, ProjectedPoint

    bh = ProjectedPoint(12.0, 1.0, "B1", "borehole", z_top=100.0,
                        log=[LogInterval(0.0, 2.5, "sand"), LogInterval(2.5, 6.0, "clay")])
    dock.provider.context_source = lambda profile: ContextItems(points=[bh])
    t = dock.interp.snap_targets()
    assert {(12.0, 100.0), (12.0, 97.5), (12.0, 94.0)} <= set(t.boundaries)
    assert t.ground is not None
