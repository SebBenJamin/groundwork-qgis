"""QGIS colour ramps for colour scales (main thread only: QGIS objects).

A scale keeps its ramp as QGIS XML (to edit it again) and a 256-colour table that drawing
uses; scales from before (only a matplotlib ``cmap`` name) open with the matching QGIS ramp
and keep drawing exactly as before until the user picks a ramp."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
from qgis.core import QgsGradientColorRamp, QgsGradientStop, QgsStyle, QgsSymbolLayerUtils
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtXml import QDomDocument

LUT_SIZE = 256
#: old matplotlib names -> (QGIS default-style ramp, inverted); None: sampled from matplotlib
_QGIS_NAME = {"Spectral_r": ("Spectral", True), "viridis": ("Viridis", False),
              "RdYlBu_r": ("RdYlBu", True), "gray": ("Greys", True),
              "turbo": (None, False), "jet": (None, False)}


def _from_matplotlib(name: str):
    from matplotlib import colormaps
    rgba = np.rint(colormaps[name](np.linspace(0.0, 1.0, 11)) * 255).astype(int)
    colours = [QColor(int(r), int(g), int(b), int(a)) for r, g, b, a in rgba]
    stops = [QgsGradientStop(i / 10.0, c) for i, c in enumerate(colours[1:-1], start=1)]
    return QgsGradientColorRamp(colours[0], colours[-1], False, stops)


def ramp_for_cmap(name: str):
    """The QGIS ramp that matches an old colour-map name."""
    qgis_name, inverted = _QGIS_NAME.get(name, (None, False))
    ramp = QgsStyle.defaultStyle().colorRamp(qgis_name) if qgis_name else None
    if ramp is None:
        return _from_matplotlib(name)
    if inverted:
        ramp.invert()
    return ramp


def ramp_xml(ramp) -> str:
    doc = QDomDocument()
    doc.appendChild(QgsSymbolLayerUtils.saveColorRamp("ramp", ramp, doc))
    return doc.toString()


def ramp_from_xml(text: str):
    doc = QDomDocument()
    if not text or not doc.setContent(text):
        return None
    return QgsSymbolLayerUtils.loadColorRamp(doc.documentElement())


def ramp_lut(ramp, n: int = LUT_SIZE) -> tuple:
    out = []
    for i in range(n):
        c = ramp.color(i / (n - 1))
        out.append((c.red(), c.green(), c.blue(), c.alpha()))
    return tuple(out)


def scale_ramp(scale):
    """The QGIS ramp a scale shows: the user's, else the one matching its old name."""
    return ramp_from_xml(scale.ramp) if scale.ramp else ramp_for_cmap(scale.cmap)


def with_ramp(scale, ramp):
    """``scale`` drawn with the QGIS ``ramp``."""
    return replace(scale, ramp=ramp_xml(ramp), lut=ramp_lut(ramp))
