import numpy as np, pytest
from geophysics_workbench.core.chainage import Chainage

L = Chainage(np.array([[0, 0], [100, 0], [100, 50]], float))  # crooked, length 150

def test_length():
    assert L.length == pytest.approx(150)

def test_to_xy_on_second_segment():
    assert L.to_xy(120) == pytest.approx([100, 20])

def test_to_xy_extrapolates_beyond_ends():
    assert L.to_xy(-10) == pytest.approx([-10, 0])
    assert L.to_xy(160) == pytest.approx([100, 60])

def test_project_returns_chainage_and_signed_offset():
    s, off = L.project(np.array([[50, 5], [50, -5], [90, 30]], float))
    assert s == pytest.approx([50, 50, 130])
    assert off == pytest.approx([5, -5, 10])

def test_reversed_flips_chainage():
    r = L.reversed()
    assert r.to_xy(0) == pytest.approx([100, 50])
    assert r.project(np.array([[50, 0.0]]))[0] == pytest.approx([100])

def test_rejects_degenerate_lines():
    with pytest.raises(ValueError):
        Chainage(np.array([[1, 1], [1, 1]], float))

def test_remap_carries_a_position_across():
    from geophysics_workbench.core.chainage import remap
    old = Chainage(np.array([[0, 0], [100, 0]], float))
    new = Chainage(np.array([[0, 2], [50, 2], [100, 6]], float))
    s = remap(old, new, [25.0, 500.0])
    assert s[0] == pytest.approx(25.0, abs=0.1)
    assert s[1] == pytest.approx(new.length, abs=1.0)      # beyond the old end: clamped
