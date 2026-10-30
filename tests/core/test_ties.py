import numpy as np
import pytest

from geophysics_workbench.core.section_mesh import SectionMesh
from geophysics_workbench.core.ties import TieColumn, mismatch_text, tie_mismatch


def test_column_at_quads_and_outside():
    m, _ = SectionMesh.from_cell_centres(np.array([1.0, 3, 1, 3]), np.array([-1.0, -1, -3, -3]),
                                         np.array([10.0, 20, 30, 40]), z_kind="elevation")
    top, bot, v = m.column_at(1.5)
    assert v.tolist() == [10.0, 30.0] and top[0] > bot[0] >= top[1] > bot[1]
    assert m.column_at(99.0)[2].size == 0


def test_column_at_triangles():
    m = SectionMesh(np.array([[0.0, 0], [4, 0], [0, -4]]), np.array([[0, 1, 2, -1]]), np.array([7.0]))
    top, bot, v = m.column_at(1.0)
    assert v.tolist() == [7.0] and top[0] == pytest.approx(0.0) and bot[0] == pytest.approx(-3.0)


def test_tie_mismatch_log_factor_over_overlap_only():
    a = TieColumn("P1", np.array([10.0, 5]), np.array([5.0, 0]), np.array([100.0, 100]), None, "resistivity", "ohm.m")
    b = TieColumn("P3", np.array([8.0, 4]), np.array([4.0, -6]), np.array([200.0, 200]), None, "resistivity", "ohm.m")
    m = tie_mismatch(a, b)
    assert m.factor == pytest.approx(2.0) and m.z_range == pytest.approx((0.0, 8.0))
    assert mismatch_text(m) == "×2.0 (median, 0–8 m a.s.l.)"


def test_tie_mismatch_no_overlap_and_linear_quantity():
    a = TieColumn("A", np.array([10.0]), np.array([5.0]), np.array([1.0]), None, "velocity", "m/s")
    b = TieColumn("B", np.array([4.0]), np.array([0.0]), np.array([1.0]), None, "velocity", "m/s")
    assert tie_mismatch(a, b).z_range is None and mismatch_text(tie_mismatch(a, b)) == "no depth overlap"
    c = TieColumn("C", np.array([10.0]), np.array([0.0]), np.array([300.0]), None, "velocity", "m/s")
    d = TieColumn("D", np.array([10.0]), np.array([0.0]), np.array([100.0]), None, "velocity", "m/s")
    m = tie_mismatch(c, d)
    assert m.rel_diff == pytest.approx(1.0) and m.factor is None
    assert mismatch_text(m).startswith("100 % (median, 0–10")


def test_mismatch_text_overlap_without_finite_samples():
    a = TieColumn("A", np.array([10.0]), np.array([0.0]), np.array([np.nan]), None, "velocity", "m/s")
    b = TieColumn("B", np.array([10.0]), np.array([0.0]), np.array([100.0]), None, "velocity", "m/s")
    m = tie_mismatch(a, b)
    assert m.z_range == pytest.approx((0.0, 10.0)) and mismatch_text(m) == "no comparable values"
