"""Electrode numbers from point names in "Where the Line Runs": the Number choice takes a text
column or field, the last/first choice, the row list with its corrections. Offscreen."""
from pathlib import Path

import numpy as np
import pytest

WILD = Path(__file__).resolve().parent.parent / "fixtures" / "wild"
NAMES = WILD / "positions_names.csv"
TWICE = "measured twice, later row used"


@pytest.fixture
def make_widget(qgis_app, fake_iface, project_store):
    from groundwork_geophysics.ui.placement_widget import PlacementWidget

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


def _find(w, cls, name):
    from qgis.PyQt import QtWidgets
    from qgis.gui import QgsCollapsibleGroupBox
    kinds = {"radio": QtWidgets.QRadioButton, "table": QtWidgets.QTableWidget,
             "box": QgsCollapsibleGroupBox, "combo": QtWidgets.QComboBox}
    return w.findChild(kinds[cls], name)


def _column(table, c):
    return [table.item(r, c).text() for r in range(table.rowCount())]


def _edit(w, name_row, text, occurrence=0):
    """Type ``text`` into the Number cell of the ``occurrence``-th row named ``name_row``."""
    table = _find(w, "table", "names_table")
    rows = [r for r in range(table.rowCount()) if table.item(r, 0).text() == name_row]
    table.item(rows[occurrence], 1).setText(text)


def test_name_column_reads_numbers(qgis_app, make_widget):
    w = make_widget()
    w.set_positions_file(NAMES)
    qgis_app.processEvents()
    p = w.placement().positions
    assert p.numbers.tolist() == [1, 2, 3, 4, 5]
    assert p.names == ["ERT03_01", "ERT03_02", "ERT03_03", "ERT03_04", "ERT03_05"]
    np.testing.assert_allclose(p.xyz[3, :2], [500006.1, 5600000.1])     # the later ERT03_04
    assert _find(w, "radio", "names_last").isChecked()
    assert _find(w, "combo", "role_number").currentText() == "Punkt (names)"


def test_name_list_shows_problem_rows_first(qgis_app, make_widget):
    w = make_widget()
    w.set_positions_file(NAMES)
    box = _find(w, "box", "names_box")
    assert box.isVisible() and box.isCollapsed()
    assert box.title() == "Electrodes from Names (8 rows, 3 to check)"
    table = _find(w, "table", "names_table")
    assert _column(table, 0)[:3] == ["Base", "GCP3", "ERT03_04"]
    assert _column(table, 2)[:3] == ["not an electrode", TWICE, TWICE]
    assert _column(table, 1)[:3] == ["", "3", "4"]
    assert table.rowCount() == 8


def test_correction_in_the_table(qgis_app, make_widget):
    w = make_widget()
    w.set_positions_file(NAMES)
    _edit(w, "GCP3", "")
    box = _find(w, "box", "names_box")
    assert box.title() == "Electrodes from Names (8 rows, 2 to check)"
    _edit(w, "ERT03_04", "9")                       # the earlier one (problem rows first)
    p = w.placement().positions
    assert 9 in p.numbers.tolist() and len(p.numbers) == 6
    table = _find(w, "table", "names_table")
    status = dict(zip(_column(table, 1), _column(table, 2)))
    assert status["9"] == "corrected"
    _edit(w, "ERT03_01", "abc")
    assert "1" in _column(table, 1)                 # the cell went back
    assert "Type a whole number, or leave it empty" in w.positions_status.text()


def test_first_number_keeps_corrections(qgis_app, make_widget):
    w = make_widget()
    w.set_positions_file(NAMES)
    _edit(w, "Base", "20")
    _find(w, "radio", "names_first").click()
    qgis_app.processEvents()
    p = w.placement().positions
    assert 20 in p.numbers.tolist()                 # the correction stays
    assert 3 in p.numbers.tolist() and len(p.numbers) == 2   # every ERT03_… reads 3: one wins
    w.set_positions_file(WILD / "positions_sparse.csv")
    w.set_positions_file(NAMES)                     # a new file clears the corrections
    _find(w, "radio", "names_last").click()
    assert 20 not in w.placement().positions.numbers.tolist()


def test_numeric_number_column_hides_the_names_parts(qgis_app, make_widget):
    w = make_widget()
    w.set_positions_file(WILD / "positions_sparse.csv")
    qgis_app.processEvents()
    assert not _find(w, "box", "names_box").isVisible()
    assert not _find(w, "radio", "names_last").isVisible()
    assert w.placement().positions.numbers.tolist() == [1, 5, 10, 16, 20]
    assert w.name_rows() is None


def _layer(values):
    from qgis.core import QgsFeature, QgsField, QgsGeometry, QgsPointXY, QgsVectorLayer
    from qgis.PyQt.QtCore import QMetaType

    layer = QgsVectorLayer("Point?crs=EPSG:25832", "gps names", "memory")
    layer.dataProvider().addAttributes([QgsField("pt", QMetaType.Type.QString)])
    layer.updateFields()
    feats = []
    for i, v in enumerate(values):
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1000.0 + 10 * i, 2000.0)))
        f.setAttributes([v])
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    return layer


def test_point_layer_names_selected_only(qgis_app, make_widget):
    layer = _layer(["E1", "E2", "E2", "E3", "Base"])
    ids = sorted(f.id() for f in layer.getFeatures())
    layer.selectByIds(ids[:3])
    w = make_widget()
    w.set_point_layer(layer, number_field="pt", selected_only=True)
    qgis_app.processEvents()
    assert _find(w, "box", "names_box").isVisible()
    table = _find(w, "table", "names_table")
    assert table.rowCount() == 3 and _column(table, 2).count(TWICE) == 1
    assert w.placement().positions.numbers.tolist() == [1, 2]
    layer.selectByIds(ids)                          # the list follows the selection
    qgis_app.processEvents()
    assert table.rowCount() == 5


def test_too_few_electrodes_from_names(qgis_app, make_widget, tmp_path):
    csv = tmp_path / "few.csv"
    csv.write_text("name,east,north\nBase,1000,2000\nGCP,1010,2000\nE1,1020,2000\n",
                   encoding="utf-8")
    w = make_widget()
    w.set_positions_file(csv)
    with pytest.raises(ValueError) as err:
        w.placement()
    assert str(err.value) and w.positions_status.text() == str(err.value)


def test_fit_labels_use_names(qgis_app, make_widget, tmp_path):
    csv = tmp_path / "known.csv"
    csv.write_text("name,east,north,inline\nA1,1000,2000,0\nA2,1010,2000,10\n"
                   "A3,1020,2001,20\n", encoding="utf-8")
    w = make_widget()
    w.set_positions_file(csv)
    _, _, labels = w.known_points()
    assert labels == ["A1", "A2", "A3"]


def test_reading_the_same_file_again_clears_corrections(qgis_app, make_widget):
    """A cleaned file is often read again under the same name: it starts from the guess."""
    w = make_widget()
    w.set_positions_file(NAMES)
    _edit(w, "Base", "20")
    assert 20 in w.placement().positions.numbers.tolist()
    w.set_positions_file(NAMES)
    assert 20 not in w.placement().positions.numbers.tolist()
