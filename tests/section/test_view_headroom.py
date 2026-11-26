"""Room for the geology band and the context labels above the section: a fixed pixel
height, so a short bottom dock still shows them (Important 1), and "Zoom Full" covers the
context z (borehole logs, tie strips; R19b)."""
import numpy as np
import pytest

from groundwork_geophysics.core.context import (BandSegment, ContextItems, Crossing, LogInterval,
                                               ProjectedPoint)


def test_headroom_covers_the_band_and_three_label_rows(qgis_app):
    """The fitter's pixel figure and the drawing's own placement agree: three labels at
    the same chainage stack in three rows, and the top one ends inside the headroom."""
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtGui import QImage, QPainter, QTransform

    from groundwork_geophysics.section.context_render import (context_headroom_px, mm,
                                                             plan_labels, set_label_font)

    img = QImage(400, 400, QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    try:
        rc = QgsRenderContext.fromQPainter(painter)
        wt = QTransform(10.0, 0.0, 0.0, -10.0, 0.0, 300.0)       # z = 0 at y = 300
        items = ContextItems(crossings=[Crossing(20.0, f"Line {i}", "line", 90.0)
                                        for i in range(3)])
        plan = plan_labels(painter, rc, wt, items, (np.array([0.0, 40.0]), np.zeros(2)))
        set_label_font(painter, rc)
        line_height = painter.fontMetrics().height()
        need = context_headroom_px(mm(rc, 1.0), line_height)
    finally:
        painter.end()
    assert len({round(lab.y) for lab in plan.values()}) == 3     # three rows
    top = min(lab.y for lab in plan.values()) - line_height
    assert 300 - top <= need <= 300 - top + 2


def _context(profile):
    return ContextItems(crossings=[Crossing(20.0, "HS 110 kV", "line", 90.0)],
                        points=[ProjectedPoint(30.0, 2.0, "BK1", "borehole", None,
                                               [LogInterval(0.0, 3.0, "Sand")])],
                        band=[BandSegment(0.0, 50.0, "Talsand")])


def test_short_dock_keeps_the_label_rows_inside_the_plot(qgis_app, store_with_model, make_dock):
    from qgis.core import QgsProfilePoint

    from groundwork_geophysics.section.view_extent import headroom_px

    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.provider.context_source = _context
    dock.resize(1100, 260)
    dock.ve_spin.setValue(2.0)               # a typed VE keeps every label row inside the plot
    qgis_app.processEvents()
    dock.open_profile(p.id)
    qgis_app.processEvents()
    dock.zoom_full()
    area = dock.canvas.plotArea()
    assert 120 <= area.height() <= 220, area.height()           # a short bottom dock
    need = headroom_px(dock)
    assert need > 60                                            # band plus three label rows
    surface_top = dock.canvas.plotPointToCanvasPoint(QgsProfilePoint(50.0, 102.0)).y()
    assert surface_top - need >= area.top() - 0.5               # the top label row fits
    e = dock.canvas.visibleElevationRange()
    assert e.lower() <= -5                                      # the model still fits


def test_headroom_is_zero_without_context(qgis_app, store_with_model, make_dock):
    from groundwork_geophysics.section.view_extent import headroom_px

    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    assert headroom_px(dock) == 0.0
    dock.provider.context_source = lambda profile: ContextItems(
        band=[BandSegment(0.0, 50.0, "Talsand")])
    band_only = headroom_px(dock)
    dock.provider.context_source = _context
    assert 0.0 < band_only < headroom_px(dock)


def test_zoom_full_includes_borehole_bottoms_and_tie_columns(qgis_app, store_with_model,
                                                             make_dock):
    from groundwork_geophysics.core.colors import ColorScale
    from groundwork_geophysics.core.ties import Tie, TieColumn
    from groundwork_geophysics.section.view_extent import data_extent

    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.open_profile(p.id)
    plain = data_extent(dock)
    bh = ProjectedPoint(25.0, 1.0, "BK1", "borehole", None, [LogInterval(0.0, 150.0, "Kies")])
    col = TieColumn("P3", np.array([101.0, -20.0]), np.array([-20.0, -80.0]),
                    np.array([5.0, 50.0]), ColorScale(), "resistivity", "ohm.m")
    items = ContextItems(points=[bh])
    dock.provider.context_source = lambda profile: items
    real_ties = dock.provider.ties
    dock.provider.ties = lambda pid, defer=None: [Tie(10.0, "p3", "P3", 5.0, 0.0, [col])]
    try:
        s0, s1, z0, z1 = data_extent(dock)
    finally:
        dock.provider.ties = real_ties
    assert plain[2] > -60                                       # the model alone is shallower
    # surface at s = 25 is 101 m, the log 150 m long: bottom at -49; the tie column -80
    assert z0 == pytest.approx(-80.0)
    assert (s0, s1, z1) == pytest.approx(plain[:2] + (plain[3],))
    dock.provider.ties = lambda pid, defer=None: []
    try:
        assert data_extent(dock)[2] == pytest.approx(-49.0)
    finally:
        dock.provider.ties = real_ties


def test_zoom_full_of_a_local_section_leaves_out_the_boreholes(qgis_app, tmp_path, make_dock):
    import shutil
    from pathlib import Path

    from groundwork_geophysics.core.model import Dataset, file_fingerprint, profile_from_polyline
    from groundwork_geophysics.section.view_extent import data_extent
    from groundwork_geophysics.store.gpkg_store import ProjectStore

    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p = profile_from_polyline("L", "EPSG:25832", np.array([[0.0, 0.0], [50.0, 0.0]]))
    st.save_profile(p)
    src = tmp_path / "zond_model_depth.dat"
    shutil.copy(Path(__file__).resolve().parent.parent / "fixtures" / "ert" /
                "zond_model_depth.dat", src)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("z", p.id, "", "ert_model", str(src), mt, sha, "zondres_xyz",
                            {"z_kind": "depth"}, {}, name="z"))
    dock = make_dock(st)
    dock.open_profile(p.id)
    bh = ProjectedPoint(25.0, 1.0, "BK1", "borehole", 250.0, [LogInterval(0.0, 10.0, "Kies")])
    dock.provider.context_source = lambda profile: ContextItems(points=[bh])
    assert dock.provider.is_local(p.id)
    assert data_extent(dock)[2:] == pytest.approx((-6.0, 0.0))     # the model alone
