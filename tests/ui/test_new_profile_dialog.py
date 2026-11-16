"""New Profile dialog: a name, the method and where the line runs. A line never gets invented
stations; positions keep their order by number; the duplicate-geometry warning and the
pick on the map are kept. Driven programmatically (offscreen)."""
from pathlib import Path

import numpy as np
import pytest

WILD = Path(__file__).resolve().parent.parent / "fixtures" / "wild"


def _close(dialog, qgis_app):
    dialog.close()
    dialog.deleteLater()
    qgis_app.processEvents()


@pytest.fixture
def make_dialog(qgis_app, fake_iface, project_store):
    from groundwork_geophysics.ui.new_profile_dialog import NewProfileDialog

    st, prj = project_store
    made = []

    def make(name=""):
        dlg = NewProfileDialog(fake_iface, st, project=prj)
        dlg.name_edit.setText(name)
        dlg.show()
        qgis_app.processEvents()
        made.append(dlg)
        return dlg

    yield make
    for dlg in made:
        _close(dlg, qgis_app)


@pytest.fixture
def line_layer(qgis_app, fake_iface):
    """A memory line layer (EPSG:25832) with one bent line, active, nothing selected."""
    from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

    layer = QgsVectorLayer("LineString?crs=EPSG:25832", "lines", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromWkt("LineString (0 0, 30 40, 60 40)"))
    layer.dataProvider().addFeatures([f])
    fake_iface.setActiveLayer(layer)
    yield layer
    fake_iface.setActiveLayer(None)


def _points_dialog(make_dialog, name, xy):
    dlg = make_dialog(name)
    dlg.placement.set_points(*np.ravel(xy))
    return dlg


def test_line_feature_profile_has_no_stations(qgis_app, fake_iface, project_store, make_dialog,
                                              line_layer, warnings_shown):
    st, prj = project_store
    dlg = make_dialog("Crooked")
    dlg.placement.select_source("line")
    assert not dlg.placement.spacing_edit.isVisible()
    assert not dlg.method_combo.isVisible()              # a line makes no station set
    dlg.accept()                                         # nothing selected yet
    assert "select" in warnings_shown[-1].lower() and st.profiles() == []
    line_layer.selectAll()
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    assert p.name == "Crooked" and dlg.profile.id == p.id
    assert np.allclose(p.xy, [[0, 0], [30, 40], [60, 40]])
    assert st.station_sets(p.id) == []
    assert "electrode_spacing" not in p.metadata
    assert prj.mapLayersByName("profiles")[0].featureCount() == 1


def test_two_points_profile_has_no_stations(qgis_app, project_store, make_dialog,
                                            warnings_shown):
    st, _prj = project_store
    dlg = _points_dialog(make_dialog, "L2", [[1000, 2000], [1000, 2100]])
    assert not dlg.placement.spacing_edit.isVisible()     # no spacing for a line
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    assert np.allclose(p.xy, [[1000, 2000], [1000, 2100]])
    assert st.station_sets(p.id) == []


def test_identical_points_are_refused(qgis_app, project_store, make_dialog, warnings_shown):
    st, _prj = project_store
    dlg = make_dialog("L3")
    dlg.placement.select_source("points")               # all coordinates 0: same point
    dlg.accept()
    assert "different" in warnings_shown[-1].lower() and st.profiles() == []
    assert dlg.result() == 0


def test_line_and_points_can_be_reversed(qgis_app, project_store, make_dialog, line_layer,
                                         warnings_shown):
    """The old "Number stations from the end" chose the profile's direction; without
    stations the choice is "Reverse the line"."""
    st, _prj = project_store
    line_layer.selectAll()
    dlg = make_dialog("Back")
    dlg.placement.select_source("line")
    assert dlg.reverse_check.text() == "Reverse the line" and dlg.reverse_check.isVisible()
    dlg.reverse_check.setChecked(True)
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    assert np.allclose(p.xy, [[60, 40], [30, 40], [0, 0]]) and st.station_sets(p.id) == []

    dlg = _points_dialog(make_dialog, "Back 2", [[1000, 2000], [1000, 2012]])
    dlg.reverse_check.setChecked(True)
    dlg.accept()
    p = next(q for q in st.profiles() if q.name == "Back 2")
    assert np.allclose(p.xy, [[1000, 2012], [1000, 2000]])

    dlg = make_dialog("Positions")
    dlg.placement.set_positions_file(WILD / "positions_sparse.csv")
    assert not dlg.reverse_check.isVisible()             # positions follow their numbers


