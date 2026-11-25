"""The free-text reader: any text table read with the columns the user assigned."""
from pathlib import Path

import numpy as np
import pytest

from groundwork_geophysics import readers
from groundwork_geophysics.core.roles import ModelColumns
from groundwork_geophysics.readers.text_columns import map_points
from groundwork_geophysics.readers.texttable import TableOptions

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


def _with_unplaced_rows(tmp_path) -> Path:
    """The map fixture plus rows whose easting/northing is the -9999 fill (one with a value),
    as exports write the cells past the surveyed line (a real Res2DInv-style CSV)."""
    path = tmp_path / "fill_coords.csv"
    text = (WILD / "east_north_depth_rho.csv").read_text()
    path.write_text(text + "-9999,-9999,0.5,-9999\n-9999,-9999,1.5,120.0\n"
                    "437784.44,-9999,3.0,130.0\n")
    return path


def test_map_points_leave_out_fill_coordinates(tmp_path):
    # a -9999 position is no position: it must not pull the profile line off to (-9999, -9999)
    xy = map_points(_with_unplaced_rows(tmp_path), {}, MAP_COLS)
    assert xy.shape == (60, 2) and (xy > 0).all()


def test_map_file_rows_with_fill_coordinates_are_not_placed(tmp_path):
    seen = []

    def project(e, n):
        seen.append(np.column_stack([e, n]))
        return e - 437702.17, np.zeros_like(e)
    r = readers.read(_with_unplaced_rows(tmp_path), reader="text_columns", table={},
                     columns=MAP_COLS, xy_to_distance=project)
    assert (np.concatenate(seen) > 0).all()            # never asked to place a fill
    lo, hi = r.mesh.bounds()[:2]
    assert lo > -5 and hi < 100                         # the 60 real cells only
    assert r.provenance["n_masked"] >= 2                # the two with a value, counted
    assert r.provenance["n_unplaced"] == 3              # reported on their own


def test_max_rows_reads_only_the_first_rows():
    # the Add Data preview reads a sample; the whole file is read when it is added
    cols = ModelColumns(distance=0, vertical=1, vertical_kind="elevation", value=2)
    r = readers.read(WILD / "dist_y_rho_junk.txt", reader="text_columns", table={},
                     columns=cols.to_dict(), max_rows=25)
    assert r.provenance["n_rows"] + r.provenance["n_skipped"] == 25
    assert len(map_points(WILD / "east_north_depth_rho.csv", {}, MAP_COLS, max_rows=6)) == 6


def test_text_table_with_coverage(tmp_path):
    rows = [[x, z, 500.0 + x + z, 1.0 + x / 10] for z in (100.0, 98.0, 96.0)
            for x in (1.0, 3.0, 5.0, 7.0)]
    p = _write(tmp_path / "vel.txt", rows)
    cols = ModelColumns(distance=0, vertical=1, vertical_kind="elevation", value=2,
                        coverage=3, quantity="p_velocity", unit="m/s")
    r = _read(p, cols)
    assert r.mesh.quantity == "p_velocity" and r.mesh.unit == "m/s"
    assert r.mesh.coverage is not None and len(r.mesh.coverage) == len(r.mesh.values)
    assert np.nanmax(r.mesh.values) == pytest.approx(507.0 + 100.0)
    without = _read(p, ModelColumns(distance=0, vertical=1, vertical_kind="elevation",
                                    value=2, quantity="p_velocity", unit="m/s"))
    assert without.mesh.coverage is None
    assert np.array_equal(without.mesh.values, r.mesh.values)


