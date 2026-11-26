"""Section pictures for the 3D view: a profile's models painted by the section's own drawing
code (cells, smooth field, contour lines and labels, each model's opacity and coverage fade,
stacked bottom first as the panel stacks them) over their joint extent, optionally with the
interpretation over them as the panel draws it, on the panel's background colour: QGIS draws
a tiled scene's textures opaque, so a see-through texel would show black. Long pictures come
in pieces a graphics card can take."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from qgis.core import QgsRenderContext
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QImage, QPainter, QTransform

PX_PER_M = 100                  # pixels per metre, along and across
MAX_PIXELS = 8_000_000          # per model: long lines get coarser instead of heavier
#: (each picture is held by the graphics card, and decoded again for every 2D map redraw)
MAX_PX = 8192                   # the longest side of one piece
LABEL_SHARE = 1 / 25            # contour label text height as a share of the picture height


@dataclass
class Picture:
    image: QImage               # opaque (RGB), row 0 at z1, column 0 at s0
    alpha: np.ndarray           # (rows, columns) where the section painted something, 0-255
    s0: float
    s1: float
    z0: float
    z1: float


def layout(s0: float, s1: float, z0: float, z1: float) -> tuple[float, np.ndarray]:
    """(pixels per metre, chainages where the pieces meet, ends included)."""
    area = max((s1 - s0) * (z1 - z0), 1e-9)
    ppm = min(PX_PER_M, math.sqrt(MAX_PIXELS / area))
    pieces = max(1, math.ceil((s1 - s0) * ppm / MAX_PX))
    return ppm, np.linspace(s0, s1, pieces + 1)


def extent(mesh, topo) -> tuple[float, float, float, float]:
    """(s0, s1, z0, z1) a model's picture covers: the mesh, raised to the ground above it
    (the smooth field fills up to the surface)."""
    return _raised(mesh.bounds(), topo)


def _raised(bounds, topo) -> tuple[float, float, float, float]:
    """``bounds`` (s0, s1, z0, z1) raised to the ground above them."""
    s0, s1, z0, z1 = (float(v) for v in bounds)
    if topo is not None and len(topo[0]) > 1:
        ts, tz = (np.asarray(a, float) for a in topo)
        inside = (ts >= s0) & (ts <= s1)
        ends = np.interp([s0, s1], ts, tz)
        z1 = max(z1, float(ends.max()), float(tz[inside].max()) if inside.any() else z1)
    return s0, s1, z0, z1


def joint_extent(layers, topo, pieces=()) -> tuple[float, float, float, float]:
    """(s0, s1, z0, z1) of several models' pictures together, widened to the interpretation
    ``pieces`` drawn over them. A trace section counts with its picture's box; a layer that
    failed does not count."""
    from .data import layer_bounds
    boxes = [_raised(b, topo) for b in map(layer_bounds, layers) if b is not None]
    for piece in pieces:
        v = np.asarray(piece.vertices, float).reshape(-1, 2)
        if len(v):
            boxes.append((v[:, 0].min(), v[:, 0].max(), v[:, 1].min(), v[:, 1].max()))
    return (float(min(b[0] for b in boxes)), float(max(b[1] for b in boxes)),
            float(min(b[2] for b in boxes)), float(max(b[3] for b in boxes)))


def section_pictures(layers, topo, interpretation=None, base=None) -> list[Picture]:
    """``layers`` (one section layer with a mesh, or a profile's several, bottom first) as
    the panel draws them, in pieces; ``interpretation`` (pieces, features, symbols as in the
    section's snapshot) is painted over them, names included; on the colour ``base`` (a
    QColor; None: the panel's, read here, so only on the main thread)."""
    from .display_render import LABEL_MM, build_drawing
    layers = list(layers) if isinstance(layers, (list, tuple)) else [layers]
    drawings = [build_drawing(layer, topo) for layer in layers]
    pieces = list(interpretation[0]) if interpretation else []
    s0, s1, z0, z1 = joint_extent(layers, topo, pieces)
    ppm, cuts = layout(s0, s1, z0, z1)
    label_px = LABEL_SHARE * (z1 - z0) * ppm
    out = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        painted = _paint(drawings, interpretation if pieces else None, a, b, z0, z1, ppm,
                         label_px / LABEL_MM)
        out.append(Picture(_flatten(painted, base), _alpha(painted), float(a), float(b),
                           z0, z1))
    return out


def _alpha(image: QImage) -> np.ndarray:
    raw = np.frombuffer(image.constBits().asstring(image.sizeInBytes()), np.uint8)
    rows = raw.reshape(image.height(), image.bytesPerLine())
    return rows[:, :image.width() * 4].reshape(image.height(), image.width(), 4)[..., 3].copy()


def panel_colour():
    """The colour the section panel is drawn on (main thread)."""
    from qgis.PyQt.QtGui import QGuiApplication, QPalette
    return QGuiApplication.palette().color(QPalette.ColorRole.Base)


def _flatten(image: QImage, base=None) -> QImage:
    """``image`` on ``base`` (the panel's colour when None), without transparency."""
    out = QImage(image.size(), QImage.Format.Format_RGB888)
    out.fill(base if base is not None else panel_colour())
    painter = QPainter(out)
    try:
        painter.drawImage(0, 0, image)
    finally:
        painter.end()
    return out


def _paint(drawings, interpretation, s0, s1, z0, z1, ppm: float, px_per_mm: float) -> QImage:
    from .profile_source import paint_layers
    w = max(2, min(MAX_PX, round((s1 - s0) * ppm)))
    h = max(2, min(MAX_PX, round((z1 - z0) * ppm)))
    image = QImage(w, h, QImage.Format.Format_RGBA8888)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        sx, sz = w / (s1 - s0), h / (z1 - z0)
        wt = QTransform(sx, 0.0, 0.0, -sz, -s0 * sx, z1 * sz)
        rc = QgsRenderContext.fromQPainter(painter)
        rc.setScaleFactor(px_per_mm)
        paint_layers(painter, drawings, wt, rc)
        if interpretation is not None:
            from .interp_render import draw_interpretation
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            draw_interpretation(painter, rc, wt, *interpretation)
    finally:
        painter.end()
    return image
