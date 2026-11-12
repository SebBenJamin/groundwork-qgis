from pathlib import Path

import pytest

from geophysics_workbench.readers.texttable import (
    TableOptions, guess_options, read_table, select_rows)

WILD = Path("tests/fixtures/wild")


def test_junk_lines_decimal_comma_and_text_column():
    opts = guess_options(WILD / "dist_y_rho_junk.txt")
    assert (opts.skip, opts.header) == (2, True)
    t = read_table(WILD / "dist_y_rho_junk.txt", opts)
    assert t.names == ["X", "Y", "Rho", "Comment"]
    assert [t.is_numeric(c) for c in range(4)] == [True, True, True, False]
    arr, skipped, first = select_rows(t, [0, 1, 2])
    assert arr[0].tolist() == [1.25, 0.31, 84.2]
    assert skipped == 1 and first == 9          # the short row, by its file line number


def test_without_names_columns_are_numbered():
    t = read_table(WILD / "x_zero_depth_rho.txt", TableOptions(header=False))
    assert t.names == ["column 1", "column 2", "column 3", "column 4"]


def test_all_rows_unusable_is_an_error():
    t = read_table(WILD / "dist_y_rho_junk.txt", guess_options(WILD / "dist_y_rho_junk.txt"))
    with pytest.raises(ValueError, match="no usable rows"):
        select_rows(t, [3])


def test_max_rows_limits_the_preview_read():
    assert read_table(WILD / "east_north_depth_rho.csv", max_rows=5).n_rows == 5


def test_options_round_trip():
    o = TableOptions("semicolon", 2, True, True)
    assert TableOptions.from_dict(o.to_dict()) == o


def test_comma_table_with_spaced_remarks_keeps_its_columns():
    opts = guess_options(WILD / "positions_sparse.csv")
    assert (opts.skip, opts.header) == (0, True)
    t = read_table(WILD / "positions_sparse.csv", opts)
    assert t.names == ["nr", "east", "north", "z", "remark"] and t.n_rows == 5
    assert t.numeric(0).tolist() == [1, 5, 10, 16, 20]
    assert not t.is_numeric(4)


def test_headerless_table_is_guessed_without_header():
    opts = guess_options(WILD / "x_zero_depth_rho.txt")
    assert (opts.skip, opts.header) == (0, False)
    t = read_table(WILD / "x_zero_depth_rho.txt", opts)
    assert t.n_columns == 4 and (t.numeric(1) == 0).all()


def test_explicit_delimiter_reads_decimal_commas_only_when_asked(tmp_path):
    p = tmp_path / "t.txt"
    p.write_text("a;b\n1,5;2\n")
    assert read_table(p, TableOptions("semicolon", decimal_comma=True)).numeric(0).tolist() == [1.5]
    assert not read_table(p, TableOptions("semicolon")).is_numeric(0)
