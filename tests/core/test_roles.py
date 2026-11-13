from pathlib import Path

import numpy as np

from geophysics_workbench.core.roles import (
    QUANTITIES, VERTICAL_KINDS, ModelColumns, PositionColumns, guess_model_columns,
    guess_position_columns)
from geophysics_workbench.readers.texttable import (
    TableOptions, TextTable, guess_options, read_table)

WILD = Path(__file__).resolve().parent.parent / "fixtures" / "wild"


def _table(names, rows):
    cells = [[repr(float(v)) for v in row] for row in rows]
    return TextTable(list(names), cells, list(range(2, len(cells) + 2)))


def _junk_table():
    return read_table(WILD / "dist_y_rho_junk.txt", guess_options(WILD / "dist_y_rho_junk.txt"))


def test_constant_column_is_never_a_position():        # x, 0, depth, rho
    c = guess_model_columns(read_table(WILD / "x_zero_depth_rho.txt", TableOptions(header=False)))
    assert (c.position, c.distance, c.vertical, c.value) == ("distance", 0, 2, 3)


def test_projected_coordinates_suggest_map():           # easting, northing, depth, rho
    c = guess_model_columns(read_table(WILD / "east_north_depth_rho.csv"))
    assert ((c.position, c.easting, c.northing, c.vertical, c.vertical_kind)
            == ("map", 0, 1, 2, "depth"))


def test_distance_named_x_and_depth_named_y():          # X; Y; Rho; Comment
    c = guess_model_columns(_junk_table())
    assert (c.position, c.distance, c.vertical, c.value) == ("distance", 0, 1, 2)


def test_log10_pair_picks_the_linear_column():
    rho = np.array([12.0, 55.0, 130.0, 410.0, 87.0, 23.0])
    rows = np.column_stack([np.arange(6) * 2.5, [0.5, 1.5, 3.0] * 2, np.log10(rho), rho])
    c = guess_model_columns(_table(["x", "z", "log_rho", "rho"], rows))
    assert (c.value, c.log10) == (3, False)


def test_log10_pair_linear_column_wins_when_the_log_column_is_last():
    rho = np.array([12.0, 55.0, 130.0, 410.0, 87.0, 23.0])
    rows = np.column_stack([np.arange(6) * 2.5, [0.5, 1.5, 3.0] * 2, rho, np.log10(rho)])
    c = guess_model_columns(_table(["column 1", "column 2", "column 3", "column 4"], rows))
    assert (c.distance, c.vertical, c.value, c.log10) == (0, 1, 2, False)


def test_degrees_preselect_wgs84():
    lonlat_table = _table(["x", "y", "z"], [[9.8501, 52.7501, 57.2], [9.8503, 52.7502, 57.8],
                                            [9.8506, 52.7504, 58.3]])
    assert guess_position_columns(lonlat_table).crs == "EPSG:4326"
    projected = _table(["x", "y", "z"], [[437700.0, 5850700.0, 57.2], [437717.3, 5850710.0, 57.8]])
    assert guess_position_columns(projected).crs == ""


def test_problems_name_what_is_missing():
    t = _junk_table()
    assert ModelColumns(distance=0, value=2).problems(t) == [
        "Choose the vertical column and what it means"]
    text_distance = ModelColumns(distance=3, vertical=1, vertical_kind="depth", value=2)
    assert "cannot be a text column" in text_distance.problems(t)[0]
    assert ModelColumns(distance=0, vertical=1, vertical_kind="depth", value=2).problems(t) == []
    assert ModelColumns(distance=0, vertical=0, vertical_kind="depth", value=2).problems(t) == [
        "The vertical column cannot also be the distance column"]
    assert PositionColumns(easting=None, northing=1).problems(t) == [
        "Choose the easting and northing columns"]


def test_sparse_positions_roles():
    p = guess_position_columns(read_table(WILD / "positions_sparse.csv"))
    assert (p.number, p.easting, p.northing, p.elevation, p.inline) == (0, 1, 2, 3, None)


def test_columns_round_trip_through_a_dict():
    m = ModelColumns(position="map", easting=0, northing=1, crs="EPSG:25832", vertical=2,
                     vertical_kind="depth", value=3, quantity="", unit="", log10=True)
    assert ModelColumns.from_dict(m.to_dict()) == m
    assert m.used() == [0, 1, 2, 3]
    assert ModelColumns(distance=0, vertical=2, value=3).used() == [0, 2, 3]
    p = PositionColumns(easting=1, northing=2, number=0, inline=4)
    assert PositionColumns.from_dict(p.to_dict()) == p
    assert p.used() == [1, 2, 0, 4]


def test_role_lists():
    assert [v for _, v in VERTICAL_KINDS] == ["elevation", "depth", "local"]
    assert QUANTITIES[0] == ("Resistivity (ohm.m)", "resistivity", "ohm.m")


def test_unit_suffix_is_ignored_in_names():
    # by position alone the first column would be the distance and the last the value
    rows = [[12.0, 0.0, 0.5], [55.0, 2.5, 1.5], [130.0, 5.0, 3.0], [410.0, 7.5, 0.5]]
    c = guess_model_columns(_table(["Rho [ohm.m]", "Distance [m]", "Depth (m)"], rows))
    assert (c.position, c.distance, c.vertical, c.vertical_kind, c.value) == (
        "distance", 1, 2, "depth", 0)


def test_positions_with_units_keep_elevation():
    rows = [[1, 437700.0, 5850700.0, 57.2], [2, 437717.3, 5850710.0, 57.8],
            [3, 437739.0, 5850722.5, 58.3]]
    p = guess_position_columns(_table(["Nr", "Easting [m]", "Northing [m]", "Elevation [m]"],
                                      rows))
    assert (p.number, p.easting, p.northing, p.elevation) == (0, 1, 2, 3)
    q = guess_position_columns(_table(["Nr", "Easting [m]", "Northing (m)", "Elevation [m NN]"],
                                      rows))
    assert (q.number, q.easting, q.northing, q.elevation) == (0, 1, 2, 3)
