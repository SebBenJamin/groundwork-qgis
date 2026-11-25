from pathlib import Path

import pytest

from groundwork_geophysics.readers.texttable import (
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


def _numbers_match_the_text_table(path, opts):
    import numpy as np

    from groundwork_geophysics.readers.texttable import read_numbers
    fast, slow = read_numbers(path, opts), read_table(path, opts)
    assert fast is not None
    assert fast.names == slow.names and fast.n_rows == slow.n_rows
    for c in range(slow.n_columns):
        np.testing.assert_array_equal(fast.numeric(c), slow.numeric(c))
        assert fast.is_numeric(c) == slow.is_numeric(c)
    return fast


RES2D = ("JWDL9 merged - Resistivity model \n"
         "Dist, X_NAD83UTMz16N, Y_NAD83UTMz16N, Elev, Log10Res, Shading \n"
         "0.00, 703719.50, 3399129.47, -19.77, -9999, -9999 \n"
         "\n"
         "0.50, 703719.90, 3399129.80, -19.67, 1.92, -inf \n")


def test_a_clean_table_is_read_as_numbers_alone(tmp_path):
    # the full read of a big model keeps no text per cell: a 2-million-row export ran out of
    # memory as text
    _numbers_match_the_text_table(WILD / "east_north_depth_rho.csv",
                                  guess_options(WILD / "east_north_depth_rho.csv"))
    _numbers_match_the_text_table(WILD / "x_zero_depth_rho.txt", TableOptions(header=False))
    p = tmp_path / "res2d.csv"
    p.write_text(RES2D)
    t = _numbers_match_the_text_table(p, TableOptions(skip=1))
    assert t.names[0] == "Dist" and t.raw(5)[1] == float("-inf")


@pytest.mark.parametrize("text, opts", [
    ("a,b\n1,2\n3\n", TableOptions()),                                  # a short row
    ("a,b\n1,2\n3,x\n", TableOptions()),                                # a text cell
    ("a,b\n1,2 # note\n", TableOptions()),                              # a comment in a row
])
def test_a_table_the_numbers_alone_cannot_read_is_left_to_the_text_table(tmp_path, text,
                                                                           opts):
    from groundwork_geophysics.readers.texttable import read_numbers
    p = tmp_path / "t.txt"
    p.write_text(text)
    assert read_numbers(p, opts) is None
    read_table(p, opts)                                 # which reads it as before


@pytest.mark.parametrize("opts", [TableOptions("semicolon", decimal_comma=True),
                                  TableOptions()])
def test_decimal_commas_are_read_as_numbers_alone(tmp_path, opts):
    # German exports: 1,25;3,4;120,5 (by "detect" too: a semicolon table reads commas as
    # decimal points)
    p = tmp_path / "comma.txt"
    p.write_text("x;z;rho\n1,25;3,4;120,5\n1,5;3,5;-9999\n")
    _numbers_match_the_text_table(p, opts)
