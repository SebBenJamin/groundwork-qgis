import numpy as np
import pytest

from groundwork_geophysics.core.colors import COLORMAPS, ColorScale


def test_log_scale_endpoints_and_nan():
    cs = ColorScale("gray", 10, 1000, log=True)
    rgba = cs.rgba(np.array([10, 100, 1000, np.nan]))
    assert rgba.dtype == np.uint8
    assert rgba[0, :3].tolist() == [0, 0, 0] and rgba[2, :3].tolist() == [255, 255, 255]
    assert abs(int(rgba[1, 0]) - 128) <= 1        # 100 is mid-way on a log scale
    assert rgba[3, 3] == 0


def test_clipping_and_non_positive_on_log():
    cs = ColorScale("gray", 10, 1000, log=True)
    rgba = cs.rgba(np.array([1.0, 1e6, 0.0, -5.0]))
    assert rgba[0].tolist() == [0, 0, 0, 255]
    assert rgba[1].tolist() == [255, 255, 255, 255]
    assert rgba[2, 3] == 0 and rgba[3, 3] == 0
    lin = ColorScale("gray", 0, 10, log=False).rgba(np.array([-5.0, 0.0, 20.0]))
    assert lin[:, 3].tolist() == [255, 255, 255]
    assert lin[0, 0] == 0 and lin[2, 0] == 255


def test_auto_uses_percentiles():
    cs = ColorScale.auto(np.r_[np.full(98, 50.0), 1e-3, 1e6])
    assert 40 < cs.vmin <= 50 <= cs.vmax < 60


def test_auto_degenerate_and_empty():
    cs = ColorScale.auto(np.full(5, 100.0))
    assert cs.vmin == pytest.approx(100 / 1.1) and cs.vmax == pytest.approx(110)
    lin = ColorScale.auto(np.full(5, 0.0), log=False)
    assert (lin.vmin, lin.vmax) == (-1.0, 1.0)
    lin = ColorScale.auto(np.full(5, 10.0), log=False)
    assert (lin.vmin, lin.vmax) == pytest.approx((9.0, 11.0))
    with pytest.raises(ValueError):
        ColorScale.auto(np.array([np.nan, -1.0, 0.0]))


def test_unknown_colormap_and_roundtrip():
    with pytest.raises(ValueError, match="Spectral_r"):
        ColorScale("nope")
    cs = ColorScale("turbo", 2.0, 50.0, False)
    assert ColorScale.from_dict(cs.to_dict()) == cs
    assert "viridis" in COLORMAPS


def test_scale_validation():
    with pytest.raises(ValueError):
        ColorScale("gray", 5, 5)
    with pytest.raises(ValueError):
        ColorScale("gray", 10, 1)
    with pytest.raises(ValueError):
        ColorScale("gray", 0, 10, log=True)
    ColorScale("gray", -5, 5, log=False)
