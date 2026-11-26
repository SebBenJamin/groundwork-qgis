"""The section view never scrolls: viewport pixels are scene pixels, so what the tools draw
lands under the cursor. Overlay items reaching outside the plot (a sketch vertex far outside
the view, the hidden 3D cursor ring at the origin) used to grow the scene and shift the view."""
from qgis.PyQt.QtCore import QPoint, QPointF

from test_interp_tools import dock  # noqa: F401


def _settle(qgis_app):
    for _ in range(20):
        qgis_app.processEvents()


def _assert_under_cursor(dock):
    from groundwork_geophysics.section.interp_tools import SketchItem
    canvas = dock.canvas
    sketch = SketchItem(canvas)
    try:
        # a vertex far outside the visible range reaches far outside the plot area
        sketch.show([(10.0, -2.0), (50000.0, -90000.0)])
        canvas.viewport().update()
        assert canvas.horizontalScrollBar().value() == 0
        assert canvas.verticalScrollBar().value() == 0
        assert canvas.mapToScene(QPoint(100, 100)) == QPointF(100, 100)
        pos = QPointF(canvas.plotArea().center())      # a mouse position, viewport pixels
        pp = canvas.canvasPointToPlotPoint(pos)
        sketch.show([(pp.distance(), pp.elevation())])
        vertex = sketch.item.path().boundingRect().center()   # its ring, scene coordinates
        on_screen = canvas.viewportTransform().map(vertex)
        assert abs(on_screen.x() - pos.x()) <= 0.5 and abs(on_screen.y() - pos.y()) <= 0.5
    finally:
        sketch.remove()


def test_sketch_lands_under_cursor(qgis_app, dock):
    _settle(qgis_app)
    _assert_under_cursor(dock)


def test_sketch_lands_under_cursor_after_resize(qgis_app, dock):
    _settle(qgis_app)
    dock.resize(800, 420)
    _settle(qgis_app)
    _assert_under_cursor(dock)
    dock.resize(1200, 600)
    _settle(qgis_app)
    _assert_under_cursor(dock)
