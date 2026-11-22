"""Section pictures for the 3D view: a model painted by the section's own drawing code, as the
panel shows it, over its own extent at a resolution that keeps long lines affordable."""
from dataclasses import replace

import numpy as np
import pytest


def test_the_resolution_drops_for_long_lines_and_long_pictures_come_in_pieces():
    from groundwork_geophysics.section.picture import MAX_PX, layout
    ppm, cuts = layout(0.0, 50.0, 170.0, 180.0)
    assert ppm == 100 and list(cuts) == [0.0, 50.0]               # Erfurt: 5000 x 1000 px
    ppm, cuts = layout(0.0, 720.0, 0.0, 60.0)                     # a long refraction line
    assert ppm == pytest.approx((8e6 / (720 * 60)) ** 0.5)
    assert all((b - a) * ppm <= MAX_PX for a, b in zip(cuts, cuts[1:]))
    assert cuts[0] == 0.0 and cuts[-1] == 720.0


def _layer(provider, p, mode):
    layer = provider.layers(p.id)[0]
    provider.set_style(layer.dataset.id, replace(provider.style(layer.dataset.id), mode=mode))
    return provider.layers(p.id)[0], provider.surface(p.id).line


def _pixel(picture, s, z):
    img = picture.image
    col = int((s - picture.s0) / (picture.s1 - picture.s0) * img.width())
    row = int((picture.z1 - z) / (picture.z1 - picture.z0) * img.height())
    c = img.pixelColor(min(col, img.width() - 1), min(row, img.height() - 1))
    return c.red(), c.green(), c.blue(), c.alpha()


