"""The placement widget ("Where the Line Runs"): six sources, the positions file's roles,
the guessed spacing and the map overlay. Driven programmatically (offscreen)."""
from pathlib import Path

import numpy as np
import pytest

WILD = Path(__file__).resolve().parent.parent / "fixtures" / "wild"


@pytest.fixture
def make_widget(qgis_app, fake_iface, project_store):
    from geophysics_workbench.ui.placement_widget import PlacementWidget

    st, prj = project_store
    made = []

    def make(**kw):
        w = PlacementWidget(fake_iface, st, prj, **kw)
        w.show()
        qgis_app.processEvents()
        made.append(w)
        return w

    yield make
    for w in made:
        w.close()
        w.deleteLater()
    qgis_app.processEvents()


def _radio(w, name):
    from qgis.PyQt.QtWidgets import QRadioButton
    return w.findChild(QRadioButton, f"source_{name}")


def _bands(fake_iface):
    from qgis.gui import QgsRubberBand
    return [i for i in fake_iface.mapCanvas().scene().items() if isinstance(i, QgsRubberBand)]


def test_existing_profile_is_preselected_and_collapsed(qgis_app, fake_iface, project_store,
                                                       make_widget):
    from qgis.PyQt.QtWidgets import QPushButton

    from geophysics_workbench.core.model import profile_from_polyline

    st, _prj = project_store
    p = profile_from_polyline("L1", st.crs_authid, np.array([[0.0, 0.0], [50.0, 0.0]]))
    st.save_profile(p)
    w = make_widget()
    w.set_current_profile(p.id)
    qgis_app.processEvents()
    assert w.title() == "Where the Line Runs"
    assert _radio(w, "existing").isChecked()
    assert w.placement().profile_id == p.id
    assert not _radio(w, "line").isVisible()              # collapsed to one line
    other = w.findChild(QPushButton, "other_button")
    assert other.isVisible() and other.text() == "Other…"
    other.click()
    qgis_app.processEvents()
    assert _radio(w, "line").isVisible() and not other.isVisible()
    assert _radio(w, "file") is None                      # the file's own coordinates: not allowed


def test_selected_line_feature_gives_the_line(qgis_app, fake_iface, project_store, make_widget):
    # a memory line layer in EPSG:4326 with one selected feature: placement().line_xy is in
    # the store CRS
    from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

    layer = QgsVectorLayer("LineString?crs=EPSG:4326", "survey_lines", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromWkt("LineString (9.8501 52.7501, 9.8531 52.7511)"))
    layer.dataProvider().addFeatures([f])
    layer.selectAll()
    fake_iface.setActiveLayer(layer)
    try:
        w = make_widget()
        w.select_source("line")
        p = w.placement()
        assert p.profile_id is None and p.positions is None
        assert p.line_xy.shape == (2, 2)
        assert 500_000 < p.line_xy[0, 0] < 600_000 and 5_800_000 < p.line_xy[0, 1] < 5_900_000
        assert "“survey_lines”: 1 feature selected" in w.line_info.text()
        assert w.line_info.text().endswith(" m")
    finally:
        fake_iface.setActiveLayer(None)


def test_positions_file_sparse(qgis_app, fake_iface, project_store, make_widget):
    from qgis.PyQt.QtWidgets import QLineEdit

    w = make_widget()
    w.set_positions_file(WILD / "positions_sparse.csv")
    qgis_app.processEvents()
    p = w.placement()
    assert p.positions.numbers.tolist() == [1, 5, 10, 16, 20] and p.positions.inline is None
    assert np.allclose(p.positions.xyz[:, 2], [57.2, 57.8, 58.3, 58.9, 58.6])
    assert w.findChild(QLineEdit, "spacing_edit").isVisible()


