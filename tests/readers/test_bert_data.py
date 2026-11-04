"""pyGIMLi/BERT unified data format: measured readings, optional model response."""
import numpy as np
import pytest

from geophysics_workbench import readers

DATA = """6
# x z
0 10.0
1 10.1
2 10.2
3 10.3
4 10.4
5 10.5
5
# a b m n rhoa err
1 4 2 3 100.0 0.03
2 5 3 4 110.0 0.03
3 6 4 5 120.0 0.03
1 6 2 5 130.0 0.03
1 2 3 4 140.0 0.03
0
"""


def _write(tmp_path, text=DATA, name="line.data"):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_detect_and_read_measured_only(tmp_path):
    p = _write(tmp_path)
    assert readers.detect(p)[0] == "bert_data"
    r = readers.read(p)
    rd = r.mesh.readings
    assert r.z_kind == "depth" and r.provenance["kind"] == "ert_measured"
    assert np.allclose(rd.measured, [100, 110, 120, 130, 140])
    assert np.allclose(rd.a, [0, 1, 2, 0, 0]) and np.allclose(rd.n, [2, 3, 4, 4, 3])
    assert not rd.has_calculated and r.mesh.quantity == "resistivity"


def test_response_gives_misfit(tmp_path):
    p = _write(tmp_path)
    resp = tmp_path / "response.vector"
    resp.write_text("\n".join(str(v) for v in (110, 121, 132, 143, 154)))
    r = readers.read(p, response=str(resp))
    assert r.provenance["kind"] == "ert_misfit"
    assert np.allclose(r.mesh.readings.misfit_percent(), 10.0)
    assert r.mesh.quantity == "misfit"
    assert r.mesh.readings.chi2() == pytest.approx((0.10 / 0.03) ** 2)


def test_response_length_mismatch_fails(tmp_path):
    p = _write(tmp_path)
    resp = tmp_path / "r.vector"
    resp.write_text("1\n2\n")
    with pytest.raises(ValueError, match="response"):
        readers.read(p, response=str(resp))


def test_measured_from_r_and_k_and_pole_electrodes(tmp_path):
    text = DATA.replace("# a b m n rhoa err", "# a b m n r k").replace(" 0.03", " 2.0")
    text = text.replace("1 4 2 3 100.0", "1 0 2 3 50.0")           # pole-dipole: b absent
    r = readers.read(_write(tmp_path, text))
    rd = r.mesh.readings
    assert rd.measured[0] == pytest.approx(100.0) and np.isnan(rd.b[0])


def test_electrode_index_out_of_range_fails(tmp_path):
    text = DATA.replace("2 5 3 4 110.0", "2 9 3 4 110.0")
    with pytest.raises(ValueError, match="electrode"):
        readers.read(_write(tmp_path, text))


def test_model_files_are_not_bert_data():
    from pathlib import Path
    f = Path(__file__).resolve().parents[1] / "fixtures" / "ert"
    assert "bert_data" not in readers.detect(f / "f001_res.dat")


def test_real_guelpe_t3_misfit_matches_pygimli():
    """The authors' measured data (CC BY 4.0) and our pyGIMLi response
    (scripts/invert_guelpe.py): the reader's RMS must equal pyGIMLi's own."""
    import json
    from pathlib import Path
    d = Path(__file__).resolve().parents[2] / "demo_guelpe" / "data" / "ert" / "T3"
    r = readers.read(d / "T3_measured.data", response="T3_response.vector")
    info = json.loads((d / "T3_pygimli.json").read_text())
    assert len(r.mesh.readings) == info["n"] == 4524
    assert r.mesh.readings.rms_percent() == pytest.approx(info["rms_percent"], rel=1e-6)


def test_unit_suffixes_are_applied_not_misread(tmp_path):
    text = DATA.replace("# a b m n rhoa err", "# a b m n rhoa/Ohmm err/% i/mA").replace(
        " 0.03\n", " 3.0 100\n")
    rd = readers.read(_write(tmp_path, text)).mesh.readings
    assert np.allclose(rd.error, 0.03)                       # percent -> fraction
    assert np.allclose(rd.a, [0, 1, 2, 0, 0])                # 'i/A'-style tokens never clobber a


def test_unknown_unit_on_a_used_column_fails(tmp_path):
    text = DATA.replace("# a b m n rhoa err", "# a b m n rhoa/kOhmm err")
    with pytest.raises(ValueError, match="unit"):
        readers.read(_write(tmp_path, text))


def test_more_tokens_than_columns_is_a_readable_error(tmp_path):
    text = DATA.replace("# a b m n rhoa err", "# a b m n rhoa err k u")
    with pytest.raises(ValueError):
        readers.read(_write(tmp_path, text))


def test_xyz_2d_with_elevation_in_y_uses_x_and_3d_fails(tmp_path):
    rows = "\n".join(f"{x} {10 + 0.1 * x} 0" for x in range(6))
    text = DATA.replace("# x z\n0 10.0\n1 10.1\n2 10.2\n3 10.3\n4 10.4\n5 10.5",
                        "# x y z\n" + rows)
    rd = readers.read(_write(tmp_path, text)).mesh.readings
    assert np.allclose(rd.a, [0, 1, 2, 0, 0])                # x as given, no slope distance
    rows3d = "\n".join(f"{x} {0.5 * x} {10 + 0.1 * x}" for x in range(6))
    text3d = DATA.replace("# x z\n0 10.0\n1 10.1\n2 10.2\n3 10.3\n4 10.4\n5 10.5",
                          "# x y z\n" + rows3d)
    with pytest.raises(ValueError, match="3D"):
        readers.read(_write(tmp_path, text3d, "b.data"))


def test_remote_electrode_counts_as_a_pole(tmp_path):
    text = DATA.replace("5 10.5", "100000 10.5")              # electrode 6 far away (remote)
    rd = readers.read(_write(tmp_path, text)).mesh.readings
    assert rd.b[1] == 4.0                                     # reading 2: B = electrode 5
    assert np.isnan(rd.b[2]) and np.isnan(rd.b[3])           # readings 3, 4: B = electrode 6
    assert np.nanmax(np.r_[rd.a, rd.m, rd.n]) <= 4.0
