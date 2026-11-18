"""Seismic refraction models: pyGIMLi/Refrapy VTK files and Refrapy's _xzv.txt."""
from pathlib import Path

import numpy as np
import pytest

from groundwork_geophysics import readers

F = Path("tests/fixtures/ert")


def _vtk(path: Path, arrays: list[str]) -> Path:
    """Two triangles (x, y=elevation, z=0, as pyGIMLi writes 2D meshes) with one cell array
    per name; values: 1000 + 100 * array index + cell."""
    lines = ["# vtk DataFile Version 3.0", "pyGIMLi", "ASCII", "DATASET UNSTRUCTURED_GRID",
             "POINTS 4 double", "0 0 0", "10 0 0", "0 -5 0", "10 -5 0",
             "CELLS 2 8", "3 0 1 2", "3 1 3 2", "CELL_TYPES 2", "5", "5", "CELL_DATA 2"]
    for k, name in enumerate(arrays):
        lines += [f"SCALARS {name} double 1", "LOOKUP_TABLE default",
                  f"{1000 + 100 * k} {1001 + 100 * k}"]
    path.write_text("\n".join(lines) + "\n")
    return path


def test_pygimli_velocity_vtk(tmp_path):
    p = _vtk(tmp_path / "velocity.vtk", ["Coverage", "Marker", "S_Coverage", "Velocity"])
    r = readers.read(p)
    assert r.provenance["array"] == "Velocity"
    assert r.mesh.quantity == "p_velocity" and r.mesh.unit == "m/s"
    assert r.provenance["kind"] == "srt_model" and r.provenance["method"] == "srt"
    assert r.provenance["coverage_array"] == "Coverage"
    assert r.mesh.values.tolist() == [1300, 1301]


def test_bootstrap_vtk_skips_top_and_bottom(tmp_path):
    p = _vtk(tmp_path / "run.vtk", ["Bottom_Velocity", "Marker", "Ray_Coverage",
                                    "Standard_Ray_Coverage", "Top_Velocity", "Velocity"])
    r = readers.read(p)
    assert r.provenance["array"] == "Velocity"
    assert r.provenance["coverage_array"] == "Ray_Coverage"


def test_velocity_named_differently(tmp_path):
    p = _vtk(tmp_path / "v.vtk", ["Top_Velocity", "P_Velocity(m/s)", "Coverage"])
    r = readers.read(p)
    assert r.provenance["array"] == "P_Velocity(m/s)" and r.mesh.quantity == "p_velocity"


def test_resistivity_vtk_unchanged():
    r = readers.read(F / "f001_res.vtk")
    assert r.provenance["array"].startswith("Resistivity")
    assert r.mesh.quantity == "resistivity" and "method" not in r.provenance
    assert r.provenance["coverage_array"] == "Sensitivity(log10)"


HEADER = "x z velocity converage standardized coverage sc_v"


def _xzv(folder: Path, stem: str = "L9", topography: bool = True) -> Path:
    """A 4 x 3 grid of cell centres as Refrainv saves them; the bottom row has no rays
    (coverage -inf, standardized 0), one middle cell is outside the resolved area."""
    rows = []
    for j, z in enumerate((100.0, 98.0, 96.0)):
        for i, x in enumerate((1.0, 3.0, 5.0, 7.0)):
            v = 400.0 + 500.0 * j + 10 * i
            if j == 2:
                c, s = "-inf", 0.0
            elif j == 1 and i == 0:
                c, s = "0.50", 0.0
            else:
                c, s = f"{2.0 + 0.1 * i - j:.2f}", 1.0
            rows.append(f"{x:.2f} {z:.2f} {v:.2f} {c} {s:.2f} {v * s:.2f}")
    p = folder / f"{stem}_xzv.txt"
    p.write_text(HEADER + "\n" + "\n".join(rows) + "\n")
    if topography:
        (folder / f"{stem}_topography.txt").write_text("x z\n0.00 101.00\n2.00 101.10\n"
                                                       "4.00 101.20\n8.00 101.30\n")
    return p


def test_refrapy_detected_first(tmp_path):
    assert readers.detect(_xzv(tmp_path))[0] == "refrapy_xzv"


def test_refrapy_reads_velocity_coverage_and_cut(tmp_path):
    r = readers.read(_xzv(tmp_path))
    assert r.mesh.quantity == "p_velocity" and r.mesh.unit == "m/s"
    assert r.provenance["kind"] == "srt_model" and r.provenance["method"] == "srt"
    assert r.z_kind == "elevation"
    # resolved rows (standardized 1) have coverages 1.1 .. 2.3: the cut is the lowest
    assert r.mesh.coverage_cut == pytest.approx(1.1)
    assert r.provenance["coverage_cut"] == pytest.approx(1.1)
    assert np.isfinite(r.mesh.coverage).all()             # no ray: below the rest, not nan
    assert (r.mesh.coverage < r.mesh.coverage_cut).any()
    assert r.provenance["n_cells"] == 12 and r.provenance["n_unresolved"] == 5
    assert r.provenance["station_x"] == [0.0, 2.0, 4.0, 8.0]
    assert 400 <= np.nanmin(r.mesh.values) and np.nanmax(r.mesh.values) <= 1430


def test_refrapy_without_topography_file_still_reads(tmp_path):
    r = readers.read(_xzv(tmp_path, topography=False))
    assert "station_x" not in r.provenance
    assert "_topography.txt" in r.provenance["warning"]


def test_refrapy_rejects_short_rows(tmp_path):
    p = tmp_path / "bad_xzv.txt"
    p.write_text(HEADER + "\n1 2 3\n4 5 6\n7 8 9\n")
    with pytest.raises(ValueError, match="bad_xzv.txt"):
        readers.read(p, reader="refrapy_xzv")


def test_refrapy_user_run_reads():
    p = Path(".cache/demo_seismic/refrapy_calhoun/models/20261118-191757/L1_xzv.txt")
    if not p.exists():
        pytest.skip("the user's Refrainv run is not in the local cache")
    r = readers.read(p)
    assert r.provenance["n_cells"] == 6886 and r.provenance["n_unresolved"] == 3013
    assert 100 <= np.nanmin(r.mesh.values) and np.nanmax(r.mesh.values) <= 7000


def test_no_ray_cells_fade(tmp_path):
    """Refrainv's -inf coverage (no ray) is below the cut, so the default fade covers it."""
    from groundwork_geophysics.core.gridding import coverage_alpha, default_threshold
    r = readers.read(_xzv(tmp_path))
    m = r.mesh
    alpha = coverage_alpha(m.coverage, default_threshold(m.coverage, m.coverage_cut), "fade")
    assert (alpha < 1).sum() >= 4            # at least the bottom row's cells fade


def test_pygimli_vtk_minus_inf_coverage_fades(tmp_path):
    p = _vtk(tmp_path / "velocity.vtk", ["Coverage", "Velocity"])
    p.write_text(p.read_text().replace("1000 1001", "-inf 1.5"))
    r = readers.read(p)
    assert np.isfinite(r.mesh.coverage).all() and r.mesh.coverage[0] < r.mesh.coverage[1]
