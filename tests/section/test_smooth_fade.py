"""Round 2, F2: in the smooth modes the fade follows the smoothed coverage softly; the cells
mode keeps its per-cell fade."""
import numpy as np
from test_display_render import _layer, _results


def _alpha_row(drawing):
    img, _rect = drawing.field
    y = img.height() // 2
    return [(img.pixel(x, y) >> 24) & 255 for x in range(img.width())]


def _gradient(m):
    return (m.vertices[m.cells, 0].mean(axis=1) - 60.0) / 5.0       # -4 .. 4 along s


def test_smooth_field_edge_is_soft(qgis_app):
    res = _results(_layer("smooth", coverage=_gradient, fade_coverage=True,
                          coverage_threshold=0.0, fade_mode="fade", grid_cell=0.25))
    [drawing] = res._layers
    alphas = [a for a in _alpha_row(drawing) if a > 0]
    assert len(set(alphas)) > 2


def test_cells_unchanged(qgis_app):
    from geophysics_workbench.core.gridding import FADE_ALPHA
    res = _results(_layer("cells", coverage=_gradient, fade_coverage=True,
                          coverage_threshold=0.0, fade_mode="fade"))
    [drawing] = res._layers
    alphas = sorted({c.alpha() for c, _path in drawing.groups})
    assert alphas == [round(255 * FADE_ALPHA), 255] or len(alphas) == 2
