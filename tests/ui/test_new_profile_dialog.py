"""New-profile dialog: station-file order, coordinate checks, numbering from the end,
duplicate-geometry warning. Driven programmatically (offscreen)."""
import numpy as np
import pytest


def _close(dialog, qgis_app):
    dialog.close()
    dialog.deleteLater()
    qgis_app.processEvents()


def test_new_profile_from_unsorted_station_file(qgis_app, fake_iface, project_store,
                                                tmp_path, warnings_shown):
    """Rows recorded from the far end and out of order: the line follows the numbers."""
    from geophysics_workbench.ui.new_profile_dialog import TAB_FILE, NewProfileDialog

    st, prj = project_store
    csv = tmp_path / "unsorted.csv"
    rows = [(3, 110.0), (1, 120.0), (4, 105.0), (2, 115.0), (5, 100.0)]
    csv.write_text("number,x,y,z\n" + "".join(f"{n},{x},0,50\n" for n, x in rows),
                   encoding="utf-8")
    dlg = NewProfileDialog(fake_iface, st, project=prj)
    try:
        dlg.tabs.setCurrentIndex(TAB_FILE)
        dlg.set_station_file(csv)
        dlg.accept()
        assert dlg.result() == 1, warnings_shown
        [p] = st.profiles()
        assert p.chainage.length == pytest.approx(20)                 # straight, no zigzag
        assert np.allclose(p.xy[0], [120, 0]) and np.allclose(p.xy[-1], [100, 0])
        [s] = st.station_sets(p.id)
        assert s.numbers.tolist() == [1, 2, 3, 4, 5] and s.direction == 1
    finally:
        _close(dlg, qgis_app)


def _points_dialog(fake_iface, st, prj, name, xy):
    from geophysics_workbench.ui.new_profile_dialog import TAB_POINTS, NewProfileDialog

    dlg = NewProfileDialog(fake_iface, st, project=prj)
    dlg.tabs.setCurrentIndex(TAB_POINTS)
    dlg.name_edit.setText(name)
    for w, v in zip((dlg.x1, dlg.y1, dlg.x2, dlg.y2), np.ravel(xy)):
        w.setValue(float(v))
    return dlg


def test_new_profile_warns_when_geometry_duplicates_a_profile(qgis_app, fake_iface,
                                                              project_store, warnings_shown):
    st, prj = project_store
    fake_iface.messageBar().clearWidgets()
    first = _points_dialog(fake_iface, st, prj, "L1", [[1000, 2000], [1000, 2100]])
    try:
        first.accept()
        assert first.result() == 1 and first.last_warning is None
    finally:
        _close(first, qgis_app)
    twin = _points_dialog(fake_iface, st, prj, "L1 copy", [[1000, 2100], [1000, 2000]])
    try:
        twin.accept()
        assert twin.result() == 1 and not warnings_shown          # non-blocking: saved
        assert len(st.profiles()) == 2
        assert "L1" in twin.last_warning and "same line" in twin.last_warning
        assert fake_iface.messageBar().currentItem() is not None
    finally:
        _close(twin, qgis_app)


def test_station_file_in_degrees_is_refused(qgis_app, fake_iface, project_store, tmp_path,
                                            warnings_shown):
    from qgis.PyQt.QtWidgets import QLabel

    from geophysics_workbench.ui.new_profile_dialog import NONE, TAB_FILE, NewProfileDialog

    st, prj = project_store
    csv = tmp_path / "gps.csv"
    csv.write_text("number,lon,lat\n1,9.8501,52.7501\n2,9.8502,52.7502\n3,9.8503,52.7503\n",
                   encoding="utf-8")
    dlg = NewProfileDialog(fake_iface, st, project=prj)
    try:
        labels = [w.text() for w in dlg.tabs.widget(TAB_FILE).findChildren(QLabel)]
        assert "Coordinates must be in EPSG:25832" in labels
        dlg.tabs.setCurrentIndex(TAB_FILE)
        dlg.set_station_file(csv)
        dlg.col_x.setCurrentIndex(dlg.col_x.findData(1))
        dlg.col_y.setCurrentIndex(dlg.col_y.findData(2))
        dlg.col_z.setCurrentIndex(dlg.col_z.findData(NONE))
        dlg.accept()
        assert dlg.result() == 0 and st.profiles() == []
        assert "degrees" in warnings_shown[-1] and "EPSG:25832" in warnings_shown[-1]
    finally:
        _close(dlg, qgis_app)


def test_looks_like_degrees_rule():
    from geophysics_workbench.ui.station_columns import looks_like_degrees

    assert looks_like_degrees(np.array([[9.85, 52.75], [9.86, 52.76]]))
    assert not looks_like_degrees(np.array([[0.0, 0.0], [50.0, 0.0]]))       # local metres
    assert not looks_like_degrees(np.array([[437731.3, 5850754.4], [437730.7, 5850759.4]]))
    assert not looks_like_degrees(np.array([[10.0, 20.0], [10.5, 95.0]]))     # |y| > 90


def test_line_profile_numbered_from_the_end(qgis_app, fake_iface, project_store,
                                            warnings_shown):
    from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

    from geophysics_workbench.ui.new_profile_dialog import TAB_LINE

    st, prj = project_store
    layer = QgsVectorLayer("LineString?crs=EPSG:25832", "lines", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromWkt("LineString (0 0, 30 40, 60 40)"))
    layer.dataProvider().addFeatures([f])
    layer.selectAll()
    fake_iface.setActiveLayer(layer)
    dlg = _points_dialog(fake_iface, st, prj, "Back", [[0, 0], [0, 0]])
    try:
        dlg.tabs.setCurrentIndex(TAB_LINE)
        dlg.line_spacing.setValue(10.0)
        assert dlg.line_from_end.text() == "Number stations from the end"
        dlg.line_from_end.setChecked(True)
        dlg.accept()
        assert dlg.result() == 1, warnings_shown
        [p] = st.profiles()
        assert np.allclose(p.xy, [[60, 40], [30, 40], [0, 0]])
        [s] = st.station_sets(p.id)
        assert np.allclose(s.xyz[0, :2], [60, 40]) and s.numbers[0] == 1
    finally:
        fake_iface.setActiveLayer(None)
        _close(dlg, qgis_app)


def test_points_profile_numbered_from_the_end(qgis_app, fake_iface, project_store):
    st, prj = project_store
    dlg = _points_dialog(fake_iface, st, prj, "Back", [[1000, 2000], [1000, 2012]])
    try:
        assert dlg.points_from_end.text() == "Number stations from the end"
        dlg.points_from_end.setChecked(True)
        dlg.accept()
        [p] = st.profiles()
        assert np.allclose(p.xy, [[1000, 2012], [1000, 2000]])
        [s] = st.station_sets(p.id)
        assert np.allclose(s.xyz[:, :2], [[1000, 2012], [1000, 2007], [1000, 2002]])
    finally:
        _close(dlg, qgis_app)
