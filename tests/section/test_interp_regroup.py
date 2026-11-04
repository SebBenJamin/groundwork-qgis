"""Regrouping interpretation: move pieces between features, merge/split features, rename
types. Every operation is one undo step."""
import pytest
from qgis.PyQt.QtCore import QEvent

from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id


@pytest.fixture
def two(qgis_app, store_with_model, make_dock):
    from qgis.PyQt.QtCore import QCoreApplication
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qgis_app.processEvents()
    store = store_with_model[0]
    prof = store.profiles()[0]
    store.ensure_interpretation()
    v = store.current_version().id
    from osgeo import ogr
    ds = ogr.Open(str(store.path), 1)               # a field the user added in QGIS
    ds.GetLayerByName("interp_features").CreateField(ogr.FieldDefn("drill", ogr.OFTString))
    ds = None
    a = InterpFeature(new_id(), v, type="Clay lens", letter="A", confidence="certain",
                      note="n", extra={"drill": "yes"})
    b = InterpFeature(new_id(), v, type="clay", letter="B")
    for f in (a, b):
        store.save_feature(f)
    pa1 = store.save_piece(InterpPiece(new_id(), v, a.id, prof.id, "line", [(1, 0), (5, -1)]))
    pa2 = store.save_piece(InterpPiece(new_id(), v, a.id, prof.id, "line", [(6, 0), (9, -1)]))
    pb = store.save_piece(InterpPiece(new_id(), v, b.id, prof.id, "point", [(20, -2)]))
    dock = make_dock(store)
    dock.open_profile(prof.id)
    ctl = dock.interp
    ctl.undo.clear()
    return ctl, store, v, a, b, pa1, pa2, pb


def _owner(store, v, piece):
    return next(p.feature_id for p in store.pieces(v) if p.id == piece.id)


def _feature_ids(store, v):
    return {f.id for f in store.features(v)}


def test_move_piece_to_other_feature_and_undo(two):
    ctl, store, v, a, b, pa1, _pa2, _pb = two
    ctl.move_piece_to(pa1, b.id)
    assert _owner(store, v, pa1) == b.id
    ctl.undo.stack.undo()
    assert _owner(store, v, pa1) == a.id
    ctl.undo.stack.redo()
    assert _owner(store, v, pa1) == b.id


def test_moving_last_piece_deletes_empty_feature_undo_restores_it(two):
    ctl, store, v, a, b, _pa1, _pa2, pb = two
    ctl.move_piece_to(pb, a.id)
    assert b.id not in _feature_ids(store, v)
    ctl.undo.stack.undo()
    assert b.id in _feature_ids(store, v) and _owner(store, v, pb) == b.id


def test_split_piece_into_new_feature_copies_attributes(two):
    ctl, store, v, a, b, _pa1, pa2, _pb = two
    ctl.move_piece_to(pa2, None)
    new = [f for f in store.features(v) if f.id not in (a.id, b.id)]
    assert len(new) == 1
    n = new[0]
    assert (n.type, n.confidence, n.note, n.letter) == (a.type, a.confidence, a.note, "")
    assert n.extra == a.extra and _owner(store, v, pa2) == n.id
    ctl.undo.stack.undo()
    assert _feature_ids(store, v) == {a.id, b.id} and _owner(store, v, pa2) == a.id


def test_merge_features(two):
    ctl, store, v, a, b, *_ = two
    ctl.merge_features(b.id, a.id)
    assert {p.feature_id for p in store.pieces(v)} == {a.id}
    assert b.id not in _feature_ids(store, v)
    ctl.undo.stack.undo()
    assert {p.feature_id for p in store.pieces(v)} == {a.id, b.id}
    assert b.id in _feature_ids(store, v)


def test_noops_push_nothing(two):
    ctl, _store, _v, a, _b, pa1, *_ = two
    ctl.move_piece_to(pa1, a.id)
    ctl.merge_features(a.id, a.id)
    assert ctl.rename_type("no such type", "x") == 0
    assert ctl.undo.stack.count() == 0


def test_rename_type_merges_case_insensitively(two):
    ctl, store, v, *_ = two
    assert ctl.rename_type("clay", "clay LENS") == 1
    assert {f.type for f in store.features(v)} == {"Clay lens"}
    ctl.undo.stack.undo()
    assert {f.type for f in store.features(v)} == {"Clay lens", "clay"}


def test_regroup_refused_on_frozen_version(two):
    ctl, store, *_ = two
    frozen = store.freeze_current("R1")
    p = store.pieces(frozen.id)[0]
    with pytest.raises(PermissionError):
        ctl.move_piece_to(p, None)
    with pytest.raises(PermissionError):
        ctl.merge_features(store.features(frozen.id)[0].id, store.features(frozen.id)[1].id)


def test_edit_tool_menu_lists_other_features(two):
    from geophysics_workbench.section.interp_tools import EditTool
    ctl, _store, _v, _a, _b, pa1, *_ = two
    tool = EditTool(ctl.dock.canvas, ctl)
    actions = tool.menu_actions(pa1)
    assert [label for label, _ in actions] == ["Attributes…", "Move piece to",
                                               "Merge this feature into", "Delete piece"]
    move = dict(actions)["Move piece to"]
    assert [label for label, _ in move] == ["New feature", "B · clay"]
    assert [label for label, _ in dict(actions)["Merge this feature into"]] == ["B · clay"]
    dict(move)["B · clay"]()
    assert _owner(ctl.dock.provider.store, _v, pa1) == _b.id


def test_types_button_disabled_on_frozen_version(two):
    ctl, store, *_ = two
    r1 = store.freeze_current("R1")
    ctl.versions.refresh(r1.id)
    assert not ctl.buttons["types"].isEnabled()
    assert store.type_counts(store.current_version().id) == {"Clay lens": 1, "clay": 1}
