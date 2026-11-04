"""Interpretation pieces drawn on the section with their QGIS layer symbols.

Symbols are resolved on the main thread (``piece_symbols``) from the derived layers' renderers
and travel in the snapshot as clones, so the map, the section and later the plates share one
style. Letters are drawn at ``label_point`` in the symbol's colour.
"""
from __future__ import annotations

from qgis.core import (Qgis, QgsFeature, QgsField, QgsFields, QgsFillSymbol, QgsLineSymbol,
                       QgsMarkerSymbol, QgsRenderContext, QgsSymbol)
from qgis.PyQt.QtCore import QMetaType, QPointF
from qgis.PyQt.QtGui import QFont, QPen, QPolygonF

from ..core.interpretation import label_point

LETTER_SIZE_MM = 3.5
LAYER_BY_KIND = {"polygon": "interp_polygons_3d", "line": "interp_lines_3d",
                 "point": "interp_points_3d"}
_DEFAULT = {"polygon": QgsFillSymbol, "line": QgsLineSymbol, "point": QgsMarkerSymbol}


def _feature_for(fields, feat) -> QgsFeature:
    f = QgsFeature(fields)
    if feat is not None:
        for name in ("type", "letter", "confidence", "note"):
            if fields.indexOf(name) >= 0:
                f[name] = getattr(feat, name)
        for k, v in feat.extra.items():
            if fields.indexOf(k) >= 0:
                f[k] = v
    return f


def piece_symbols(pieces, features, layers: dict) -> dict:
    """piece id -> cloned QgsSymbol from the derived layer's renderer (main thread only)."""
    out = {}
    for p in pieces:
        layer = layers.get(LAYER_BY_KIND[p.kind])
        sym = None
        if layer is not None and layer.renderer() is not None:
            rc = QgsRenderContext()
            renderer = layer.renderer().clone()
            renderer.startRender(rc, layer.fields())
            try:
                syms = renderer.symbolsForFeature(_feature_for(layer.fields(),
                                                               features.get(p.feature_id)), rc)
                sym = syms[0].clone() if syms else None
            finally:
                renderer.stopRender(rc)
        out[p.id] = sym or _DEFAULT[p.kind].createSimple({})
    return out


def draw_interpretation(painter, rc, wt, pieces, features, symbols) -> None:
    fields = QgsFields()
    fields.append(QgsField("letter", QMetaType.Type.QString))
    for p in pieces:
        sym: QgsSymbol | None = symbols.get(p.id)
        if sym is None:
            continue
        pts = QPolygonF([wt.map(QPointF(float(s), float(z))) for s, z in p.vertices])
        feature = QgsFeature(fields)
        sym.startRender(rc, fields)
        try:
            if p.kind == "polygon":
                sym.renderPolygon(pts, None, feature, rc)
            elif p.kind == "line":
                sym.renderPolyline(pts, feature, rc)
            else:
                sym.renderPoint(pts[0], feature, rc)
        finally:
            sym.stopRender(rc)
        feat = features.get(p.feature_id)
        if feat is not None and feat.letter:
            s, z = label_point(p)
            at = wt.map(QPointF(s, z))
            font = QFont(painter.font())
            font.setBold(True)
            font.setPixelSize(max(8, round(rc.convertToPainterUnits(LETTER_SIZE_MM,
                                                                    Qgis.RenderUnit.Millimeters))))
            painter.save()
            painter.setFont(font)
            painter.setPen(QPen(sym.color(), 1))
            painter.drawText(at + QPointF(3, -3), feat.letter)
            painter.restore()
