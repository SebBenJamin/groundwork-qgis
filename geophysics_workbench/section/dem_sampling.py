"""Sample a QGIS raster layer (a DEM) along a profile or at one point. Main thread only."""
from __future__ import annotations

import math

import numpy as np
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY, QgsProject

MAX_SAMPLES = 2000
MIN_STEP = 0.5          # metres
_DEG_TO_M = 111_320.0


def _transform(from_authid: str, layer, project):
    src = QgsCoordinateReferenceSystem(from_authid)
    if src == layer.crs():
        return None
    return QgsCoordinateTransform(src, layer.crs(), project or QgsProject.instance())


def _value(provider, x: float, y: float) -> float:
    value, ok = provider.sample(QgsPointXY(x, y), 1)
    return float(value) if ok and math.isfinite(value) else math.nan


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
    provider = layer.dataProvider()
    z = np.empty(len(s))
    for i, (x, y) in enumerate(xy):
        if ct is not None:
            p = ct.transform(QgsPointXY(float(x), float(y)))
            x, y = p.x(), p.y()
        z[i] = _value(provider, float(x), float(y))
    return None if np.isnan(z).all() else (s, z)


def sample_point(layer, x: float, y: float, crs_authid: str, project=None) -> float | None:
    ct = _transform(crs_authid, layer, project)
    if ct is not None:
        p = ct.transform(QgsPointXY(x, y))
        x, y = p.x(), p.y()
    v = _value(layer.dataProvider(), x, y)
    return None if math.isnan(v) else v
