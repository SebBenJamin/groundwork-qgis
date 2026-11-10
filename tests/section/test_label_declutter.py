"""Usability round 1, Task 6: labels never overlap — on the section, in the borehole viewer and
on plates (same code). A label with no free room is left out (its item stays; hover reads it)."""
import random

import numpy as np


def _overlaps(placed):
    for i, (a0, a1, ra) in enumerate(placed):
        for b0, b1, rb in placed[i + 1:]:
            if ra == rb and a0 < b1 and b0 < a1:
                return True
    return False


def test_place_labels_never_overlaps():
    from geophysics_workbench.section.context_render import place_labels
    rnd = random.Random(7)
    for _ in range(50):
        spans = []
        for _ in range(30):
            x = rnd.uniform(0, 500)
            spans.append((x, x + rnd.uniform(20, 120), rnd.randint(0, 4)))
        rows = place_labels(spans, 3)
        placed = [(s[0], s[1], r) for s, r in zip(spans, rows) if r is not None]
        assert not _overlaps(placed)
        assert all(r is None or 0 <= r < 3 for r in rows)


def test_more_important_labels_win():
    from geophysics_workbench.section.context_render import place_labels
    spans = [(0, 100, 3), (10, 110, 0)]               # the second is more important
    assert place_labels(spans, 1) == [None, 0]


def test_section_labels_do_not_overlap(qgis_app):
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtGui import QImage, QPainter, QTransform

    from geophysics_workbench.core.context import ContextItems, ProjectedPoint
    from geophysics_workbench.section.context_render import plan_labels, set_label_font
    img = QImage(800, 400, QImage.Format.Format_ARGB32)
    painter = QPainter(img)
    try:
        rc = QgsRenderContext.fromQPainter(painter)
        wt = QTransform(10, 0, 0, -10, 0, 200)        # 10 px per metre, z up
        items = ContextItems(points=[ProjectedPoint(10 + 0.3 * i, 0.5, f"EN-RK {40 + i}",
                                                    "point") for i in range(8)])
        surface = (np.array([0.0, 80.0]), np.array([0.0, 0.0]))
        plan = plan_labels(painter, rc, wt, items, surface)
        set_label_font(painter, rc)
        fm = painter.fontMetrics()
        placed = [(lab.x - fm.horizontalAdvance(lab.text) / 2,
                   lab.x + fm.horizontalAdvance(lab.text) / 2, round(lab.y)) for lab in plan.values()]
        assert placed and not _overlaps(placed)
        assert len(plan) < 8                           # some are left out, none drawn on top
    finally:
        painter.end()


def test_viewer_drops_overlapping_labels_keeps_highlight():
    from geophysics_workbench.section.borehole_viewer import choose_viewer_labels
    spans = [(100.0, 160.0), (110.0, 170.0), (300.0, 360.0)]
    assert choose_viewer_labels(spans, highlight=1) == [False, True, True]
