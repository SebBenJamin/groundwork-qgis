"""R2 / ResIPy misfit file f001_err.dat with ResIPy's electrodes.dat."""
import numpy as np
import pytest

from groundwork_geophysics import readers

HEADER = ("   C+  C-  P+  P-  Normalised_Error  Observed_Rho  Calculated_Rho  "
          "Original_Data_Weight  Final_Data_Weight  Flag\n")
ROWS = [(1, 4, 2, 3, 2.0, 100.0, 110.0), (2, 5, 3, 4, -1.0, 100.0, 95.0),
        (1, 3, 4, 6, 0.5, 120.0, 123.0), (2, 6, 3, 5, 1.0, 130.0, 136.5),
        (1, 6, 2, 5, -2.0, 140.0, 126.0)]


def _write(tmp_path, electrodes=True):
    p = tmp_path / "f001_err.dat"
    p.write_text(HEADER + "".join(f"{a} {b} {m} {n} {ne} {o} {c} 0.01 0.01 0\n"
                                  for a, b, m, n, ne, o, c in ROWS))
    if electrodes:
        (tmp_path / "electrodes.dat").write_text("".join(f"{x:.3f} 25.0 0.0\n"
                                                         for x in (0, 2, 4, 6, 8, 10)))
    return p


def test_detect_and_read(tmp_path):
    p = _write(tmp_path)
    assert readers.detect(p)[0] == "r2_err"
    r = readers.read(p)
    rd = r.mesh.readings
    assert r.provenance["kind"] == "ert_misfit" and r.z_kind == "depth"
    assert np.allclose(rd.a, [0, 2, 0, 2, 0]) and np.allclose(rd.n, [4, 6, 10, 8, 8])
    assert np.allclose(rd.misfit_percent(), [10.0, -5.0, 2.5, 5.0, -10.0])
    assert rd.chi2() == pytest.approx(np.mean(np.square([2.0, -1.0, 0.5, 1.0, -2.0])))


def test_missing_electrode_positions_is_a_readable_error(tmp_path):
    with pytest.raises(ValueError, match="electrodes.dat"):
        readers.read(_write(tmp_path, electrodes=False))


def test_electrode_number_out_of_range(tmp_path):
    p = _write(tmp_path)
    (tmp_path / "electrodes.dat").write_text("0 25 0\n2 25 0\n4 25 0\n")
    with pytest.raises(ValueError, match="out of range"):
        readers.read(p)


def test_real_r2_run_on_guelpe_matches_r2s_final_rms():
    """A real R2 run (via ResIPy, 80 electrodes of Gülpe transect 3, CC BY 4.0;
    scripts/invert_guelpe.py r2small): sqrt(chi2) from R2's normalised misfit must equal R2's
    own final RMS (1.00), and the electrodes come from ResIPy's electrodes.dat."""
    import re
    from pathlib import Path
    d = Path(__file__).resolve().parents[1] / "fixtures" / "ert" / "r2_guelpe_t3"
    r = readers.read(d / "f001_err.dat")
    rd = r.mesh.readings
    final = float(re.findall(r"Final RMS Misfit:\s+([0-9.]+)", (d / "R2.out").read_text())[-1])
    assert len(rd) == 1642
    assert np.sqrt(rd.chi2()) == pytest.approx(final, abs=0.02)
    assert np.nanmax(np.r_[rd.a, rd.b, rd.m, rd.n]) <= 79.0          # 80 electrodes, 1 m
    assert 0 < rd.rms_percent() < 20


def test_r2_out_final_rms_is_checked(tmp_path):
    p = _write(tmp_path)
    (tmp_path / "R2.out").write_text("   Final RMS Misfit:        9.00" + chr(10))
    with pytest.raises(ValueError, match="RMS"):
        readers.read(p)
    (tmp_path / "R2.out").write_text("   Final RMS Misfit:        1.50" + chr(10))
    readers.read(p)                                          # sqrt(chi2) = 1.45: consistent


def test_r2_header_layout_is_validated(tmp_path):
    p = _write(tmp_path)
    p.write_text(p.read_text().replace("Observed_Rho  Calculated_Rho", "Foo  Bar"))
    with pytest.raises(ValueError, match="column"):
        readers.read(p)


def test_electrodes_csv_is_not_used(tmp_path):
    p = _write(tmp_path, electrodes=False)
    rows = ["x,y,z"] + [f"{x},25,0" for x in (0, 2, 4, 6, 8, 10)]
    (tmp_path / "electrodes.csv").write_text(chr(10).join(rows) + chr(10))
    with pytest.raises(ValueError, match="electrodes.dat"):
        readers.read(p)
