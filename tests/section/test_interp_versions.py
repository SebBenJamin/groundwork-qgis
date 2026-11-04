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
    assert vb.readonly_label.isVisibleTo(vb.widget) and vb.restore_button.isEnabled()
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
