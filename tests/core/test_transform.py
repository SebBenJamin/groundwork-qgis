import numpy as np, pytest
from geophysics_workbench.core.transform import fit_control_points, Transform2D

def test_two_points_similarity_exact():
    local = np.array([[0, 0], [100, 0]], float)
    world = np.array([[500000, 5700000], [500000, 5700100]], float)  # rotated 90°
    t = fit_control_points(local, world)
    assert t.kind == "similarity"
    assert t.apply(np.array([[50, 0.0]])) == pytest.approx(np.array([[500000, 5700050]]))
    assert t.rms == pytest.approx(0, abs=1e-6)

def test_three_points_affine_reports_residuals():
    local = np.array([[0, 0], [100, 0], [0, 100], [100, 100]], float)
    world = local + [400000, 5600000]
    world[3] += [0.3, -0.4]  # one bad control point
    t = fit_control_points(local, world)
    assert t.kind == "affine"
    assert t.rms > 0 and t.residuals.shape == (4,)

def test_roundtrip_dict():
    t = fit_control_points(np.array([[0, 0], [1, 0.0]]), np.array([[10, 10], [11, 10.0]]))
    assert Transform2D.from_dict(t.to_dict()).apply(np.array([[2, 0.0]])) == pytest.approx(np.array([[12, 10]]))

def test_rejects_single_point():
    with pytest.raises(ValueError):
        fit_control_points(np.array([[0, 0.0]]), np.array([[1, 1.0]]))

def test_rejects_coincident_local_points():
    with pytest.raises(ValueError):
        fit_control_points(np.array([[1, 1], [1, 1.0]]), np.array([[0, 0], [5, 5.0]]))