def test_coverage_column_never_drops_cells(tmp_path):
    """A row with -inf (no ray) or no coverage keeps its cell: the coverage is optional."""
    p = tmp_path / "vel.txt"
    rows = [f"{x} {z} {500 + x + z} {1 + x / 10}" for z in (100, 98, 96) for x in (1, 3, 5, 7)]
    rows[0] = "1 100 601 -inf"
    rows[1] = "3 100 603"                               # no coverage at all
    p.write_text("\n".join(rows) + "\n")
    cols = ModelColumns(distance=0, vertical=1, vertical_kind="elevation", value=2,
                        coverage=3, quantity="p_velocity", unit="m/s")
    r = _read(p, cols)
    assert r.provenance["n_rows"] == 12 and r.provenance["n_skipped"] == 0
    c = r.mesh.coverage
    assert np.isnan(c).sum() == 1                       # the blank one: unknown
    assert np.nanmin(c) < 1.0                           # -inf: below the lowest (1.1)


def test_a_clean_model_file_is_read_without_its_text(tmp_path, monkeypatch):
    # the whole file of a big model is read as numbers alone (the preview still shows text)
    from groundwork_geophysics.readers import text_columns

    def no_text(*_a, **_k):
        raise AssertionError("read as text")
    monkeypatch.setattr(text_columns, "read_table", no_text)
    r = readers.read(WILD / "x_zero_depth_rho.txt", reader="text_columns", table=NO_HEADER,
                     columns=DEPTH_COLS.to_dict())
    assert r.mesh is not None


DIST_ELEV = ModelColumns(distance=0, vertical=1, vertical_kind="elevation", value=2)


def _lattice_file(path, nx, nz, dx=0.25, dz=0.1, depth=False):
    """A model exported on a fine lattice: distance, elevation (or depth), resistivity."""
    x, z = np.meshgrid(np.arange(nx) * dx, (1 if depth else -1) * (np.arange(nz) * dz
                                                                   + (0.05 if depth else 0)))
    rho = 10 ** (1 + x / 50)
    np.savetxt(path, np.column_stack([x.ravel(), z.ravel(), rho.ravel()]), fmt="%.4f")
    return path


def test_a_block_reads_the_file_as_coarser_averaged_cells(tmp_path):
    path = _lattice_file(tmp_path / "fine.txt", 40, 20)
    full = _read(path, DIST_ELEV)
    r = _read(path, DIST_ELEV, block=[4, 5])
    assert len(r.mesh.values) == 10 * 4
    assert r.provenance["block"] == [4, 5]
    assert r.provenance["cell"] == pytest.approx([1.0, 0.5])
    assert r.provenance["cell_file"] == pytest.approx([0.25, 0.1])
    assert r.provenance["n_points_file"] == 800
    assert r.mesh.bounds() == pytest.approx(full.mesh.bounds(), abs=1e-9)


def test_a_depth_model_still_hangs_from_the_surface_when_coarsened(tmp_path):
    path = _lattice_file(tmp_path / "depth.txt", 40, 20, depth=True)
    cols = ModelColumns(distance=0, vertical=1, vertical_kind="depth", value=2)
    r = _read(path, cols, block=[4, 5])
    assert r.provenance["reconstruction"] == "rows"
    assert min(r.mesh.bounds()[2:]) == pytest.approx(0.0)


def test_a_map_file_with_a_bend_is_averaged_along_its_line(tmp_path):
    s = np.arange(81) * 0.25                                    # 0 .. 20 m along an L
    e = np.where(s <= 10, 100 + s, 110.0)
    n = np.where(s <= 10, 200.0, 200 + s - 10)
    rows = [(e[i], n[i], 0.05 + 0.1 * k, 50.0) for k in range(20) for i in range(81)]
    path = tmp_path / "bend.txt"
    np.savetxt(path, rows, fmt="%.4f")

    def project(ee, nn):
        along = np.where(nn == 200.0, ee - 100, 10 + nn - 200)
        return along, np.zeros_like(along)
    r = readers.read(path, reader="text_columns", table=NO_HEADER, columns=MAP_COLS,
                     xy_to_distance=project, block=[4, 5])
    assert len(r.mesh.values) == 21 * 4                         # 81 positions in blocks of 4
    assert r.mesh.bounds()[:2] == pytest.approx((-0.125, 20.125))


