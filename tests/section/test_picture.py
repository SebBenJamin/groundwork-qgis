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
    assert ppm == pytest.approx((32e6 / (720 * 60)) ** 0.5)
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


def test_above_the_ground_the_picture_is_clear(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.picture import section_pictures
    st, p, _ = store_with_model
    provider = SectionDataProvider(st)
    layer, topo = _layer(provider, p, "smooth")
    picture = section_pictures(layer, topo)[0]
    alpha = np.frombuffer(picture.image.constBits().asstring(picture.image.sizeInBytes()),
                          np.uint8).reshape(picture.image.height(), -1, 4)[..., 3]
    assert alpha.max() == 255                                    # the field is painted
    s = (picture.s0 + picture.s1) / 2
    ground = float(np.interp(s, *topo))
    if ground < picture.z1 - 0.5:
        assert _pixel(picture, s, (ground + picture.z1) / 2)[3] == 0


def test_contours_are_drawn_into_the_picture(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.picture import section_pictures
    st, p, _ = store_with_model
    provider = SectionDataProvider(st)
    smooth = section_pictures(*_layer(provider, p, "smooth"))[0].image
    both = section_pictures(*_layer(provider, p, "smooth+contours"))[0].image
    assert smooth.size() == both.size() and smooth != both