def test_guessed_spacing_is_not_returned_as_stated(qgis_app, fake_iface, project_store,
                                                   make_widget):
    from qgis.PyQt.QtWidgets import QLineEdit

    w = make_widget()
    w.set_positions_file(WILD / "positions_sparse.csv")
    w.set_guessed_spacing(2.5)
    edit = w.findChild(QLineEdit, "spacing_edit")
    assert edit.text() == "" and edit.placeholderText() == "2.5 (guessed)"
    assert w.spacing_is_guess() and w.placement().spacing is None
    d, s, labels = w.known_points()                       # the guess still gives known points
    assert labels == ["1", "5", "10", "16", "20"]
    assert np.allclose(d, [0.0, 10.0, 22.5, 37.5, 47.5])
    assert s[0] == pytest.approx(0.0) and np.all(np.diff(s) > 0)


def test_typed_spacing_is_returned(qgis_app, fake_iface, project_store, make_widget):
    from qgis.PyQt.QtWidgets import QLineEdit

    w = make_widget()
    w.set_positions_file(WILD / "positions_sparse.csv")
    w.set_guessed_spacing(2.5)
    w.findChild(QLineEdit, "spacing_edit").setText("2.5")    # equal to the guess: still typed
    assert not w.spacing_is_guess() and w.placement().spacing == 2.5
    w.findChild(QLineEdit, "spacing_edit").setText("x")
    with pytest.raises(ValueError, match="spacing"):
        w.placement()


def test_text_column_cannot_be_a_coordinate(qgis_app, fake_iface, project_store, make_widget):
    # the remark column is not offered
    from qgis.PyQt.QtWidgets import QComboBox

    w = make_widget()
    w.set_positions_file(WILD / "positions_sparse.csv")
    for role in ("easting", "northing", "elevation", "number", "inline"):
        combo = w.findChild(QComboBox, f"role_{role}")
        assert combo.findData(4) == -1, role
        assert combo.findText("remark") == -1, role
    assert w.findChild(QComboBox, "role_easting").currentData() == 1


def test_degrees_preselect_wgs84_and_reproject(qgis_app, fake_iface, project_store, tmp_path,
                                               make_widget):
    from qgis.gui import QgsProjectionSelectionWidget

    csv = tmp_path / "gps.csv"
    csv.write_text("nr,x,y,z\n1,9.8501,52.7501,57.2\n2,9.8502,52.7502,57.8\n"
                   "3,9.8503,52.7503,58.3\n", encoding="utf-8")
    w = make_widget()
    w.set_positions_file(csv)
    crs = w.findChild(QgsProjectionSelectionWidget, "role_crs")
    assert crs.crs().authid() == "EPSG:4326"
    xyz = w.placement().positions.xyz
    assert np.all((500_000 < xyz[:, 0]) & (xyz[:, 0] < 600_000))
    assert np.all((5_800_000 < xyz[:, 1]) & (xyz[:, 1] < 5_900_000))
    assert np.allclose(xyz[:, 2], [57.2, 57.8, 58.3])
    st, _prj = project_store
    from qgis.core import QgsCoordinateReferenceSystem
    crs.setCrs(QgsCoordinateReferenceSystem(st.crs_authid))   # degrees taken as metres
    with pytest.raises(ValueError, match="degrees"):
        w.placement()


def test_point_layer_source(qgis_app, fake_iface, project_store, make_widget):
    from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsVectorLayer
    from qgis.PyQt.QtCore import QMetaType

    layer = QgsVectorLayer("Point?crs=EPSG:25832", "gps points", "memory")
    layer.dataProvider().addAttributes([QgsField("nr", QMetaType.Type.Int),
                                        QgsField("dist", QMetaType.Type.Double),
                                        QgsField("h", QMetaType.Type.Double)])
    layer.updateFields()
    feats = []
    for nr, x, h in ((3, 1020.0, 51.0), (1, 1000.0, 50.0), (2, 1010.0, 50.5)):
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, 2000.0)))
        f.setAttributes([nr, (nr - 1) * 10.0, h])
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    w = make_widget()
    w.set_point_layer(layer, number_field="nr", inline_field="dist", elevation_field="h",
                      selected_only=False)
    assert _radio(w, "layer").isChecked()
    p = w.placement()
    assert sorted(p.positions.numbers.tolist()) == [1, 2, 3]
    by_number = dict(zip(p.positions.numbers.tolist(), p.positions.xyz.tolist()))
    assert by_number[1] == [1000.0, 2000.0, 50.0]
    assert sorted(p.positions.inline.tolist()) == [0.0, 10.0, 20.0]
    d, s, labels = w.known_points()
    assert np.allclose(sorted(d), [0, 10, 20]) and np.allclose(sorted(s), [0, 10, 20])
    w.set_point_layer(layer, number_field="nr", selected_only=True)      # nothing selected
    with pytest.raises(ValueError, match="Select"):
        w.placement()


