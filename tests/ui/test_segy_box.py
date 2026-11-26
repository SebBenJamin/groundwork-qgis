"""The SEG-Y Section group of Add Data (and, with its vertical rows only, of Dataset Info):
how the samples are read, hung and the traces placed. Driven programmatically (offscreen)."""
import pytest

from groundwork_geophysics.readers.segy import SegyInfo

SWISS = {"source": ((2525014.0, 1161279.0), (2522995.0, 1153108.0))}


def info(**kw) -> SegyInfo:
    values = dict(n_traces=3, n_samples=4, step=0.002, first=0.0, endian="big", sample_format=1,
                  text="C 1 CLIENT\nC 2 LINE 7", positions={}, velocity=None, unstacked=False)
    values.update(kw)
    return SegyInfo(**values)


@pytest.fixture
def box(qgis_app):
    from groundwork_geophysics.ui.segy_box import SegyBox
    made = SegyBox()
    yield made
    made.deleteLater()


def test_a_file_without_positions_offers_spacing_only(box):
    box.set_info(info(positions={}))
    assert not box.by_positions.isEnabled() and box.by_spacing.isChecked()
    assert box.by_positions.toolTip() == "The file has no positions that change along the line"
    assert "Enter the trace spacing in metres." in box.problems()


def test_velocity_is_empty_unless_the_file_states_one(box):
    box.set_info(info(velocity=None))
    assert box.velocity_edit.text() == ""
    box.set_info(info(velocity=1500.0))
    assert box.options()["velocity"] == 1500.0


@pytest.mark.parametrize("text", ["", "0", "-3", "abc"])
def test_a_bad_velocity_is_a_problem(box, text):
    box.set_info(info())
    box.velocity_edit.setText(text)
    assert "Enter the velocity in m/s." in box.problems()


def test_depth_hides_the_velocity_and_needs_none(box):
    box.set_info(info())
    box.set_domain("depth")
    assert box.velocity_edit.isHidden() and "velocity" not in " ".join(box.problems())
    assert box.options()["domain"] == "depth" and "velocity" not in box.options()


def test_fixed_height_needs_a_height(box):
    box.set_info(info())
    box.set_zero("datum")
    assert "Enter the height of time zero." in box.problems()


def test_position_fields_show_their_coordinates(box):
    box.set_info(info(positions=SWISS))
    assert "2525014" in box.field_combo.itemText(0) and box.field_combo.itemData(0) == "source"


def test_options_round_trip(box):
    o = {"position": "spacing", "spacing": 2.0, "domain": "time", "velocity": 1450.0,
         "zero": "ground"}
    box.set_info(info())
    box.set_options(o)
    assert box.options() == o


# -- added --------------------------------------------------------------------------------
def test_positions_in_the_file_are_chosen_with_their_crs(box):
    from qgis.core import QgsCoordinateReferenceSystem
    box.set_default_crs(QgsCoordinateReferenceSystem("EPSG:2056"))
    box.set_info(info(positions=SWISS, velocity=3000.0))
    assert box.by_positions.isChecked()
    o = box.options()
    assert o["position"] == "map" and o["xy_field"] == "source" and o["crs"] == "EPSG:2056"
    assert "spacing" not in o and box.problems() == []


def test_degrees_preset_wgs84(box):
    box.set_info(info(positions={"cdp": ((7.1, 50.2), (7.2, 50.3))}, geographic=True))
    assert box.options()["crs"] == "EPSG:4326"


def test_fixed_height_and_replacement_velocity_only_when_they_apply(box):
    box.set_info(info(velocity=2000.0))
    box.by_spacing.setChecked(True)
    box.spacing_edit.setText("5")
    assert "datum" not in box.options() and "replacement_velocity" not in box.options()
    box.set_zero("datum")
    box.datum_edit.setText("700,5")                     # a decimal comma
    assert box.options()["datum"] == 700.5 and "replacement_velocity" not in box.options()
    box.set_zero("datum_ground")
    assert "Enter the replacement velocity in m/s." in box.problems()
    box.replacement_edit.setText("3200")
    o = box.options()
    assert o["zero"] == "datum_ground" and o["replacement_velocity"] == 3200.0
    assert box.problems() == []


def test_corrected_to_the_ground_is_not_offered_for_depth(box):
    box.set_info(info())
    box.set_zero("datum_ground")
    box.set_domain("depth")
    assert box.zero() == "datum"
    item = box.zero_combo.model().item(box.zero_combo.findData("datum_ground"))
    assert not item.isEnabled() and item.toolTip()


