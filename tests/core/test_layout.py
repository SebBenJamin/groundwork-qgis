from pathlib import Path

import numpy as np
from pytest import approx

from groundwork_geophysics import readers
from groundwork_geophysics.core.layout import (derived_electrodes, guess_electrodes,
                                              guessed_spacing, inline_distances)
from groundwork_geophysics.core.placement import rigid_map
from groundwork_geophysics.core.section_mesh import SectionMesh
from groundwork_geophysics.readers.base import mesh_from_points

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def test_stored_distances_win():
    d, src = inline_distances([1, 5], [0.0, 9.5], spacing=2.5)
    assert d.tolist() == [0.0, 9.5] and src == "distances"


def test_readings_before_spacing_before_guess():
    d, src = inline_distances([1, 5, 10], [np.nan] * 3, readings_x=np.arange(0, 60, 2.0),
                              spacing=2.5)
    assert d.tolist() == [0.0, 8.0, 18.0] and src == "readings"
    assert inline_distances([1, 5], [np.nan] * 2, spacing=2.5)[0].tolist() == [0.0, 10.0]
    d, src = inline_distances([1, 5], [np.nan] * 2, guessed_spacing=2.0)
    assert d.tolist() == approx([0.0, 8.0]) and src == "guessed"
    assert inline_distances([1, 5], [np.nan] * 2)[1] == "none"


def test_spacing_counts_from_the_first_number():
    assert inline_distances([11, 16], [np.nan] * 2, spacing=5.0)[0].tolist() == [0.0, 25.0]


def _row_model():
    """Cell centres at x = 1.25, 3.75, ... 48.75 in three rows of depth."""
    xc = np.arange(1.25, 50, 2.5)
    x, z = np.meshgrid(xc, [0.5, 1.5, 3.0])
    return x.ravel(), z.ravel(), np.full(x.size, 100.0)


def test_guess_from_a_row_model_is_its_top_cell_edges():
    x, z, v = _row_model()
    mesh, _n, kind = mesh_from_points(x, z, v, "m", "depth")
    assert kind == "rows"
    assert guess_electrodes(mesh, "depth").tolist() == approx(np.arange(0, 50.01, 2.5).tolist())
    assert guessed_spacing(mesh, "depth") == approx(2.5)


def _scattered_model():
    """Points on a gently varying surface, about 2 m apart between 0 and 40, over two
    deeper, sparser layers: neither rows nor columns, so the model is triangulated."""
    rng = np.random.default_rng(7)
    xt = np.arange(0, 40.01, 2.0) + rng.uniform(-0.1, 0.1, 21)
    xt[0] = 0.0
    zt = 100 + 0.3 * np.sin(xt / 5.0) + rng.uniform(-0.05, 0.05, 21)
    xm = np.arange(1.0, 39.5, 3.0) + rng.uniform(-0.2, 0.2, 13)
    zm = 97 + rng.uniform(-0.3, 0.3, 13)
    xb = np.arange(2.0, 38.5, 4.0) + rng.uniform(-0.2, 0.2, 10)
    zb = 93 + rng.uniform(-0.5, 0.5, 10)
    x, z = np.r_[xt, xm, xb], np.r_[zt, zm, zb]
    return x, z, np.full(x.size, 50.0)


def test_no_guess_from_a_triangulated_model():
    x, z, v = _scattered_model()
    mesh, _n, kind = mesh_from_points(x, z, v, "m", "elevation")
    assert kind == "delaunay"
    assert guess_electrodes(mesh, "elevation").size == 0
    assert guessed_spacing(mesh, "elevation") is None


def test_no_guess_from_a_vtk_triangle_mesh():
    r = readers.read(FIXTURES / "ert" / "f001_res.vtk")
    assert (r.mesh.cells[:, 3] < 0).any()
    assert guess_electrodes(r.mesh, r.z_kind).size == 0
    assert guessed_spacing(r.mesh, r.z_kind) is None


def test_no_guess_from_a_skewed_quad():
    skew = SectionMesh([[0.0, 0.0], [2.0, 0.0], [3.0, 1.0], [1.0, 1.0]], [[0, 1, 2, 3]], [10.0])
    assert guess_electrodes(skew, "elevation").size == 0
    assert guessed_spacing(skew, "elevation") is None


def test_derived_order_and_kind():
    m = rigid_map(0.0)
    assert derived_electrodes(m, (0, 10), readings_x=[0, 2, 4]).kind == "readings"
    e = derived_electrodes(m, (0, 10), spacing=2.5)
    assert e.kind == "spacing" and e.chainage.tolist() == [0.0, 2.5, 5.0, 7.5, 10.0]
    assert e.numbers.tolist() == [1, 2, 3, 4, 5]
    assert derived_electrodes(m, (0, 10), guess=[0.0, 3.0]).kind == "guessed"
    assert derived_electrodes(m, (0, 10)) is None


def test_derived_from_readings_number_by_distance_and_skip_remote_poles():
    e = derived_electrodes(rigid_map(100.0, -1), (0, 10), readings_x=[4.0, None, 0.0, 2.0])
    assert e.numbers.tolist() == [1, 2, 3] and e.chainage.tolist() == [100.0, 98.0, 96.0]