def test_overlay_shows_and_clears(qgis_app, fake_iface, project_store, make_widget):
    w = make_widget()
    w.set_positions_file(WILD / "positions_sparse.csv")
    qgis_app.processEvents()
    bands = _bands(fake_iface)
    assert len(bands) == 2 and all(b.numberOfVertices() > 0 for b in bands)
    colour = fake_iface.mapCanvas().selectionColor()
    assert all(b.strokeColor().rgb() == colour.rgb() for b in bands)
    w.clear_overlay()
    assert _bands(fake_iface) == []
    w.set_points(1000.0, 2000.0, 1000.0, 2100.0)               # a new line: shown again
    assert len(_bands(fake_iface)) == 2
    w.hide()                                                   # dialog closed: gone
    assert _bands(fake_iface) == []


def test_incomplete_placement_says_what_is_missing(qgis_app, fake_iface, project_store,
                                                   make_widget):
    fake_iface.setActiveLayer(None)
    w = make_widget(allow_file_coordinates=True)
    w.select_source("line")
    with pytest.raises(ValueError, match="Select exactly one line feature"):
        w.placement()
    w.select_source("positions")
    with pytest.raises(ValueError, match="Choose a positions file"):
        w.placement()
    w.select_source("points")
    with pytest.raises(ValueError, match="Start and end point must be different"):
        w.placement()
    w.select_source("file")
    with pytest.raises(ValueError, match="no map coordinates"):
        w.placement()
    w.set_file_line(np.array([[0.0, 0.0], [30.0, 40.0], [60.0, 40.0]]), bends=1)
    assert np.allclose(w.placement().line_xy, [[0, 0], [30, 40], [60, 40]])
    assert w.known_points() is None


def test_distance_zero_and_offset(qgis_app, fake_iface, project_store, make_widget):
    from qgis.PyQt.QtWidgets import QComboBox

    w = make_widget()
    combo = w.findChild(QComboBox, "zero_combo")
    assert not combo.isVisible()
    w.set_needs_distance(True)
    w.set_points(1000.0, 2000.0, 1000.0, 2100.0)
    qgis_app.processEvents()
    assert combo.isVisible()
    assert [combo.itemData(i) for i in range(combo.count())] == ["start", "end"]
    w.set_positions_file(WILD / "positions_sparse.csv")     # has station 1
    assert [combo.itemData(i) for i in range(combo.count())] == ["start", "end", "station1"]
    combo.setCurrentIndex(2)
    w.offset_spin.setValue(-2.5)
    p = w.placement()
    assert (p.zero, p.offset) == ("station1", -2.5)


def test_table_options_box_and_preview(qgis_app):
    from geophysics_workbench.readers.texttable import TableOptions, read_table
    from geophysics_workbench.ui.table_widgets import PreviewTable, TableOptionsBox

    box = TableOptionsBox()
    seen = []
    box.changed.connect(lambda: seen.append(box.options()))
    assert box.options() == TableOptions()
    assert not box.decimal_check.isEnabled()                   # Detect decides by itself
    box.set_options(TableOptions(delimiter="semicolon", skip=2, header=False,
                                 decimal_comma=True))
    assert box.options() == TableOptions("semicolon", 2, False, True)
    assert box.decimal_check.isEnabled() and seen == []        # set_options is silent
    box.skip_spin.setValue(3)
    assert seen[-1].skip == 3

    table = read_table(WILD / "positions_sparse.csv")
    preview = PreviewTable()
    preview.show(table, {0: "Number", 1: "Easting"}, max_rows=3)
    assert preview.rowCount() == 3 and preview.columnCount() == 5
    assert preview.horizontalHeaderItem(0).text() == "nr\nNumber"
    assert preview.horizontalHeaderItem(4).text() == "remark"
    assert preview.item(0, 1).text() == "437700.00"
    assert preview.verticalHeaderItem(0).text() == "2"          # the file's line number