def test_a_cells_picture_has_the_section_colours(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.picture import section_pictures
    st, p, _ = store_with_model
    provider = SectionDataProvider(st)
    layer, topo = _layer(provider, p, "cells")
    pictures = section_pictures(layer, topo)
    assert len(pictures) == 1
    mesh = layer.mesh
    i = len(mesh.cells) // 2
    corners = mesh.vertices[[k for k in mesh.cells[i] if k >= 0]]
    s, z = corners.mean(axis=0)
    want = layer.style.scale.rgba([mesh.values[i]])[0]
    r, g, b, a = _pixel(pictures[0], s, z)
    assert a == 255 and (r, g, b) == pytest.approx(tuple(int(c) for c in want[:3]), abs=3)


def _base():
    from qgis.PyQt.QtGui import QGuiApplication, QPalette
    c = QGuiApplication.palette().color(QPalette.ColorRole.Base)
    return c.red(), c.green(), c.blue()


def test_the_texture_is_opaque_on_the_panels_background(qgis_app, store_with_model):
    """QGIS draws tiled-scene textures opaque (alpha ignored): the picture is flattened onto
    the colour the section is drawn on, and ``alpha`` keeps where something was painted."""
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.picture import section_pictures
    st, p, _ = store_with_model
    provider = SectionDataProvider(st)
    layer, topo = _layer(provider, p, "smooth")
    picture = section_pictures(layer, topo)[0]
    assert picture.alpha.max() == 255                            # the field is painted
    assert not picture.image.hasAlphaChannel()
    s = (picture.s0 + picture.s1) / 2
    ground = float(np.interp(s, *topo))
    if ground < picture.z1 - 0.5:
        z = (ground + picture.z1) / 2
        row = int((picture.z1 - z) / (picture.z1 - picture.z0) * picture.image.height())
        col = int((s - picture.s0) / (picture.s1 - picture.s0) * picture.image.width())
        assert picture.alpha[row, col] == 0
        assert _pixel(picture, s, z)[:3] == _base()


def test_contours_alone_are_lines_on_the_background_not_black(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.picture import section_pictures
    st, p, _ = store_with_model
    provider = SectionDataProvider(st)
    picture = section_pictures(*_layer(provider, p, "contours"))[0]
    rows, cols = np.nonzero(picture.alpha == 0)
    for r, c in list(zip(rows, cols))[::max(1, len(rows) // 50)]:
        colour = picture.image.pixelColor(int(c), int(r))
        assert (colour.red(), colour.green(), colour.blue()) == _base()


def test_a_faint_model_is_blended_with_the_background(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.picture import section_pictures
    st, p, _ = store_with_model
    provider = SectionDataProvider(st)
    layer = provider.layers(p.id)[0]
    did = layer.dataset.id
    provider.set_style(did, replace(provider.style(did), mode="cells", opacity=0.4))
    layer, topo = provider.layers(p.id)[0], provider.surface(p.id).line
    picture = section_pictures(layer, topo)[0]
    mesh = layer.mesh
    i = len(mesh.cells) // 2
    s, z = mesh.vertices[[k for k in mesh.cells[i] if k >= 0]].mean(axis=0)
    want = layer.style.scale.rgba([mesh.values[i]])[0][:3]
    blend = tuple(0.4 * int(c) + 0.6 * b for c, b in zip(want, _base()))
    assert _pixel(picture, s, z)[:3] == pytest.approx(blend, abs=4)


def test_contours_are_drawn_into_the_picture(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.picture import section_pictures
    st, p, _ = store_with_model
    provider = SectionDataProvider(st)
    smooth = section_pictures(*_layer(provider, p, "smooth"))[0].image
    both = section_pictures(*_layer(provider, p, "smooth+contours"))[0].image
    assert smooth.size() == both.size() and smooth != both


# -- several models of a profile in one picture, and its interpretation -----------------------
def _shifted(layer, ds):
    from dataclasses import replace as dc_replace
    return dc_replace(layer, mesh=layer.mesh.with_x(lambda x: x + ds))


def _cell_centre(layer, i=None):
    mesh = layer.mesh
    i = len(mesh.cells) // 2 if i is None else i
    s, z = mesh.vertices[[k for k in mesh.cells[i] if k >= 0]].mean(axis=0)
    return i, float(s), float(z)


def test_several_models_share_one_picture_over_their_joint_extent(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.picture import section_pictures
    st, p, _ = store_with_model
    provider = SectionDataProvider(st)
    first, topo = _layer(provider, p, "cells")
    second = _shifted(first, 30.0)
    pictures = section_pictures([first, second], None)
    s0, s1, _z0, _z1 = first.mesh.bounds()
    assert pictures[0].s0 == pytest.approx(s0) and pictures[-1].s1 == pytest.approx(s1 + 30.0)
    i, s, z = _cell_centre(second)
    want = second.style.scale.rgba([second.mesh.values[i]])[0]
    picture = next(pic for pic in pictures if pic.s0 <= s <= pic.s1)
    assert _pixel(picture, s, z)[:3] == pytest.approx(tuple(int(c) for c in want[:3]), abs=3)


def test_the_later_model_is_drawn_over_the_earlier_one_with_its_opacity(qgis_app,
                                                                       store_with_model):
    """Stacked as the section draws them: bottom first, each with its own opacity."""
    from dataclasses import replace as dc_replace

    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.picture import section_pictures
    st, p, _ = store_with_model
    provider = SectionDataProvider(st)
    first, topo = _layer(provider, p, "cells")
    over = dc_replace(first, style=dc_replace(first.style, opacity=0.5),
                      mesh=dc_replace(first.mesh, values=first.mesh.values[::-1].copy()))
    picture = section_pictures([first, over], None)[0]
    i, s, z = _cell_centre(first)
    below = first.style.scale.rgba([first.mesh.values[i]])[0][:3]
    above = first.style.scale.rgba([over.mesh.values[i]])[0][:3]
    blend = tuple(0.5 * int(a) + 0.5 * int(b) for a, b in zip(above, below))
    assert _pixel(picture, s, z)[:3] == pytest.approx(blend, abs=4)
    alone = section_pictures(first, None)[0]                     # one layer still works
    assert _pixel(alone, s, z)[:3] == pytest.approx(tuple(int(c) for c in below), abs=3)


def _green_polygon(s0, s1, z0, z1):
    from qgis.core import QgsFillSymbol

    from groundwork_geophysics.core.interpretation import InterpFeature, InterpPiece
    piece = InterpPiece("pc", "v", "f1", "prof", "polygon",
                        [(s0, z1), (s1, z1), (s1, z0), (s0, z0)])
    symbol = QgsFillSymbol.createSimple({"color": "0,200,0,255", "outline_style": "no"})
    return [piece], {"f1": InterpFeature("f1", "v", name="")}, {"pc": symbol}


def test_the_interpretation_is_painted_over_the_models(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.picture import section_pictures
    st, p, _ = store_with_model
    provider = SectionDataProvider(st)
    layer, topo = _layer(provider, p, "cells")
    _i, s, z = _cell_centre(layer)
    interp = _green_polygon(s - 2, s + 2, z - 1, z + 1)
    picture = section_pictures([layer], topo, interp)[0]
    assert _pixel(picture, s, z)[:3] == pytest.approx((0, 200, 0), abs=3)
    plain = section_pictures([layer], topo)[0]
    assert _pixel(plain, s, z)[:3] != pytest.approx((0, 200, 0), abs=3)


def test_an_interpretation_past_the_models_widens_the_picture(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.picture import section_pictures
    st, p, _ = store_with_model
    provider = SectionDataProvider(st)
    layer, topo = _layer(provider, p, "cells")
    s0, s1, z0, _z1 = layer.mesh.bounds()
    interp = _green_polygon(s1 - 1, s1 + 4, z0 - 3, z0 + 1)
    pictures = section_pictures([layer], topo, interp)
    assert pictures[-1].s1 == pytest.approx(s1 + 4) and pictures[0].z0 == pytest.approx(z0 - 3)
    picture = pictures[-1]
    assert _pixel(picture, s1 + 2, z0 - 2)[:3] == pytest.approx((0, 200, 0), abs=3)
    rows = picture.image.height()
    assert picture.alpha[int(rows * 0.99), -2] == 255             # painted: shown in 3D
