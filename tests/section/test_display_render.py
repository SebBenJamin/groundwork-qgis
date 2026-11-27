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

    from groundwork_geophysics.core.colors import ColorScale
    from groundwork_geophysics.core.model import Dataset
    from groundwork_geophysics.section.data import LayerStyle, SectionLayer

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
    from groundwork_geophysics.section.data import SectionSnapshot
    from groundwork_geophysics.section.profile_source import WorkbenchProfileGenerator

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
    from groundwork_geophysics.core.colors import ColorScale
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
    from groundwork_geophysics.section.data import identify_layers
    layer = _layer("smooth")
    [hit] = identify_layers([layer], 60.2, -1.5)
    assert hit["value"] == pytest.approx(60.5)                      # the cell's value, not 60.2


def test_blank_removes_contours_in_low_coverage(qgis_app):
    cov = lambda m: np.where(m.vertices[m.cells[:, 0], 0] < 65.0, -5.0, 0.0)   # noqa: E731
    res = _results(_layer("smooth+contours", coverage=cov, contour_step=10.0,
                          fade_coverage=True, coverage_threshold=-2.0, fade_mode="blank"))
    img = _img(res)
    assert (_rgb(img, _x(60), _y(-2.5)) == 255).all()               # line at 60: blanked
    assert (_rgb(img, _x(70), _y(-2.5)) < 200).any()                # line at 70: drawn


def test_field_does_not_overshoot_empty_cells(qgis_app):
    from groundwork_geophysics.section.data import SectionLayer
    layer = _layer("smooth", grid_cell=1.5)
    vals = layer.mesh.values.copy()
    x0 = layer.mesh.vertices[layer.mesh.cells[:, 0], 0]
    vals[(x0 >= 59.0) & (x0 < 62.0)] = np.nan                       # empty cells s 59..62
    layer = SectionLayer(layer.dataset, replace(layer.mesh, values=vals), layer.style, None)
    img = _img(_results(layer))
    assert (_rgb(img, _x(61.8), _y(-1.5)) == 255).all()             # node 62.22 overshoots


def test_smooth_field_fills_up_to_a_higher_ground(qgis_app):
    res = _results(_layer("smooth"), topo=(np.array([0.0, 200.0]), np.array([0.6, 0.6])))
    img = _img(res)
    assert np.abs(_rgb(img, _x(60.5), _y(0.3)) - _expected(60.5)).max() <= 12   # mesh top is 0
    assert (_rgb(img, _x(60.5), _y(0.8)) == 255).all()                          # above ground


def test_cells_are_grouped_by_colour_once_per_look(qgis_app, monkeypatch):
    # every pan or zoom builds the drawing again: a 2-million-cell model took 1.3 s each time
    from groundwork_geophysics.section import data, display_render
    calls = []
    real = data.cell_path_groups
    monkeypatch.setattr(data, "cell_path_groups",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    display_render._cache.clear()
    layer = _layer("cells")
    first = display_render.build_drawing(layer, None)
    again = display_render.build_drawing(layer, None)
    assert len(calls) == 1 and again.groups is first.groups
    other = replace(layer, style=replace(layer.style, opacity=0.5))     # opacity: no regroup
    display_render.build_drawing(other, None)
    assert len(calls) == 1
    recoloured = replace(layer, style=replace(layer.style, scale=replace(
        layer.style.scale, vmax=60.0)))
    display_render.build_drawing(recoloured, None)
    assert len(calls) == 2


def test_display_cache_key_follows_the_gridding_method():
    from groundwork_geophysics.core.interpolators import Interpolation
    from groundwork_geophysics.section.display_render import _key
    a = _layer()
    b = replace(a, style=replace(a.style, interpolation=Interpolation(method="idw")))
    assert _key(a, None, (10, 10)) != _key(b, None, (10, 10))


def test_the_smooth_field_uses_the_layers_method():
    from groundwork_geophysics.core.interpolators import Interpolation
    from groundwork_geophysics.section.display_render import _gridded
    layer = _layer()
    near = replace(layer, style=replace(layer.style, interpolation=Interpolation(
        method="nearest", anisotropy=1.0)))
    linear_image, _rect = _gridded(layer, None, None)[0]
    near_image, _rect = _gridded(near, None, None)[0]
    assert linear_image != near_image


def test_smooth_field_reaches_the_ground_line_without_a_gap(qgis_app):
    # drawn smoothly, the nodes above the ground fade the field out below it: the field takes
    # the colour of its top node up to the ground, where the clip cuts it
    for cell in (0.5, 0.3):
        for ground in (0.5, 0.0, 0.2):
            res = _results(_layer("smooth", grid_cell=cell),
                           topo=(np.array([0.0, 200.0]), np.array([ground, ground])))
            img = _img(res)
            below = _rgb(img, _x(60.5), _y(ground) + 2)                     # 4 cm below
            assert np.abs(below - _expected(60.5)).max() <= 12, (cell, ground, below)
            assert (_rgb(img, _x(60.5), _y(ground) - 2) == 255).all()      # above: empty


def test_a_blanked_top_is_not_filled_up_to_the_ground(qgis_app):
    cov = lambda m: np.where(m.vertices[m.cells[:, 0], 1] >= -1.0, -5.0, 0.0)   # noqa: E731
    res = _results(_layer("smooth", coverage=cov, fade_coverage=True, coverage_threshold=-2.0,
                          fade_mode="blank", grid_cell=0.3))
    img = _img(res)
    assert (_rgb(img, _x(60.5), _y(-0.3)) == 255).all()             # low coverage: blank
    assert (_rgb(img, _x(60.5), _y(0.3)) == 255).all()              # and nothing above it
