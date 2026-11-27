"""The smooth field is painted with smooth scaling: zoomed in, the colours run between the
grid nodes instead of standing as squares, and the model's edge does not take a dark fringe
from the transparent nodes beyond it."""
import numpy as np


def _rgba(image) -> np.ndarray:
    from qgis.PyQt.QtGui import QImage
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    raw = np.frombuffer(image.constBits().asstring(image.sizeInBytes()), np.uint8)
    return raw.reshape(image.height(), image.bytesPerLine())[:, :image.width() * 4] \
        .reshape(image.height(), image.width(), 4).astype(int)


def _field(pixels):
    """A LayerDrawing whose field is ``pixels`` (rows, cols, 4 uint8) over s 0 .. cols m and
    z 0 .. rows m (one metre a node)."""
    from qgis.PyQt.QtCore import QRectF
    from qgis.PyQt.QtGui import QImage

    from groundwork_geophysics.section.display_render import LayerDrawing
    a = np.ascontiguousarray(np.asarray(pixels, np.uint8))
    rows, cols = a.shape[:2]
    img = QImage(a.tobytes(), cols, rows, cols * 4, QImage.Format.Format_RGBA8888).copy()
    return LayerDrawing(opacity=1.0, field=(img, QRectF(0.0, 0.0, float(cols), float(rows))))


def _paint(drawing, cols, rows, px_per_m=50):
    from qgis.core import QgsRenderContext
    from qgis.PyQt.QtGui import QColor, QImage, QPainter, QTransform

    from groundwork_geophysics.section.profile_source import paint_layers
    w, h = cols * px_per_m, rows * px_per_m
    img = QImage(w, h, QImage.Format.Format_ARGB32)
    img.fill(QColor(255, 255, 255))
    painter = QPainter(img)
    try:
        wt = QTransform(px_per_m, 0.0, 0.0, -px_per_m, 0.0, rows * px_per_m)
        paint_layers(painter, [drawing], wt, QgsRenderContext.fromQPainter(painter))
    finally:
        painter.end()
    return _rgba(img)


def test_zoomed_in_the_field_runs_between_its_nodes(qgis_app):
    red, blue = (255, 0, 0, 255), (0, 0, 255, 255)
    px = _paint(_field([[red, blue]]), 2, 1)            # two nodes, 50 px each
    row = px[25, :, :3]
    # half way between the node centres (x 25 and 75) the colour is a blend, not red or blue
    mid = row[50]
    assert 60 < mid[0] < 200 and 60 < mid[2] < 200, mid
    # and it changes step by step, not in one jump at x 50
    reds = row[25:76, 0]
    assert len(np.unique(reds)) > 10


def test_the_edge_next_to_empty_nodes_takes_no_dark_fringe(qgis_app):
    # the transparent node carries black colour values: they must not show
    green, empty = (0, 200, 0, 255), (0, 0, 0, 0)
    px = _paint(_field([[green, empty]]), 2, 1)
    row = px[25, :, :3]
    # every painted pixel lies between the green and the white background, never darker
    assert (row[:, 1] >= 199).all(), row[:, 1].min()
    assert (row[:, 0] == row[:, 2]).all()               # grey-free: only white and green mix


def test_the_field_image_is_premultiplied(qgis_app):
    # an edge node made transparent keeps its scale colour in the RGBA values; premultiplied,
    # that colour is gone before the image is scaled
    from types import SimpleNamespace

    from qgis.PyQt.QtGui import QImage

    from groundwork_geophysics.section.display_render import _field_image
    grid = SimpleNamespace(values=np.zeros((1, 2)), s=np.array([0.0, 1.0]), z=np.array([0.0]))
    rgba = np.array([[[0, 200, 0, 255], [255, 0, 255, 0]]], np.uint8)
    img, _rect = _field_image(grid, rgba)
    assert img.format() == QImage.Format.Format_RGBA8888_Premultiplied
    assert _rgba(img)[0, 1].tolist() == [0, 0, 0, 0]
    px = _paint(_field(rgba), 2, 1)                     # unpremultiplied, Qt still copes
    assert (px[25, :, 1] >= 199).all()
