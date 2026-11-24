"""Coarser cells for over-fine model exports: the grid of a table's points, the proposed
block size and the averaged blocks."""
import numpy as np
import pytest

from groundwork_geophysics.core.coarsen import (PointGrid, coarsen_boxes, point_grid,
                                                proposed_block)


def _lattice(nx, nz, dx, dz):
    x, z = np.meshgrid(np.arange(nx) * dx, -np.arange(nz) * dz)
    return x.ravel(), z.ravel()


def test_a_lattice_is_found_with_its_spacing():
    g = point_grid(*_lattice(400, 251, 0.25, 0.1))
    assert g.n_points == 100_400 and g.dx == pytest.approx(0.25) and g.dz == pytest.approx(0.1)


def test_scattered_points_are_no_grid():
    rng = np.random.default_rng(1)
    assert point_grid(rng.uniform(0, 100, 5000), rng.uniform(-20, 0, 5000)) is None


def test_the_proposal_is_nice_sizes_no_more_lopsided_and_about_50000_cells():
    assert proposed_block(PointGrid(623_241, 0.25, 0.1)) == (4, 5)      # 1.0 x 0.5 m
    assert proposed_block(PointGrid(100_400, 0.25, 0.1)) == (2, 2)      # 0.5 x 0.2 m
    assert proposed_block(PointGrid(100_000, 0.25, 0.1)) is None


def test_a_spacing_without_nice_multiples_still_gets_a_proposal():
    fx, fz = proposed_block(PointGrid(400_000, 0.3, 0.07))
    assert 400_000 / (fx * fz) <= 50_000


def test_blocks_average_in_log_and_keep_a_value_when_half_filled():
    x, z = _lattice(4, 2, 1.0, 1.0)                  # two 2 x 2 blocks
    v = np.array([10, 1000, 10, 10, 10, 1000, np.nan, np.nan], float)
    boxes, cv, _ = coarsen_boxes(x, z, v, None, (2, 2), log=True)
    order = np.argsort(boxes[:, 0])
    assert boxes[order].tolist() == [[-0.5, 1.5, -1.5, 0.5], [1.5, 3.5, -1.5, 0.5]]
    assert cv[order][0] == pytest.approx(100.0)       # log mean of 10, 1000, 10, 1000
    assert cv[order][1] == pytest.approx(10.0)        # 2 of 4 with a value: kept


def test_a_block_mostly_empty_stays_empty_and_coverage_is_averaged():
    x, z = _lattice(2, 2, 1.0, 1.0)
    v = np.array([50, np.nan, np.nan, np.nan], float)
    cov = np.array([1.0, 3.0, -np.inf, np.nan])
    _boxes, cv, ccov = coarsen_boxes(x, z, v, cov, (2, 2), log=False)
    assert np.isnan(cv[0]) and ccov[0] == pytest.approx(2.0)


def test_a_block_at_the_edge_spans_only_the_points_it_has():
    # 5 positions in blocks of 2: the last block holds one, so the model does not grow
    x, z = _lattice(5, 2, 0.25, 0.1)
    boxes, _v, _c = coarsen_boxes(x, z, np.full(10, 10.0), None, (2, 1), log=True)
    assert boxes[:, 0].min() == pytest.approx(-0.125)
    assert boxes[:, 1].max() == pytest.approx(1.125)
