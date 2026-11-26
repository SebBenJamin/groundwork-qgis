"""Read results kept as npz files: what comes back is what was saved."""
import numpy as np


def _result(coverage=True, readings=None):
    from groundwork_geophysics.core.section_mesh import SectionMesh
    from groundwork_geophysics.readers.base import ReaderResult
    mesh = SectionMesh(np.array([[0.0, 0.0], [1.0, 0.0], [1.0, -1.0], [0.0, -1.0]]),
                       np.array([[0, 1, 2, 3]]), np.array([42.0]), "resistivity", "ohm.m",
                       coverage=np.array([-1.5]) if coverage else None, readings=readings,
                       coverage_cut=-2.0 if coverage else None)
    return ReaderResult(mesh, "elevation", {"reader": "text_columns", "cell": [1.0, 0.5],
                                            "n_points_file": 623241})


def test_a_result_comes_back_equal(tmp_path):
    from groundwork_geophysics.core.read_cache import load_result, save_result
    for coverage in (True, False):
        path = tmp_path / f"r{coverage}.npz"
        r = _result(coverage)
        assert save_result(path, r)
        back = load_result(path)
        np.testing.assert_array_equal(back.mesh.vertices, r.mesh.vertices)
        np.testing.assert_array_equal(back.mesh.cells, r.mesh.cells)
        np.testing.assert_array_equal(back.mesh.values, r.mesh.values)
        assert (back.mesh.quantity, back.mesh.unit) == ("resistivity", "ohm.m")
        assert back.z_kind == "elevation" and back.provenance == r.provenance
        if coverage:
            np.testing.assert_array_equal(back.mesh.coverage, [-1.5])
            assert back.mesh.coverage_cut == -2.0
        else:
            assert back.mesh.coverage is None and back.mesh.coverage_cut is None


def test_readings_are_not_cached(tmp_path):
    from groundwork_geophysics.core.read_cache import cacheable, save_result
    r = _result(readings=object())
    assert not cacheable(r)
    assert not save_result(tmp_path / "r.npz", r)
    assert not (tmp_path / "r.npz").exists()


def test_a_broken_file_is_none(tmp_path):
    from groundwork_geophysics.core.read_cache import load_result
    bad = tmp_path / "bad.npz"
    bad.write_bytes(b"not an npz at all")
    assert load_result(bad) is None
    assert load_result(tmp_path / "missing.npz") is None


def test_an_unwritable_place_gives_false(tmp_path):
    from groundwork_geophysics.core.read_cache import save_result
    blocker = tmp_path / "cache"
    blocker.write_text("a file where the folder should be")
    assert not save_result(blocker / "r.npz", _result())
