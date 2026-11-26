"""Remembered reads of trace sections: what comes back is what was saved."""
import numpy as np
import pytest

from groundwork_geophysics.core.read_cache import cacheable, load_result, save_result
from groundwork_geophysics.core.trace_section import TraceSection
from groundwork_geophysics.readers.base import ReaderResult


def test_a_trace_result_comes_back_as_it_went(tmp_path):
    s = TraceSection(np.arange(6, dtype=np.int16).reshape(2, 3), np.array([0.0, 2.0]),
                     0.006, 0.0001, "time", numbers=np.array([7, 8]))
    assert save_result(tmp_path / "r.npz", ReaderResult(None, "depth", {"k": 1}, traces=s))
    back = load_result(tmp_path / "r.npz")
    assert back.mesh is None and back.z_kind == "depth" and back.provenance == {"k": 1}
    t = back.traces
    assert t.amplitudes.dtype == np.int16 and (t.amplitudes == s.amplitudes).all()
    assert (t.first, t.step, t.domain) == (0.006, 0.0001, "time") and list(t.numbers) == [7, 8]


def test_a_trace_result_without_numbers_keeps_quantity_and_unit(tmp_path):
    s = TraceSection(np.ones((2, 3), np.float32), np.array([0.0, 2.0]), 1.0, 0.5, "depth",
                     quantity="reflectivity", unit="dB")
    r = ReaderResult(None, "elevation", traces=s)
    assert cacheable(r) and save_result(tmp_path / "r.npz", r)
    t = load_result(tmp_path / "r.npz").traces
    assert t.numbers is None and (t.quantity, t.unit, t.domain) == ("reflectivity", "dB", "depth")
    assert list(t.x) == [0.0, 2.0] and t.amplitudes.dtype == np.float32


def test_a_result_needs_exactly_one_of_mesh_and_traces():
    with pytest.raises(ValueError):
        ReaderResult(None, "depth")
