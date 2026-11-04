"""Display modes on the section: smooth field, contours, coverage fade."""
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "core"))


def _layer(mode="smooth", coverage=None, mirror=False, **style):
    from test_gridding import regular_mesh

    from geophysics_workbench.core.colors import ColorScale
    from geophysics_workbench.core.model import Dataset
    from geophysics_workbench.section.data import LayerStyle, SectionLayer

    mesh = regular_mesh(40, 3, fn=lambda s, z: s, x0=40.0, z0=-3.0)    # s 40..80, z -3..0
    if coverage is not None:
        mesh = replace(mesh, coverage=coverage(mesh))
    if mirror:
        mesh = mesh.with_x(lambda x: 120.0 - x)
    ds = Dataset("d1", "p1", "s1", "ert_model", "m.vtk", 0.0, "", "vtk_legacy", {}, {},
                 name="M")
    st = LayerStyle(scale=ColorScale("Spectral_r", 40.0, 80.0, False), mode=mode, **style)
    return SectionLayer(ds, mesh, st, None)


def _results(layer, topo=(np.array([0.0, 200.0]), np.array([0.5, 0.5]))):
    from geophysics_workbench.section.data import SectionSnapshot
    from geophysics_workbench.section.profile_source import WorkbenchProfileGenerator

    class Owner:
        last_results = None

    gen = WorkbenchProfileGenerator(SectionSnapshot("p1", [layer], topo, [], None, None),
                                    Owner())
    assert gen.generateProfile()
    return gen.takeResults()


def _img(results):
    from test_beyond_stations import _render
    return _render(results)


def _x(s):
    return int(round(10.0 * s - 400.0))


def _y(z):
    return int(round(50.0 - 50.0 * z))


def _rgb(img, x, y):
    from qgis.PyQt.QtGui import QColor
    c = QColor(img.pixel(x, y))
    return np.array([c.red(), c.green(), c.blue()])


def _expected(value):
    from geophysics_workbench.core.colors import ColorScale
    return ColorScale("Spectral_r", 40.0, 80.0, False).rgba([value])[0][:3].astype(int)


def test_smooth_layer_draws_field(qgis_app):
    res = _results(_layer("smooth"))
    [drawing] = res._layers
    assert drawing.field is not None and drawing.groups == []
    img = _img(res)
    assert np.abs(_rgb(img, _x(60.5), _y(-1.5)) - _expected(60.5)).max() <= 12


def test_smooth_without_topography(qgis_app):
    res = _results(_layer("smooth"), topo=None)
    img = _img(res)
    assert np.abs(_rgb(img, _x(60.5), _y(-1.5)) - _expected(60.5)).max() <= 12


def test_smooth_field_stays_below_topography(qgis_app):
    res = _results(_layer("smooth"), topo=(np.array([0.0, 200.0]), np.array([-1.0, -1.0])))
    img = _img(res)
    assert (_rgb(img, _x(60.5), _y(-0.5)) == 255).all()             # above ground: empty
    assert np.abs(_rgb(img, _x(60.5), _y(-2.0)) - _expected(60.5)).max() <= 12


def test_smooth_layer_mirrors(qgis_app):
    img = _img(_results(_layer("smooth", mirror=True)))
    assert np.abs(_rgb(img, _x(45.5), _y(-1.5)) - _expected(74.5)).max() <= 12


def test_contours_drawn_with_label(qgis_app):
    res = _results(_layer("contours", contour_step=10.0))
    [drawing] = res._layers
    assert drawing.field is None
    assert [c[3] for c in drawing.contours] == ["50", "60", "70"]
    img = _img(res)
    assert (_rgb(img, _x(60), _y(-2.5)) < 200).any()                # a line at s = 60
    assert (_rgb(img, _x(55), _y(-2.5)) == 255).all()               # nothing between lines


def test_fade_blank_clears_low_coverage(qgis_app):
    cov = lambda m: np.where(m.vertices[m.cells[:, 0], 0] < 50.0, -5.0, 0.0)   # noqa: E731
    for mode in ("cells", "smooth"):
        res = _results(_layer(mode, coverage=cov, fade_coverage=True, coverage_threshold=-2.0,
                              fade_mode="blank"))
        img = _img(res)
        assert (_rgb(img, _x(45.5), _y(-1.5)) == 255).all(), mode
        assert np.abs(_rgb(img, _x(65.5), _y(-1.5)) - _expected(65.5)).max() <= 12, mode


def test_readout_uses_mesh_value_in_smooth_mode(qgis_app):
    from geophysics_workbench.section.data import identify_layers
    layer = _layer("smooth")
    [hit] = identify_layers([layer], 60.2, -1.5)
    assert hit["value"] == pytest.approx(60.5)                      # the cell's value, not 60.2
