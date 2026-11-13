"""The free-text reader: any text table read with the columns the user assigned."""
from pathlib import Path

import numpy as np
import pytest

from geophysics_workbench import readers
from geophysics_workbench.core.roles import ModelColumns
from geophysics_workbench.readers.text_columns import map_points
from geophysics_workbench.readers.texttable import TableOptions

WILD = Path(__file__).resolve().parent.parent / "fixtures" / "wild"
NO_HEADER = TableOptions(header=False).to_dict()
DEPTH_COLS = ModelColumns(distance=0, vertical=2, vertical_kind="depth", value=3)
MAP_COLS = ModelColumns(position="map", easting=0, northing=1, vertical=2,
                        vertical_kind="depth", value=3).to_dict()


def _x_zero_rows() -> np.ndarray:
    return np.loadtxt(WILD / "x_zero_depth_rho.txt")


def _write(path, rows) -> str:
    np.savetxt(path, rows, fmt="%.6g")
    return path


def _read(path, cols=DEPTH_COLS, table=NO_HEADER, **options):
    return readers.read(path, reader="text_columns", table=table,
                        columns=cols.to_dict(), **options)


def test_distance_depth_model():
    r = readers.read(WILD / "x_zero_depth_rho.txt", reader="text_columns",
                     table=TableOptions(header=False).to_dict(),
                     columns=ModelColumns(distance=0, vertical=2, vertical_kind="depth",
                                          value=3).to_dict())
    assert r.z_kind == "depth" and r.provenance["reconstruction"] == "rows"
    assert r.mesh.bounds()[2] == 0.0                     # top edge of a depth model on the surface
    p = r.provenance
    assert (p["reader"], p["source_name"], p["position"]) == (
        "text_columns", "x_zero_depth_rho.txt", "distance")
    assert (p["n_rows"], p["n_skipped"], p["first_skipped_line"]) == (80, 0, None)
    assert "max_offset" not in p and "n_beyond" not in p


def test_negative_depths_use_their_magnitude(tmp_path):
    rows = _x_zero_rows()
    rows[:, 2] = -rows[:, 2]
    flipped = _read(_write(tmp_path / "neg.txt", rows)).mesh
    mesh = _read(WILD / "x_zero_depth_rho.txt").mesh
    np.testing.assert_array_equal(flipped.vertices, mesh.vertices)
    np.testing.assert_array_equal(flipped.cells, mesh.cells)
    np.testing.assert_array_equal(flipped.values, mesh.values)


def test_mixed_sign_depth_is_an_error(tmp_path):
    rows = _x_zero_rows()
    rows[:3, 2] = -rows[:3, 2]
    with pytest.raises(ValueError, match="Elevation or Local height"):
        _read(_write(tmp_path / "mixed.txt", rows))


def test_log10_values_are_raised(tmp_path):
    rows = _x_zero_rows()
    logs = rows.copy()
    logs[:, 3] = np.log10(rows[:, 3])
    cols = ModelColumns(distance=0, vertical=2, vertical_kind="depth", value=3, log10=True)
    r = _read(_write(tmp_path / "log.txt", logs), cols)
    np.testing.assert_allclose(r.mesh.values, 10 ** np.loadtxt(tmp_path / "log.txt")[:, 3])
    np.testing.assert_allclose(r.mesh.values, rows[:, 3], rtol=1e-4)   # 6 digits in the file


def test_other_quantity_skips_the_positivity_check(tmp_path):
    rows = _x_zero_rows()
    rows[5, 3] = -4.5
    cols = ModelColumns(distance=0, vertical=2, vertical_kind="depth", value=3,
                        quantity="chargeability", unit="mV/V")
    r = _read(_write(tmp_path / "ip.txt", rows), cols)
    assert (r.mesh.quantity, r.mesh.unit) == ("chargeability", "mV/V")
    assert r.mesh.values.min() == pytest.approx(-4.5)