def test_the_grid_of_a_big_file_is_found_and_a_small_one_is_not_read(tmp_path, monkeypatch):
    from groundwork_geophysics.core.coarsen import PointGrid
    from groundwork_geophysics.readers import text_columns
    from groundwork_geophysics.readers.text_columns import grid_of_file
    big = _lattice_file(tmp_path / "big.txt", 404, 250)
    g = grid_of_file(big, NO_HEADER, DIST_ELEV.to_dict())
    assert isinstance(g, PointGrid) and g.n_points == 101_000 and g.dx == pytest.approx(0.25) and g.dz == pytest.approx(0.1)
    small = _lattice_file(tmp_path / "small.txt", 10, 5)

    def no_read(*_a, **_k):
        raise AssertionError("a small file is not read for its grid")
    monkeypatch.setattr(text_columns, "read_numbers", no_read)
    assert grid_of_file(small, NO_HEADER, DIST_ELEV.to_dict()) is None


@pytest.mark.parametrize("bad_row", ["-9999 -1.0 50.0", "5.0 -9999 50.0"])
def test_a_fill_distance_or_height_is_left_out_of_the_coarse_cells(tmp_path, bad_row):
    # a -9999 distance or elevation is no position: it must not stretch a block to it
    from groundwork_geophysics.readers.text_columns import grid_of_file
    path = _lattice_file(tmp_path / "fill.txt", 40, 20)
    path.write_text(path.read_text() + bad_row + "\n")
    full = _read(path, DIST_ELEV)
    coarse = _read(path, DIST_ELEV, block=[4, 5])
    assert coarse.mesh.bounds() == pytest.approx(full.mesh.bounds(), abs=1e-9)
    assert coarse.provenance["n_points_file"] == 800


def test_a_coarsened_depth_model_hangs_from_the_surface_like_the_full_one(tmp_path):
    # its first points lie 0.25 m deep: the full read's top edge is still depth 0
    x, z = np.meshgrid(np.arange(40) * 0.25, np.arange(20) * 0.1 + 0.25)
    path = tmp_path / "deep.txt"
    np.savetxt(path, np.column_stack([x.ravel(), z.ravel(), np.full(x.size, 50.0)]),
               fmt="%.4f")
    cols = ModelColumns(distance=0, vertical=1, vertical_kind="depth", value=2)
    full, coarse = _read(path, cols), _read(path, cols, block=[4, 5])
    assert min(full.mesh.bounds()[2:]) == pytest.approx(0.0)
    assert min(coarse.mesh.bounds()[2:]) == pytest.approx(0.0)


def test_the_grid_check_never_reads_a_big_file_as_text(tmp_path, monkeypatch):
    # a comment line keeps the fast reader out; the slow text read of millions of rows would
    # freeze Add Data before the user chose anything, so there is simply no offer
    from groundwork_geophysics.readers import text_columns
    from groundwork_geophysics.readers.text_columns import grid_of_file
    big = _lattice_file(tmp_path / "big.txt", 404, 250)
    lines = big.read_text().splitlines(keepends=True)
    big.write_text("".join(lines[:5000] + ["# a note in the middle\n"] + lines[5000:]))

    def no_text(*_a, **_k):
        raise AssertionError("read as text")
    monkeypatch.setattr(text_columns, "read_table", no_text)
    assert grid_of_file(big, NO_HEADER, DIST_ELEV.to_dict()) is None


def test_points_that_form_no_grid_say_how_to_read_them_anyway(tmp_path):
    rng = np.random.default_rng(2)
    path = tmp_path / "scattered.txt"
    np.savetxt(path, np.column_stack([rng.uniform(0, 50, 300), rng.uniform(-10, 0, 300),
                                      np.full(300, 50.0)]), fmt="%.4f")
    with pytest.raises(ValueError, match='untick "Read as cells of"'):
        _read(path, DIST_ELEV, block=[2, 2])
