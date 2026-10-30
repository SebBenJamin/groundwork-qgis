"""Readers rebuild the real cells of cell-centre models (0.1.1, finding F3)."""
from pathlib import Path

import numpy as np
import pytest

from geophysics_workbench import readers
from geophysics_workbench.section.data import cell_path_groups
from geophysics_workbench.core.colors import ColorScale

DEMO = Path("demo/data/ert")


def test_zond_depth_model_spans_whole_cells():
    r = readers.read(DEMO / "P2" / "P2_model.dat")
    assert r.z_kind == "depth" and r.provenance["reconstruction"] == "rows"
    xmin, xmax, zmin, zmax = r.mesh.bounds()
    assert xmin == pytest.approx(0.0, abs=1e-6) and xmax == pytest.approx(355.0, abs=1e-6)
    assert zmin == 0.0                                       # top edge on the surface
    assert zmax == pytest.approx(69.052 + (69.052 - 63.827) / 2)
    assert len(r.mesh.cells) == r.provenance["n_points"] == 4118
    # the corner of the first cell has a value now (it was outside the triangulation)
    assert r.mesh.value_at(0.1, 0.05) == pytest.approx(81.94)


def test_zond_quads_hang_from_the_surface():
    r = readers.read(DEMO / "P2" / "P2_model.dat")
    m = r.mesh.depth_to_elevation(np.array([0.0, 355.0]), np.array([50.0, 60.0]))
    xmin, xmax, zmin, zmax = m.bounds()
    assert zmax == pytest.approx(60.0) and m.value_at(0.01, 49.99) == pytest.approx(81.94)
    groups = cell_path_groups(m, ColorScale.auto(m.values, log=True))
    assert sum(len(g) for _c, g in groups) == 5 * len(m.cells)


def test_r2_topography_model_uses_columns():
    r = readers.read(DEMO / "P1" / "f001_res.dat")
    assert r.z_kind == "elevation" and r.provenance["reconstruction"] == "columns"
    xmin, xmax, _zmin, _zmax = r.mesh.bounds()
    assert xmin == pytest.approx(1.25 - 1.25, abs=1e-6)
    assert xmax == pytest.approx(233.75 + 1.25, abs=1e-6)
    assert len(r.mesh.cells) == r.provenance["n_points"] == 2350


def _z_header_copy(tmp_path):
    """P2_model.dat (positive depths) with the header of the user's real Zond files."""
    lines = (DEMO / "P2" / "P2_model.dat").read_text().splitlines()
    lines[0] = "#X\tZ\tlog_Rho\tRho"
    p = tmp_path / "P2_z_header.dat"
    p.write_text("\n".join(lines) + "\n")
    return p


HALF_GAP_TOP = 0.25 - (0.775 - 0.25) / 2            # -0.0125: no snapping to depth 0


def test_user_depth_choice_puts_the_top_on_the_surface(tmp_path):
    p = _z_header_copy(tmp_path)
    guessed = readers.read(p)
    assert guessed.z_kind == "unknown" and guessed.mesh.bounds()[2] == pytest.approx(HALF_GAP_TOP)
    chosen = readers.read(p, z_kind="depth")
    assert chosen.z_kind == "depth" and chosen.mesh.bounds()[2] == 0.0


def test_user_elevation_choice_overrides_a_depth_header():
    r = readers.read(DEMO / "P2" / "P2_model.dat", z_kind="elevation")
    assert r.z_kind == "elevation"
    _x0, _x1, zmin, zmax = r.mesh.bounds()
    assert zmin == pytest.approx(HALF_GAP_TOP)
    assert zmax == pytest.approx(69.052 + (69.052 - 63.827) / 2)