def test_positions_file_in_another_crs(qgis_app, project_store, make_dialog, tmp_path,
                                       warnings_shown):
    from qgis.core import QgsCoordinateReferenceSystem

    st, _prj = project_store
    csv = tmp_path / "gps.csv"
    csv.write_text("number,lon,lat\n1,9.8501,52.7501\n2,9.8502,52.7502\n3,9.8503,52.7503\n",
                   encoding="utf-8")
    dlg = make_dialog()
    dlg.placement.set_positions_file(csv)
    assert dlg.name_edit.text() == "gps"                 # named after the file
    assert dlg.method_combo.isVisible()                  # positions make a station set
    roles = dlg.placement.role_combos
    for role, column in (("easting", 1), ("northing", 2)):
        roles[role].setCurrentIndex(roles[role].findData(column))
    assert dlg.placement.crs_widget.crs().authid() == st.crs_authid
    dlg.accept()                                         # degrees taken as metres: refused
    assert dlg.result() == 0 and st.profiles() == []
    assert "degrees" in warnings_shown[-1]
    dlg.placement.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    [s] = st.station_sets(p.id)
    assert s.numbers.tolist() == [1, 2, 3] and s.method == "ert"
    assert np.all((500_000 < s.xyz[:, 0]) & (s.xyz[:, 0] < 600_000))
    assert np.all((5_800_000 < s.xyz[:, 1]) & (s.xyz[:, 1] < 5_900_000))


def test_unsorted_positions_follow_the_numbers(qgis_app, project_store, make_dialog, tmp_path,
                                               warnings_shown):
    """Rows recorded from the far end and out of order: the line follows the numbers."""
    st, _prj = project_store
    csv = tmp_path / "unsorted.csv"
    rows = [(3, 110.0), (1, 120.0), (4, 105.0), (2, 115.0), (5, 100.0)]
    csv.write_text("number,x,y,z\n" + "".join(f"{n},{x},0,50\n" for n, x in rows),
                   encoding="utf-8")
    dlg = make_dialog()
    dlg.placement.set_positions_file(csv)
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    assert p.name == "unsorted"
    assert p.chainage.length == pytest.approx(20)                 # straight, no zigzag
    assert np.allclose(p.xy[0], [120, 0]) and np.allclose(p.xy[-1], [100, 0])
    [s] = st.station_sets(p.id)
    assert s.numbers.tolist() == [1, 2, 3, 4, 5] and s.direction == 1


def test_duplicate_line_warning_is_kept(qgis_app, fake_iface, project_store, make_dialog,
                                        warnings_shown):
    st, _prj = project_store
    fake_iface.messageBar().clearWidgets()
    first = _points_dialog(make_dialog, "L1", [[1000, 2000], [1000, 2100]])
    first.accept()
    assert first.result() == 1 and first.last_warning is None
    twin = _points_dialog(make_dialog, "L1 copy", [[1000, 2100], [1000, 2000]])
    twin.accept()
    assert twin.result() == 1 and not warnings_shown          # non-blocking: saved
    assert len(st.profiles()) == 2
    assert "L1" in twin.last_warning and "same line" in twin.last_warning
    assert "L1 copy" not in twin.last_warning.split("same line")[1]   # not its own twin
    assert fake_iface.messageBar().currentItem() is not None


