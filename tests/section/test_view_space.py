"""Usability round 1, Task 4: the section uses the docked panel's space; an empty panel says
what to do."""
import pytest


def _dock(make_dock, store, qgis_app, w=1366, h=300):
    import time
    dock = make_dock(store)
    dock.resize(w, h)
    dock.show()
    dock.open_profile(store.profiles()[0].id)
    for _ in range(40):
        qgis_app.processEvents()
        time.sleep(0.02)
    return dock


def test_auto_ve_fills_the_docked_panel(qgis_app, store_with_model, make_dock, monkeypatch):
    """A real section is wide and shallow (here 50 m x 10 m; the test store's station
    heights sit 100 m above its model)."""
    from geophysics_workbench.section import dock as dock_module
    from geophysics_workbench.section.dock import AUTO_VE
    monkeypatch.setattr(dock_module, "data_extent", lambda d: (0.0, 50.0, -8.0, 2.0))
    st, p, _ = store_with_model
    dock = _dock(make_dock, st, qgis_app)
    assert dock.ve_spin.value() == AUTO_VE and dock.ve_spin.specialValueText() == "Auto"
    dock.zoom_full()
    s0, s1, z0, z1 = dock._fit_extent()
    d = dock.canvas.visibleDistanceRange()
    e = dock.canvas.visibleElevationRange()
    assert (d.upper() - d.lower()) <= (s1 - s0) * 1.15                # the width is used
    assert e.lower() <= z0 and e.upper() >= z1                         # the full depth shows
    assert "×" in dock.ve_spin.toolTip()                               # the VE it chose


def test_typed_ve_is_kept(qgis_app, store_with_model, make_dock):
    st, p, _ = store_with_model
    dock = _dock(make_dock, st, qgis_app)
    dock.ve_spin.setValue(2.0)
    dock.zoom_full()
    assert dock.canvas.axisScaleRatio() == pytest.approx(2.0)


def test_auto_ve_keeps_room_for_labels(qgis_app, store_with_model, make_dock, monkeypatch):
    """Auto chooses the exaggeration with the label room included: labels stay inside the
    plot and the section still fills the width."""
    from geophysics_workbench.section import dock as dock_module
    monkeypatch.setattr(dock_module, "data_extent", lambda d: (0.0, 50.0, -8.0, 2.0))
    monkeypatch.setattr(dock_module, "headroom_px", lambda d: 60.0)
    st, p, _ = store_with_model
    dock = _dock(make_dock, st, qgis_app)
    dock.zoom_full()
    d = dock.canvas.visibleDistanceRange()
    e = dock.canvas.visibleElevationRange()
    area = dock.canvas.plotArea()
    epp = (e.upper() - e.lower()) / area.height()
    assert (d.upper() - d.lower()) <= 50.0 * 1.15
    assert e.upper() - 2.0 >= 60.0 * epp * 0.95             # the label room above the data


def test_empty_panel_shows_hint_not_axes(qgis_app, store_with_model, make_dock):
    from geophysics_workbench.section.dock import HINT_NO_PROFILE
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.show()
    qgis_app.processEvents()
    assert dock.empty_hint.isVisible() and not dock.canvas.isVisible()
    assert HINT_NO_PROFILE in dock.empty_hint.text()
    dock.open_profile(p.id)
    qgis_app.processEvents()
    assert dock.canvas.isVisible() and not dock.empty_hint.isVisible()
