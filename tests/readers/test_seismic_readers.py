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
