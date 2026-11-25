import numpy as np, pytest
from groundwork_geophysics.core.chainage import Chainage

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
    from groundwork_geophysics.core.chainage import remap
    old = Chainage(np.array([[0, 0], [100, 0]], float))
    new = Chainage(np.array([[0, 2], [50, 2], [100, 6]], float))
    s = remap(old, new, [25.0, 500.0])
    assert s[0] == pytest.approx(25.0, abs=0.1)
    # beyond the old end: the overhang (400 m) goes on 1:1 past the new end
    assert s[1] == pytest.approx(remap(old, new, 100.0) + 400.0)


def test_remap_carries_the_part_beyond_the_ends_over():
    from groundwork_geophysics.core.chainage import remap
    old = Chainage(np.array([[0, 0], [100, 0]], float))
    moved = Chainage(np.array([[0, 1], [100, 1]], float))         # 1 m sideways
    s = [-20.0, -10.0, 50.0, 115.0, 120.0]
    assert remap(old, moved, s) == pytest.approx(s)
    back = Chainage(np.array([[100, 1], [0, 1]], float))         # and running the other way
    assert remap(old, back, s) == pytest.approx([120.0, 110.0, 50.0, -15.0, -20.0])


def test_projecting_many_points_works_in_chunks_with_the_same_result(monkeypatch):
    # 2 million points on a 25-segment line needed two arrays of 785 MB at once
    from groundwork_geophysics.core import chainage as ch
    line = Chainage(np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0], [20.0, 15.0]]))
    rng = np.random.default_rng(4)
    pts = rng.uniform(-5, 25, size=(500, 2))
    whole = line.project(pts)
    monkeypatch.setattr(ch, "_PROJECT_CHUNK", 7)
    parts = line.project(pts)
    np.testing.assert_array_equal(parts[0], whole[0])
    np.testing.assert_array_equal(parts[1], whole[1])
