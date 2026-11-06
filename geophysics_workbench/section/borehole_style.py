"""How borehole intervals look: a QGIS feature renderer stored in the project per interval table.

QGIS cannot keep a renderer on a table without geometry, so the renderer the user builds in
the Borehole style window (QGIS's own style editor) is kept here as renderer XML in the
project. The gatherer resolves one cloned symbol per interval on the main thread; the section
and the viewer draw those clones. Without a renderer, or when it fails, every distinct text
gets a neutral colour of its own (``label_colour``): nothing is guessed from the words."""
from __future__ import annotations

from qgis.core import (QgsFeatureRenderer, QgsFillSymbol,
                       QgsMessageLog, QgsReadWriteContext, QgsRenderContext, Qgis)
from qgis.PyQt.QtXml import QDomDocument

from ..core.lithology import label_colour

STYLE_SCOPE = "geophysics_workbench"
LOG_TAG = "Geophysics Workbench"
OUTLINE_MM = 0.15


def style_key(log_layer_id: str) -> str:
    return f"borehole_style/{log_layer_id}"


def save_renderer(project, log_layer_id: str, renderer: QgsFeatureRenderer | None) -> None:
    """Store ``renderer`` for the interval table ``log_layer_id``; ``None`` removes it."""
    if renderer is None:
        project.removeEntry(STYLE_SCOPE, style_key(log_layer_id))
        return
    doc = QDomDocument("borehole_style")
    doc.appendChild(renderer.save(doc, QgsReadWriteContext()))
    project.writeEntry(STYLE_SCOPE, style_key(log_layer_id), doc.toString())


def load_renderer(project, log_layer_id: str) -> QgsFeatureRenderer | None:
    text, ok = project.readEntry(STYLE_SCOPE, style_key(log_layer_id), "")
    if not ok or not text:
        return None
    doc = QDomDocument()
    parsed = doc.setContent(text)
    if not (parsed[0] if isinstance(parsed, tuple) else parsed):
        return None
    return QgsFeatureRenderer.load(doc.documentElement(), QgsReadWriteContext())


def default_symbol(text: str) -> QgsFillSymbol:
    """The neutral look of an unstyled interval: a colour of its own per text."""
    r, g, b = label_colour(text)
    return QgsFillSymbol.createSimple({"color": f"{r},{g},{b}", "outline_color": "0,0,0",
                                       "outline_width": str(OUTLINE_MM),
                                       "outline_width_unit": "MM"})


def used_attributes(renderer, fields) -> set[str]:
    """Fields ``renderer`` reads (so the gatherer requests them); empty when it cannot tell."""
    if renderer is None:
        return set()
    try:
        ctx = QgsRenderContext()
        r = renderer.clone()
        r.startRender(ctx, fields)
        try:
            return set(r.usedAttributes(ctx))
        finally:
            r.stopRender(ctx)
    except Exception:
        return set()


def interval_symbols(renderer, fields, features, texts) -> list[tuple]:
    """(cloned fill symbol, feature) per feature; ``texts`` give the neutral fallback per
    feature. A renderer that fails or gives no symbol falls back for that feature only."""
    symbols = [None] * len(features)
    if renderer is not None:
        ctx = QgsRenderContext()
        try:
            r = renderer.clone()
            r.startRender(ctx, fields)
            try:
                for i, f in enumerate(features):
                    ctx.expressionContext().setFeature(f)
                    found = r.symbolsForFeature(f, ctx)
                    sym = found[0] if found else None
                    if isinstance(sym, QgsFillSymbol) and r.willRenderFeature(f, ctx):
                        symbols[i] = sym.clone()
            finally:
                r.stopRender(ctx)
        except Exception as exc:                  # a broken style never breaks the column
            QgsMessageLog.logMessage(f"Borehole style failed, default colours used: "
                                     f"{type(exc).__name__}: {exc}", LOG_TAG,
                                     Qgis.MessageLevel.Warning)
            symbols = [None] * len(features)
    return [(sym or default_symbol(text), f)
            for sym, f, text in zip(symbols, features, texts)]