def test_workbench_layers_are_not_offered_as_point_layers(qgis_app, fake_iface, project_store,
                                                          make_widget):
    from geophysics_workbench.section.crossing_lines import own_layer_ids

    st, prj = project_store
    own = own_layer_ids(st, prj)
    assert own                                          # the store's stations layer is there
    w = make_widget()
    offered = {w.layer_combo.layer(i).id() for i in range(w.layer_combo.count())
               if w.layer_combo.layer(i) is not None}
    assert not offered & own


def test_rows_without_coordinates_are_skipped(qgis_app, fake_iface, project_store, tmp_path,
                                              make_widget):
    from qgis.core import QgsProject

    from geophysics_workbench.core.roles import PositionColumns
    from geophysics_workbench.readers.texttable import read_table
    from geophysics_workbench.ui.positions_source import positions_from_table

    csv = tmp_path / "gaps.csv"
    csv.write_text("nr,east,north\n1,1000,2000\n2,1010,\n3,1020,2000\n4,1030,2000\n",
                   encoding="utf-8")
    positions, skipped = positions_from_table(
        read_table(csv), PositionColumns(easting=1, northing=2, number=0), "EPSG:25832",
        QgsProject())
    assert skipped == 1 and positions.numbers.tolist() == [1, 3, 4]
    assert np.isnan(positions.xyz[:, 2]).all() and positions.inline is None
    w = make_widget()
    w.set_positions_file(csv)
    assert w.positions_status.text() == ("3 positions, line 30.0 m; 1 row without coordinates "
                                         "skipped")


def test_hig_rules_in_the_group(qgis_app, fake_iface, project_store, make_widget):
    # the group and everything in it follow the HIG rules (title-case titles and buttons,
    # sentence-case labels, no colons, "…")
    from tests.ui.test_hig_strings import collect, problems

    w = make_widget(allow_file_coordinates=True)
    w.set_positions_file(WILD / "positions_sparse.csv")
    w.set_needs_distance(True)
    # (tool buttons inside QGIS's own widgets — file, CRS, clear buttons — are QGIS's)
    entries = [e for e in collect(w) if e[0] != "tool"]
    assert not problems(entries, "Placement")


def test_wrong_crs_for_a_positions_file_says_so(qgis_app, fake_iface, project_store,
                                                make_widget):
    # metres declared as EPSG:4326: the reprojection fails with a message, not a traceback
    from qgis.core import QgsCoordinateReferenceSystem
    from qgis.gui import QgsProjectionSelectionWidget

    w = make_widget()
    w.set_positions_file(WILD / "positions_sparse.csv")
    crs = w.findChild(QgsProjectionSelectionWidget, "role_crs")
    crs.setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    assert "CRS" in w.positions_status.text()
    with pytest.raises(ValueError, match="CRS"):
        w.placement()
    assert w.known_points() is None


def test_wrong_crs_for_a_line_layer_says_so(qgis_app, fake_iface, project_store, make_widget):
    from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

    layer = QgsVectorLayer("LineString?crs=EPSG:4326", "utm_as_degrees", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromWkt("LineString (437700 5850700, 437780 5850750)"))
    layer.dataProvider().addFeatures([f])
    layer.selectAll()
    fake_iface.setActiveLayer(layer)
    try:
        w = make_widget()
        w.select_source("line")
        assert "CRS" in w.line_info.text()
        with pytest.raises(ValueError, match="CRS"):
            w.placement()
    finally:
        fake_iface.setActiveLayer(None)


