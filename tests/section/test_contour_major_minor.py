"""Round 2, F3: typed major levels are drawn labelled and at the usual width, minor levels
thinner and unlabelled; plates draw the same levels."""
from test_display_render import _layer, _results


def test_minor_drawn_thin_without_label(qgis_app):
    from geophysics_workbench.section.display_render import (CONTOUR_MINOR_PEN_MM,
                                                             CONTOUR_PEN_MM, contour_pen_mm)
    res = _results(_layer("contours", contour_major=(60.0,), contour_minor=(50.0,)))
    [drawing] = res._layers
    got = sorted((c[3], c[4]) for c in drawing.contours)
    assert got == [("", False), ("60", True)]
    assert contour_pen_mm(True) == CONTOUR_PEN_MM == 0.25
    assert contour_pen_mm(False) == CONTOUR_MINOR_PEN_MM == 0.13


def test_auto_contours_all_major(qgis_app):
    res = _results(_layer("contours", contour_step=10.0))
    [drawing] = res._layers
    assert [c[4] for c in drawing.contours] == [True, True, True]


def test_plate_follows_levels(qgis_app, store_with_model):
    from geophysics_workbench.core.plates import FrameLook, ModelLook
    from geophysics_workbench.section.data import SectionDataProvider
    st, p, _ = store_with_model
    [d] = [d for d in st.datasets(p.id)][:1]
    look = FrameLook([ModelLook(d.id, mode="contours", contour_major=[100.0],
                                contour_minor=[50.0])])
    snap = SectionDataProvider(st).snapshot(p.id, look=look)
    [la] = [la for la in snap.layers if la.dataset.id == d.id]
    assert la.style.contour_major == (100.0,) and la.style.contour_minor == (50.0,)
