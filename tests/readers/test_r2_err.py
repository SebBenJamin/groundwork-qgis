"""R2 / ResIPy misfit file f001_err.dat with ResIPy's electrodes.dat."""
import numpy as np
import pytest

from geophysics_workbench import readers

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