def test_the_sample_step_is_kept_unless_changed(box):
    box.set_info(info(velocity=1500.0))
    assert box.step_edit.text() == "2" and "sample_step" not in box.options()
    box.step_edit.setText("4")
    assert box.options()["sample_step"] == pytest.approx(0.004)
    assert box.step_note.text() == "The file says 2 ms."
    box.step_edit.setText("0")
    assert "The sample step must be greater than 0." in box.problems()


def test_depth_says_to_check_the_step(box):
    box.set_info(info())
    box.set_domain("depth")
    assert box.step_label.text() == "Sample step (m)"
    assert box.step_note.text() == "Check the sample step: the file does not say it is in metres."
    assert "sample_step" not in box.options()
    box.step_edit.setText("0,5")
    assert box.options()["sample_step"] == 0.5


def test_the_velocity_function_round_trips(box):
    o = {"position": "spacing", "spacing": 1.0, "domain": "time",
         "velocity_table": [[0.0, 1800.0], [0.5, 2400.0], [2.0, 3400.0]],
         "velocity_kind": "interval", "zero": "ground"}
    box.set_info(info())
    box.set_options(o)
    assert box.velocity_table.rowCount() == 3
    assert box.velocity_table.item(1, 0).text() == "500"
    assert box.options() == o


def test_a_pasted_block_fills_the_rows(box):
    box.set_info(info())
    box.by_function.setChecked(True)
    box.paste_rows("0;1800\n500;2400\n2000;3400")
    assert box.velocity_table.rowCount() == 3
    assert box.options()["velocity_table"] == [[0.0, 1800.0], [0.5, 2400.0], [2.0, 3400.0]]
    box.paste_rows("2500\t3600,5")                      # tab separated, decimal comma
    assert box.options()["velocity_table"][-1] == [2.5, 3600.5]


@pytest.mark.parametrize("rows, text", [
    ([("0", "1800")], "Enter at least two rows of time and velocity."),
    ([("0", "1800"), ("0", "2400")], "The times must increase."),
    ([("0", "1800"), ("500", "0")], "The velocities must be greater than 0."),
    ([("0", "3000"), ("4", "100")],
     "The velocity function gives depths that do not increase with time."),
])
def test_each_velocity_function_problem(box, rows, text):
    box.set_info(info())
    box.by_function.setChecked(True)
    box.velocity_table.setRowCount(0)
    box.paste_rows("\n".join(";".join(r) for r in rows))
    assert text in box.problems()


def test_a_coordinate_file_preselects_its_columns(box, tmp_path):
    table = tmp_path / "line7.csv"
    table.write_text("CDP,X,Y\n1,500000,5700000\n3,500010,5700000\n")
    segy = tmp_path / "line7.sgy"
    from qgis.core import QgsCoordinateReferenceSystem
    box.set_default_crs(QgsCoordinateReferenceSystem("EPSG:25832"))
    box.set_info(info(), str(segy))
    box.by_table.setChecked(True)
    box.set_positions_file(str(table))
    assert (box.number_combo.currentText(), box.easting_combo.currentText(),
            box.northing_combo.currentText()) == ("CDP", "X", "Y")
    o = box.options()
    assert o["position"] == "table" and o["positions_file"] == "line7.csv"
    assert o["positions_columns"] == {"number": 0, "easting": 1, "northing": 2}
    assert box.table_note.text() == "2 of 3 traces listed; the rest are placed between them."
    assert box.problems() == ["Enter the velocity in m/s."]


def test_without_a_coordinate_file_it_is_a_problem(box):
    box.set_info(info(velocity=1500.0))
    box.by_table.setChecked(True)
    assert "Choose the coordinate file with the trace positions." in box.problems()


def test_vertical_only_shows_no_placement(qgis_app):
    from groundwork_geophysics.ui.segy_box import SegyBox
    box = SegyBox(vertical_only=True)
    box.set_info(info(velocity=1500.0))
    assert box.by_spacing.isHidden() and box.text_button.isHidden()
    assert box.options() == {"domain": "time", "velocity": 1500.0, "zero": "ground"}
    assert box.problems() == []


def test_the_text_header_opens_read_only(box):
    box.set_info(info())
    box.text_button.click()
    view = box.text_dialog.findChild(__import__("qgis.PyQt.QtWidgets", fromlist=["x"])
                                     .QPlainTextEdit)
    assert view.isReadOnly() and view.toPlainText().startswith("C 1 CLIENT")
    box.text_dialog.close()