def _canvas_in_store_crs(fake_iface):
    from qgis.core import QgsCoordinateReferenceSystem
    from qgis.gui import QgsMapToolPan

    canvas = fake_iface.mapCanvas()
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
    pan = QgsMapToolPan(canvas)
    canvas.setMapTool(pan)
    return canvas, pan


def _click(canvas, x, y):
    from qgis.core import QgsPointXY
    from qgis.PyQt.QtCore import Qt

    canvas.mapTool().canvasClicked.emit(QgsPointXY(x, y), Qt.MouseButton.LeftButton)


def test_pick_two_clicks_sets_the_points(qgis_app, fake_iface, project_store, make_widget):
    canvas, pan = _canvas_in_store_crs(fake_iface)
    w = make_widget()
    w.select_source("line")
    w.start_pick()
    assert not w.isVisible() and canvas.mapTool() is not pan
    _click(canvas, 1000.0, 2000.0)
    assert not w.isVisible()                          # waits for the end point
    _click(canvas, 1000.0, 2100.0)
    qgis_app.processEvents()
    assert w.isVisible() and canvas.mapTool() is pan
    assert [b.value() for b in (w.x1, w.y1, w.x2, w.y2)] == [1000.0, 2000.0, 1000.0, 2100.0]
    assert _radio(w, "points").isChecked()
    assert np.allclose(w.placement().line_xy, [[1000, 2000], [1000, 2100]])


def test_pick_cancelled_by_another_tool_restores_the_dialog(qgis_app, fake_iface,
                                                            project_store, make_widget):
    from qgis.gui import QgsMapToolZoom

    canvas, _pan = _canvas_in_store_crs(fake_iface)
    w = make_widget()
    w.start_pick()
    _click(canvas, 1000.0, 2000.0)
    zoom = QgsMapToolZoom(canvas, False)
    canvas.setMapTool(zoom)                           # the user takes another tool
    qgis_app.processEvents()
    assert w.isVisible() and canvas.mapTool() is zoom
    assert [b.value() for b in (w.x1, w.y1, w.x2, w.y2)] == [0.0, 0.0, 0.0, 0.0]


def test_pick_tool_released_when_the_widget_is_destroyed(qgis_app, fake_iface, project_store):
    from qgis.PyQt import sip

    from geophysics_workbench.ui.placement_widget import PlacementWidget

    st, prj = project_store
    canvas, pan = _canvas_in_store_crs(fake_iface)
    w = PlacementWidget(fake_iface, st, prj)
    w.show()
    w.start_pick()
    assert canvas.mapTool() is not pan
    sip.delete(w)                                     # the dialog goes away mid-pick
    qgis_app.processEvents()
    assert canvas.mapTool() is pan


def test_unknown_profile_is_not_replaced_by_another(qgis_app, fake_iface, project_store,
                                                    make_widget):
    from qgis.PyQt.QtWidgets import QPushButton

    from geophysics_workbench.core.model import profile_from_polyline

    st, _prj = project_store
    for name in ("L1", "L2"):
        st.save_profile(profile_from_polyline(name, st.crs_authid,
                                              np.array([[0.0, 0.0], [50.0, 0.0]])))
    w = make_widget()
    w.set_current_profile("no-such-profile")
    qgis_app.processEvents()
    assert not w.findChild(QPushButton, "other_button").isVisible()     # not collapsed
    assert _radio(w, "line").isVisible()
    assert w.profile_combo.currentIndex() == -1
    with pytest.raises(ValueError, match="Choose a profile"):
        w.placement()


def test_pick_outside_the_canvas_crs_is_refused_with_a_message(qgis_app, fake_iface,
                                                               project_store, make_widget):
    from qgis.core import QgsCoordinateReferenceSystem

    canvas, pan = _canvas_in_store_crs(fake_iface)
    canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
    fake_iface.messageBar().clearWidgets()
    w = make_widget()
    w.start_pick()
    _click(canvas, 437700.0, 5850700.0)              # metres on a degree canvas
    assert "CRS" in fake_iface.messageBar().currentItem().text()
    assert canvas.mapTool() is not pan and not w.isVisible()     # still picking
    w.cancel_pick()
    assert canvas.mapTool() is pan
