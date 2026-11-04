"""Interpretation pieces drawn on the section with their QGIS layer symbols.

Symbols are resolved on the main thread (``piece_symbols``) from the derived layers' renderers
and travel in the snapshot as clones, so the map, the section and later the plates share one
style. Letters are drawn at ``label_point`` in the symbol's colour.
"""
from __future__ import annotations

from qgis.core import (Qgis, QgsFeature, QgsField, QgsFields, QgsFillSymbol, QgsLineSymbol,
                       QgsMarkerSymbol, QgsRenderContext, QgsSymbol)
from qgis.PyQt.QtCore import QMetaType, QPointF
from qgis.PyQt.QtGui import QColor, QFont, QPen, QPolygonF

from ..core.interpretation import label_point

LETTER_SIZE_MM = 3.5
LAYER_BY_KIND = {"polygon": "interp_polygons_3d", "line": "interp_lines_3d",
                 "point": "interp_points_3d"}
_DEFAULT = {"polygon": QgsFillSymbol, "line": QgsLineSymbol, "point": QgsMarkerSymbol}


def _feature_for(fields, feat, piece=None) -> QgsFeature:
    f = QgsFeature(fields)
    if piece is not None:
        for name, value in (("feature_id", piece.feature_id), ("piece_id", piece.id),
                            ("profile_id", piece.profile_id), ("version_id", piece.version_id)):
            if fields.indexOf(name) >= 0:
                f[name] = value
    if feat is not None:
        for name in ("type", "letter", "confidence", "note", "author"):
            if fields.indexOf(name) >= 0:
                f[name] = getattr(feat, name)
        for k, v in feat.extra.items():
            if fields.indexOf(k) >= 0:
                f[k] = v
    return f


def piece_symbols(pieces, features, layers: dict) -> dict:
    """piece id -> (cloned QgsSymbol, QgsFeature with the layer's fields) from the derived
    layer's renderer (main thread only); the feature drives data-defined properties."""
    out = {}
    for p in pieces:
        layer = layers.get(LAYER_BY_KIND[p.kind])
        sym = None
        qf = _feature_for(layer.fields(), features.get(p.feature_id), p)             if layer is not None else QgsFeature()
        if layer is not None and layer.renderer() is not None:
            rc = QgsRenderContext()
            renderer = layer.renderer().clone()
            renderer.startRender(rc, layer.fields())
            try:
                syms = renderer.symbolsForFeature(qf, rc)
                sym = syms[0].clone() if syms else None
            finally:
                renderer.stopRender(rc)
        out[p.id] = (sym or _DEFAULT[p.kind].createSimple({}), QgsFeature(qf))
    return out


def draw_interpretation(painter, rc, wt, pieces, features, symbols) -> None:
    for p in pieces:
        entry = symbols.get(p.id)
        if entry is None:
            continue
        sym, feature = entry if isinstance(entry, tuple) else (entry, None)
        if feature is None or not feature.fields().count():
            fields = QgsFields()
            fields.append(QgsField("letter", QMetaType.Type.QString))
            feature = QgsFeature(fields)
        pts = QPolygonF([wt.map(QPointF(float(s), float(z))) for s, z in p.vertices])
        rc.expressionContext().setFeature(feature)
        rc.expressionContext().setFields(feature.fields())
        sym.startRender(rc, feature.fields())
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
            colour = QColor(sym.color())
            colour.setAlpha(255)                    # fills are translucent, letters never
            painter.setPen(QPen(colour, 1))
            painter.drawText(at + QPointF(3, -3), feat.letter)
            painter.restore()
