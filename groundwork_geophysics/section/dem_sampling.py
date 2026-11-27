"""Sample a QGIS raster layer (a DEM) along a profile or at one point, interpolated between
pixel centres (bilinear); where a neighbour that counts has no data, the nearest pixel is
taken (nothing where that one has none). Main thread only."""
from __future__ import annotations

import math

import numpy as np
from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY,
                       QgsProject, QgsRectangle)

MAX_SAMPLES = 2000
MIN_STEP = 0.5          # metres
_DEG_TO_M = 111_320.0
#: a neighbour weighing less than this does not count (a point on a pixel centre or edge)
_NO_WEIGHT = 1e-9


def _transform(from_authid: str, layer, project):
    src = QgsCoordinateReferenceSystem(from_authid)
    if src == layer.crs():
        return None
    return QgsCoordinateTransform(src, layer.crs(), project or QgsProject.instance())


def _nearest(provider, x: float, y: float) -> float:
    value, ok = provider.sample(QgsPointXY(x, y), 1)
    return float(value) if ok and math.isfinite(value) else math.nan


def _block_values(provider, extent: QgsRectangle) -> np.ndarray:
    """The 2 × 2 pixel values of band 1 in ``extent`` (rows from the top), NaN for nodata
    and for pixels off the raster."""
    block = provider.block(1, extent, 2, 2)
    out = np.full((2, 2), np.nan)
    if block is None or not block.isValid():
        return out
    for r in range(2):
        for c in range(2):
            if not block.isNoData(r, c):
                v = block.value(r, c)
                if math.isfinite(v):
                    out[r, c] = v
    return out


def _value(layer, x: float, y: float) -> float:
    """The height at (x, y) in the layer's CRS: bilinear between the four pixel centres
    around the point; the nearest pixel when one of them that counts has no data (or lies
    off the raster); NaN where that one has none."""
    provider = layer.dataProvider()
    xres, yres = abs(layer.rasterUnitsPerPixelX()), abs(layer.rasterUnitsPerPixelY())
    ext = layer.extent()
    if not (xres > 0 and yres > 0):
        return _nearest(provider, x, y)
    col = (x - ext.xMinimum()) / xres - 0.5           # in pixel centres from the top left
    row = (ext.yMaximum() - y) / yres - 0.5
    c0, r0 = math.floor(col), math.floor(row)
    fx, fy = col - c0, row - r0
    box = QgsRectangle(ext.xMinimum() + c0 * xres, ext.yMaximum() - (r0 + 2) * yres,
                       ext.xMinimum() + (c0 + 2) * xres, ext.yMaximum() - r0 * yres)
    values = _block_values(provider, box)
    weights = np.array([[(1 - fx) * (1 - fy), fx * (1 - fy)], [(1 - fx) * fy, fx * fy]])
    counts = weights > _NO_WEIGHT
    if np.isnan(values[counts]).any():
        return _nearest(provider, x, y)
    return float((weights[counts] * values[counts]).sum() / weights[counts].sum())


def pixel_size_m(layer) -> float:
    size = max(abs(layer.rasterUnitsPerPixelX()), abs(layer.rasterUnitsPerPixelY()))
    return size * _DEG_TO_M if layer.crs().isGeographic() else size


def sample_profile(layer, chainage, crs_authid: str, project=None):
    """``(s, z)`` along ``chainage`` (store CRS) every ``max(pixel size, 0.5 m)``, at most
    2000 samples; nodata and points outside the raster are NaN. ``None`` when all are NaN."""
    step = max(pixel_size_m(layer), MIN_STEP)
    n = min(int(math.ceil(chainage.length / step)) + 1, MAX_SAMPLES)
    s = np.linspace(0.0, chainage.length, max(n, 2))
    xy = chainage.to_xy(s)
    ct = _transform(crs_authid, layer, project)
    z = np.empty(len(s))
    for i, (x, y) in enumerate(xy):
        if ct is not None:
            p = ct.transform(QgsPointXY(float(x), float(y)))
            x, y = p.x(), p.y()
        z[i] = _value(layer, float(x), float(y))
    return None if np.isnan(z).all() else (s, z)


def sample_point(layer, x: float, y: float, crs_authid: str, project=None) -> float | None:
    ct = _transform(crs_authid, layer, project)
    if ct is not None:
        p = ct.transform(QgsPointXY(x, y))
        x, y = p.x(), p.y()
    v = _value(layer, x, y)
    return None if math.isnan(v) else v
