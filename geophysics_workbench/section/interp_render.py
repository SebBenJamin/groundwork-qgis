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


def _fallback(kind: str):
    """A symbol that never hides the model: an outline without fill for polygons."""
    if kind == "polygon":
        return QgsFillSymbol.createSimple({"style": "no", "outline_style": "solid"})
    return _DEFAULT[kind].createSimple({})


def piece_symbols(pieces, features, layers: dict, twins: dict | None = None) -> dict:
    """piece id -> (cloned QgsSymbol, QgsFeature with the layer's fields) from the derived
    layer's renderer (main thread only); the feature drives data-defined properties.
    ``twins`` maps a frozen version's feature id to the current version's feature with the
    same letter and type: frozen copies have new ids, and the layer style is keyed by id."""
    out = {}
    twins = twins or {}
    for p in pieces:
        layer = layers.get(LAYER_BY_KIND[p.kind])
        sym = None
        qf = _feature_for(layer.fields(), features.get(p.feature_id), p) \
            if layer is not None else QgsFeature()
        if layer is not None and layer.renderer() is not None:
            look_up = QgsFeature(qf)
            twin = twins.get(p.feature_id)
            if twin and layer.fields().indexOf("feature_id") >= 0:
                look_up["feature_id"] = twin
            rc = QgsRenderContext()
            renderer = layer.renderer().clone()
            renderer.startRender(rc, layer.fields())
            try:
                syms = renderer.symbolsForFeature(look_up, rc)
                sym = syms[0].clone() if syms else None
            finally:
                renderer.stopRender(rc)
        out[p.id] = (sym or _fallback(p.kind), QgsFeature(qf))
    return out


def twin_features(frozen_features, current_features) -> dict:
    """frozen feature id -> current feature id with the same (letter, type)."""
    current = {(f.letter, f.type): f.id for f in current_features}
    return {f.id: current[(f.letter, f.type)] for f in frozen_features
            if (f.letter, f.type) in current}


COMPARE_OPACITY = 0.35


def draw_interpretation(painter, rc, wt, pieces, features, symbols, compare=None) -> None:
    """``pieces`` with their symbols and letters; ``compare`` (a frozen version's pieces)
    first, faint and without letters."""
    if compare:
        painter.save()
        painter.setOpacity(COMPARE_OPACITY)
        try:
            _draw_pieces(painter, rc, wt, compare, {}, symbols)
        finally:
            painter.restore()
    _draw_pieces(painter, rc, wt, pieces, features, symbols)


def _draw_pieces(painter, rc, wt, pieces, features, symbols) -> None:
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


CROSS_FILL_ALPHA = 110          # polygon bars stay translucent over the tie strip
CROSS_POINT_MM = 1.6


def _mark_colour(symbols, piece_id: str) -> QColor | None:
    entry = symbols.get(piece_id)
    if entry is None:
        return None
    sym = entry[0] if isinstance(entry, tuple) else entry
    colour = QColor(sym.color())
    colour.setAlpha(255)
    return colour


def draw_crossing_marks(painter, rc, wt, crossings, points, features, symbols,
                        views=None) -> None:
    """A crossing profile's interpretation at the tie, over its strip (``strip_start``, as
    ``draw_ties``): polygons as bars, lines as ticks, points as diamonds, with letters."""
    from qgis.PyQt.QtCore import QRectF, Qt
    from qgis.PyQt.QtGui import QBrush, QPainter

    from .context_readout import strip_start
    from .context_render import TIE_STRIP_WIDTH, mm
    from ..core.context import ContextItems
    from .context_render_points import column_px, right_extent_px
    items = ContextItems(borehole_views=dict(views or {}))

    width = mm(rc, TIE_STRIP_WIDTH)
    px_per_m = abs(wt.map(QPointF(1.0, 0.0)).x() - wt.map(QPointF(0.0, 0.0)).x()) or 1.0
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    font = QFont(painter.font())
    font.setBold(True)
    font.setPixelSize(max(8, round(mm(rc, LETTER_SIZE_MM * 0.8))))
    painter.setFont(font)
    for s, marks in crossings:
        start = strip_start(points, s, width / px_per_m,
                            lambda q: column_px(rc, items, q) / 2 / px_per_m,
                            lambda q: right_extent_px(items, q) / px_per_m)
        x0 = wt.map(QPointF(start, 0.0)).x()
        x1 = x0 + width
        for m in marks:
            colour = _mark_colour(symbols, m.piece_id)
            if colour is None:
                continue
            y0 = wt.map(QPointF(s, m.z_top)).y()
            y1 = wt.map(QPointF(s, m.z_bottom)).y()
            pen = QPen(colour, max(1.0, mm(rc, 0.5)))
            painter.setPen(pen)
            if m.kind == "polygon":
                fill = QColor(colour)
                fill.setAlpha(CROSS_FILL_ALPHA)
                painter.setBrush(QBrush(fill))
                painter.drawRect(QRectF(QPointF(x0, min(y0, y1)), QPointF(x1, max(y0, y1))))
            elif m.kind == "line":
                ext = mm(rc, 1.0)
                painter.drawLine(QPointF(x0 - ext, y0), QPointF(x1 + ext, y0))
            else:
                r = mm(rc, CROSS_POINT_MM) / 2
                cx = (x0 + x1) / 2
                painter.setBrush(QBrush(colour))
                painter.drawPolygon(QPolygonF([QPointF(cx, y0 - r), QPointF(cx + r, y0),
                                               QPointF(cx, y0 + r), QPointF(cx - r, y0)]))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            feat = features.get(m.feature_id)
            if feat is not None and feat.letter:
                painter.drawText(QPointF(x1 + 2, min(y0, y1) + font.pixelSize()), feat.letter)
    painter.restore()