def test_pick_on_map_still_hides_and_returns(qgis_app, fake_iface, project_store, make_dialog):
    from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY
    from qgis.gui import QgsMapToolPan
    from qgis.PyQt.QtCore import Qt

    canvas = fake_iface.mapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
    pan = QgsMapToolPan(canvas)
    canvas.setMapTool(pan)
    dlg = make_dialog("Picked")
    dlg.placement.start_pick()
    tool = canvas.mapTool()
    assert tool is not pan and not dlg.isVisible()
    tool.canvasClicked.emit(QgsPointXY(10.0, 20.0), Qt.MouseButton.LeftButton)
    assert not dlg.isVisible()                          # waits for the end point
    tool.canvasClicked.emit(QgsPointXY(30.0, 40.0), Qt.MouseButton.LeftButton)
    qgis_app.processEvents()
    p = dlg.placement
    assert (p.x1.value(), p.y1.value(), p.x2.value(), p.y2.value()) == (10, 20, 30, 40)
    assert canvas.mapTool() is pan and dlg.isVisible()  # back after the second click
    assert p.source() == "points"

    dlg.placement.start_pick()                          # closed mid-pick: tool released,
    dlg.reject()                                        # the dialog stays closed
    qgis_app.processEvents()
    assert canvas.mapTool() is pan and not dlg.isVisible()


def test_store_write_error_is_shown(qgis_app, project_store, make_dialog, warnings_shown,
                                    monkeypatch):
    st, _prj = project_store

    def broken(*_a, **_k):
        raise RuntimeError("attempt to write a readonly database")

    monkeypatch.setattr(st, "_write_profile", broken)
    dlg = _points_dialog(make_dialog, "L", [[0, 0], [20, 0]])
    dlg.accept()
    assert "readonly" in warnings_shown[-1] and dlg.result() == 0
    assert dlg.profile is None and dlg.last_error == warnings_shown[-1]


def test_hig_rules_with_positions(qgis_app, project_store, make_dialog):
    from tests.ui.test_hig_strings import collect, problems

    dlg = make_dialog()
    assert dlg.windowTitle() == "New Profile"
    dlg.placement.set_positions_file(WILD / "positions_sparse.csv")
    entries = [e for e in collect(dlg) if e[0] != "tool"]   # QGIS's own tool buttons
    assert not problems(entries, "New Profile")


def test_looks_like_degrees_rule():
    from groundwork_geophysics.core.roles import looks_like_degrees

    assert looks_like_degrees(np.array([[9.85, 52.75], [9.86, 52.76]]))
    assert not looks_like_degrees(np.array([[0.0, 0.0], [50.0, 0.0]]))       # local metres
    assert not looks_like_degrees(np.array([[437731.3, 5850754.4], [437730.7, 5850759.4]]))
    assert not looks_like_degrees(np.array([[10.0, 20.0], [10.5, 95.0]]))     # |y| > 90


def test_dialog_opens_at_its_content_and_grows_with_it(qgis_app, make_dialog):
    dlg = make_dialog("Sized")
    line_height = dlg.height()
    dlg.placement.set_positions_file(WILD / "positions_sparse.csv")
    qgis_app.processEvents()
    assert dlg.height() > line_height and dlg.height() <= 580
    grown = dlg.height()
    dlg.placement.select_source("line")
    qgis_app.processEvents()
    assert dlg.height() == grown                     # never shrinks


def test_opens_wide_enough_for_its_hints(qgis_app, make_dialog):
    """"Make a line layer active and select one line feature" and the positions hint are
    not cut off when the dialog opens."""
    from qgis.PyQt.QtWidgets import QLabel, QSizePolicy

    dlg = make_dialog()
    hints = [label for label in dlg.placement.findChildren(QLabel)
             if label.sizePolicy().horizontalPolicy() == QSizePolicy.Policy.Ignored
             and label.isVisibleTo(dlg) and label.text()]
    assert len(hints) >= 2
    for label in hints:
        assert label.width() >= label.fontMetrics().horizontalAdvance(label.text()), \
            label.text()
