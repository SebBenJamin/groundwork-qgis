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
    from groundwork_geophysics.section import dock as dock_module
    from groundwork_geophysics.section.dock import AUTO_VE
    monkeypatch.setattr(dock_module, "data_extent", lambda d: (0.0, 50.0, -8.0, 2.0))
    st, p, _ = store_with_model
    dock = _dock(make_dock, st, qgis_app)
    assert dock.ve_spin.value() == AUTO_VE and dock.ve_spin.specialValueText().startswith("Auto")
    dock.zoom_full()
    s0, s1, z0, z1 = dock._fit_extent()
    d = dock.canvas.visibleDistanceRange()
    e = dock.canvas.visibleElevationRange()
    assert (d.upper() - d.lower()) <= (s1 - s0) * 1.35                # most of the width
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
    from groundwork_geophysics.section import dock as dock_module
    monkeypatch.setattr(dock_module, "data_extent", lambda d: (0.0, 50.0, -8.0, 2.0))
    monkeypatch.setattr(dock_module, "headroom_px", lambda d: 60.0)
    st, p, _ = store_with_model
    dock = _dock(make_dock, st, qgis_app)
    dock.zoom_full()
    d = dock.canvas.visibleDistanceRange()
    e = dock.canvas.visibleElevationRange()
    area = dock.canvas.plotArea()
    epp = (e.upper() - e.lower()) / area.height()
    assert (d.upper() - d.lower()) <= 50.0 * 1.35
    room = min(60.0, 0.3 * area.height())                  # Auto: at most 30 % of the plot
    assert e.upper() - 2.0 >= room * epp * 0.95             # the label room above the data


def test_empty_panel_shows_hint_not_axes(qgis_app, store_with_model, make_dock):
    from groundwork_geophysics.section.dock import HINT_NO_PROFILE
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.show()
    qgis_app.processEvents()
    assert dock.empty_hint.isVisible() and not dock.canvas.isVisible()
    assert HINT_NO_PROFILE.split(",")[0] in dock.empty_hint.text()   # (the rest is a link)
    dock.open_profile(p.id)
    qgis_app.processEvents()
    assert dock.canvas.isVisible() and not dock.empty_hint.isVisible()


def test_auto_on_a_short_laptop_panel(qgis_app, store_with_model, make_dock, monkeypatch):
    """Usability review 2, R1: at the default docked height (~289 px on 1366x768) Auto went
    down to 0.5x with labels taking 62 % of the plot: a thin strip with wide margins. Now
    label room is at most 30 %, the section fills the width, and the box shows the VE."""
    from groundwork_geophysics.section import dock as dock_module
    from groundwork_geophysics.section.view_fit import AUTO_HEADROOM, AUTO_MIN
    monkeypatch.setattr(dock_module, "data_extent", lambda d: (0.0, 49.0, 172.0, 182.0))
    monkeypatch.setattr(dock_module, "headroom_px", lambda d: 91.0)
    st, p, _ = store_with_model
    dock = _dock(make_dock, st, qgis_app, 1366, 289)
    dock.zoom_full()
    assert AUTO_MIN == 0.5 and AUTO_HEADROOM == 0.3
    assert dock.canvas.axisScaleRatio() >= AUTO_MIN - 1e-9
    assert dock.ve_spin.text().startswith("Auto (") and "×" in dock.ve_spin.text()
    d = dock.canvas.visibleDistanceRange()
    assert (d.upper() - d.lower()) <= 49.0 * 1.25                      # the width is used


def test_labels_above_the_plot_top_are_left_out(qgis_app):
    import numpy as np
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtCore import QRectF
    from qgis.PyQt.QtGui import QImage, QPainter, QTransform

    from groundwork_geophysics.core.context import ContextItems, ProjectedPoint
    from groundwork_geophysics.section.context_render import plan_labels
    img = QImage(800, 400, QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    try:
        rc = QgsRenderContext.fromQPainter(painter)
        wt = QTransform(10, 0, 0, -10, 0, 200)
        items = ContextItems(points=[ProjectedPoint(10 + 0.3 * i, 0.5, f"EN-RK {40 + i}",
                                                    "point") for i in range(6)])
        surface = (np.array([0.0, 80.0]), np.array([0.0, 0.0]))
        full = plan_labels(painter, rc, wt, items, surface)
        lowest = max(lab.y for lab in full.values())
        painter.setClipRect(QRectF(0, lowest - 20, 800, 400))   # room for one row only
        clipped = plan_labels(painter, rc, wt, items, surface)
        assert 0 < len(clipped) < len(full)
        assert all(lab.y == lowest for lab in clipped.values())
    finally:
        painter.end()
