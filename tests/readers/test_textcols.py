from pathlib import Path
import pytest
from geophysics_workbench.readers.textcols import read_columns
F = Path("tests/fixtures/ert")


def test_read_columns_decimal_comma_semicolon():
    header, a = read_columns(F / "german_semicolon.txt")   # "Abstand;Tiefe;Rho [Ω·m]" then "0,5;1,25;123,4"
    assert header[0] == "Abstand"
    assert a[0].tolist() == pytest.approx([0.5, 1.25, 123.4])


def test_read_columns_latin1_header(tmp_path):
    p = tmp_path / "l1.txt"
    p.write_bytes("x z Rho(Ohm·m)\n1 2 3\n".encode("latin-1"))
    header, a = read_columns(p)
    assert header == ["x", "z", "Rho(Ohm·m)"] and a.shape == (1, 3)


def test_plain_comma_csv(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("x,z,rho\n1.5,2,30\n2.5,3,40\n")
    header, a = read_columns(p)
    assert header == ["x", "z", "rho"]
    assert a.tolist() == [[1.5, 2, 30], [2.5, 3, 40]]


def test_whitespace_with_decimal_comma_and_comments(tmp_path):
    p = tmp_path / "w.txt"
    p.write_text("// note\n# another comment\n0,5 1,25 3\n1,5 2,25 4\n", encoding="utf-8-sig")
    header, a = read_columns(p)
    assert header is None and a.tolist() == [[0.5, 1.25, 3], [1.5, 2.25, 4]]


def test_hash_header_is_returned_without_hash(tmp_path):
    p = tmp_path / "h.dat"
    p.write_text("#X\tZ\tRho,m\n1\t2\t3\n")
    header, a = read_columns(p)
    assert header == ["X", "Z", "Rho,m"] and a.shape == (1, 3)


def test_garbage_names_file_and_line(tmp_path):
    p = tmp_path / "bad.txt"
    p.write_text("1 2 3\n4 five 6\n")
    with pytest.raises(ValueError, match=r"bad\.txt, line 2"):
        read_columns(p)
    p.write_text("1 2 3\n4 5\n")
    with pytest.raises(ValueError, match=r"line 2.*expected 3 columns"):
        read_columns(p)
    p.write_text("not numbers\n")
    with pytest.raises(ValueError, match="no numeric data"):
        read_columns(p)
    p.write_text("")
    with pytest.raises(ValueError, match="empty"):
        read_columns(p)


def test_trailing_delimiter_is_ignored():
    from geophysics_workbench.readers.textcols import parse_columns

    header, arr = parse_columns("x;z;rho;\n1;2;3;\n4;5;6;\n")
    assert header == ["x", "z", "rho"] and arr.tolist() == [[1, 2, 3], [4, 5, 6]]
    _, arr = parse_columns("1,2,3,\n4,5,6,\n")
    assert arr.tolist() == [[1, 2, 3], [4, 5, 6]]