def test_resistivity_keeps_the_positivity_check(tmp_path):
    rows = _x_zero_rows()
    rows[5, 3] = -4.5
    with pytest.raises(ValueError, match="zero or negative"):
        _read(_write(tmp_path / "neg_rho.txt", rows))


def test_local_height_is_reported():
    cols = ModelColumns(distance=0, vertical=2, vertical_kind="local", value=3)
    r = _read(WILD / "x_zero_depth_rho.txt", cols)
    assert r.z_kind == "local"


def test_z_kind_option_wins_over_the_columns():
    r = _read(WILD / "x_zero_depth_rho.txt", z_kind="elevation")
    assert r.z_kind == "elevation"


def test_never_detected():
    assert "text_columns" not in readers.detect(WILD / "x_zero_depth_rho.txt")
    assert readers.FALLBACK == "text_columns" and readers.names()[-1] == "text_columns"


def test_missing_column_names_it(tmp_path):
    _write(tmp_path / "short.txt", _x_zero_rows()[:, :3])
    with pytest.raises(ValueError, match=r"short\.txt: column 4 is not in the file any more"):
        _read(tmp_path / "short.txt")


def test_stored_options_that_no_longer_load_name_the_file():
    with pytest.raises(ValueError, match="x_zero_depth_rho.txt"):
        readers.read(WILD / "x_zero_depth_rho.txt", reader="text_columns",
                     table={"delimiter": "pipe"}, columns=DEPTH_COLS.to_dict())
    with pytest.raises(ValueError, match="x_zero_depth_rho.txt"):
        readers.read(WILD / "x_zero_depth_rho.txt", reader="text_columns", table=NO_HEADER,
                     columns={"position": "polar"})


def test_skipped_rows_are_counted():
    cols = ModelColumns(distance=0, vertical=1, vertical_kind="elevation", value=2)
    r = readers.read(WILD / "dist_y_rho_junk.txt", reader="text_columns", table={},
                     columns=cols.to_dict())
    assert r.provenance["n_skipped"] == 1 and r.provenance["first_skipped_line"] == 9


def test_map_file_needs_a_line():
    with pytest.raises(ValueError, match="needs a profile"):
        readers.read(WILD / "east_north_depth_rho.csv", reader="text_columns", table={},
                     columns=MAP_COLS)


def test_map_file_uses_the_callable():
    r = readers.read(WILD / "east_north_depth_rho.csv", reader="text_columns", table={},
                     columns=MAP_COLS,
                     xy_to_distance=lambda e, n: (e - e.min(), np.zeros_like(e)))
    # the first centre is at chainage 0; its cell reaches half the 4.33 m step before it
    assert r.mesh.bounds()[0] == pytest.approx(0.0, abs=2.5) and r.provenance["max_offset"] == 0.0
    assert r.provenance["position"] == "map" and r.provenance["n_beyond"] == 0


def test_map_file_reports_offset_and_clamped_cells():
    def project(e, n):
        return e - e.min(), np.where(e > e.min(), 1.5, -3.0), e == e.max()
    r = readers.read(WILD / "east_north_depth_rho.csv", reader="text_columns", table={},
                     columns=MAP_COLS, xy_to_distance=project)
    assert r.provenance["max_offset"] == 3.0 and r.provenance["n_beyond"] == 3


def test_map_points_are_the_usable_rows():
    xy = map_points(WILD / "east_north_depth_rho.csv", {}, MAP_COLS)
    assert xy.shape == (60, 2)
    assert xy[0].tolist() == [437702.17, 5850701.25]


def test_max_rows_reads_only_the_first_rows():
    # the Add Data preview reads a sample; the whole file is read when it is added
    cols = ModelColumns(distance=0, vertical=1, vertical_kind="elevation", value=2)
    r = readers.read(WILD / "dist_y_rho_junk.txt", reader="text_columns", table={},
                     columns=cols.to_dict(), max_rows=25)
    assert r.provenance["n_rows"] + r.provenance["n_skipped"] == 25
    assert len(map_points(WILD / "east_north_depth_rho.csv", {}, MAP_COLS, max_rows=6)) == 6
