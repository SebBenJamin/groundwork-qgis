"""Freezing, viewing and restoring interpretation versions from the section dock."""
import pytest

from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id


@pytest.fixture
def bar(qgis_app, store_with_model, make_dock):
    from qgis.PyQt.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    store = store_with_model[0]
    dock = make_dock(store)
    dock.open_profile(store.profiles()[0].id)
    store.ensure_interpretation()
    v = store.current_version()
    f = InterpFeature(new_id(), v.id, letter="A")
    store.save_feature(f)
    store.save_piece(InterpPiece(new_id(), v.id, f.id, dock.current_profile_id(), "line",
                                 [(1.0, 0.0), (5.0, -1.0)]))
    vb = dock.interp.versions
    vb.refresh()
    yield vb, store, dock
    from qgis.core import QgsProject
    QgsProject.instance().removeAllMapLayers()


def test_freeze_adds_entry_and_keeps_current_selected(bar):
    vb, store, dock = bar
    vb.ask_name = lambda title: "Report 1"
    vb.freeze()
    assert [vb.combo.itemText(i).split(" (")[0] for i in range(vb.combo.count())] == [
        "Current", "Report 1"]
    assert vb.combo.currentIndex() == 0 and dock.provider.interp_version_id is None


def test_viewing_frozen_disables_tools(bar):
    vb, store, dock = bar
    vb.ask_name = lambda title: "R1"
    vb.freeze()
    vb.combo.setCurrentIndex(1)
    ctl = dock.interp
    assert dock.provider.interp_version_id is not None
    assert not ctl.buttons["polygon"].isEnabled() and not ctl.buttons["edit"].isEnabled()
    assert vb.is_readonly() and vb.restore_button.isEnabled()
    vb.combo.setCurrentIndex(0)
    assert ctl.buttons["polygon"].isEnabled() and not vb.restore_button.isEnabled()


def test_start_from_version_with_freeze_first(bar):
    vb, store, dock = bar
    names = iter(["Old", "Before restore"])
    vb.ask_name = lambda title: next(names)
    vb.freeze()                                           # "Old" holds letter A
    cur = store.current_version().id
    [f] = store.features(cur)
    f.letter = "B"
    store.save_feature(f)
    vb.combo.setCurrentIndex(1)                           # view "Old"
    vb.ask_restore = lambda: "freeze"
    vb.start_from()
    assert sorted(v.name for v in store.versions() if v.frozen) == ["Before restore", "Old"]
    assert [x.letter for x in store.features(cur)] == ["A"]
    assert vb.combo.currentIndex() == 0 and dock.provider.interp_version_id is None


def test_start_from_clears_undo(bar):
    vb, store, dock = bar
    ctl = dock.interp
    vb.ask_name = lambda title: "Old"
    vb.freeze()
    [p] = store.pieces(store.current_version().id)
    from geophysics_workbench.section.interp_edit import move_vertex
    ctl.replace_piece(p, move_vertex(p, 0, 2.0, -0.5))
    assert ctl.undo.stack.count() == 1
    vb.combo.setCurrentIndex(1)
    vb.ask_restore = lambda: "replace"
    vb.start_from()
    assert ctl.undo.stack.count() == 0


def test_viewing_frozen_keeps_derived_layers_current(bar):
    from osgeo import ogr
    vb, store, dock = bar
    vb.ask_name = lambda title: "Old"
    vb.freeze()
    dock.interp.changed(store.current_version().id)
    vb.combo.setCurrentIndex(1)                           # view the frozen version
    ds = ogr.Open(str(store.path))
    ids = {f["version_id"] for f in ds.GetLayerByName("interp_lines_3d")}
    ds = None
    assert ids == {store.current_version().id}


def test_sync_detached_when_store_has_no_interpretation(bar, tmp_path):
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.store.gpkg_store import ProjectStore
    vb, store, dock = bar
    ctl = dock.interp
    ctl.changed(store.current_version().id)
    assert ctl._sync is not None
    other = ProjectStore.create(tmp_path / "other.gpkg", store.crs_authid)
    dock.provider = SectionDataProvider(other)
    ctl.ensure_sync()
    assert ctl._sync is None


def test_compare_combo_lists_frozen_and_sets_provider(bar):
    vb, store, dock = bar
    vb.ask_name = lambda title: "R1"
    vb.freeze()
    r1 = next(v for v in store.versions() if v.frozen)
    assert [text.split(" (")[0] for text in vb.compare_items()] == [
        "(none)", "R1"]
    vb.set_compare(1)
    assert dock.provider.interp_compare_version_id == r1.id
    snap = dock.provider.snapshot(dock.current_profile_id())
    assert {p.version_id for p in snap.interp_compare} == {r1.id}
    assert all(p.id in snap.interp_symbols for p in snap.interp_compare)
    vb.combo.setCurrentIndex(1)                      # showing R1 itself: nothing to compare
    assert dock.provider.snapshot(dock.current_profile_id()).interp_compare == []
    vb.combo.setCurrentIndex(0)
    vb.set_compare(0)
    assert dock.provider.interp_compare_version_id is None
    assert dock.provider.snapshot(dock.current_profile_id()).interp_compare == []


def test_compare_unknown_version_resets(bar):
    vb, store, dock = bar
    dock.provider.interp_compare_version_id = "gone"
    vb.refresh()
    assert vb.compare_index() == 0 and dock.provider.interp_compare_version_id is None


def test_row_is_compact(bar):
    from qgis.PyQt.QtWidgets import QPushButton
    _vb, _store, dock = bar
    row = dock.interp.bar
    widgets = [row.itemAt(i).widget() for i in range(row.count()) if row.itemAt(i).widget()]
    assert len(widgets) == 11              # + Note (field notes)
    assert not any(isinstance(w, QPushButton) for w in widgets)
    assert all(
        w.text() not in ("Freeze…", "Start from this version") for w in dock.findChildren(QPushButton))
    menu = dock.interp.menu
    texts = [a.text() for a in menu.actions() if not a.isSeparator()]
    assert texts[:6] == ["Types…", "Export…", "Field notes…", "Show field notes", "Freeze…",
                         "Start from this version"]
    assert texts[6] == "Compare with"
