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


CURVE_STYLES_KEY = "borehole_curve_styles"


def curve_styles(project) -> dict:
    """The user's curve styles by curve key; unusable entries are skipped."""
    import json
    from dataclasses import fields

    from ..core.borehole_curves import CurveStyle
    text, ok = project.readEntry(STYLE_SCOPE, CURVE_STYLES_KEY, "")
    try:
        data = json.loads(text) if ok and text else {}
    except ValueError:
        return {}
    out = {}
    names = {f.name for f in fields(CurveStyle)}
    for key, value in (data.items() if isinstance(data, dict) else []):
        if isinstance(value, dict):
            try:
                out[key] = CurveStyle(**{k: v for k, v in value.items() if k in names})
            except TypeError:
                continue
    return out


def save_curve_styles(project, styles: dict) -> None:
    import json
    from dataclasses import asdict
    project.writeEntry(STYLE_SCOPE, CURVE_STYLES_KEY,
                       json.dumps({k: asdict(v) for k, v in styles.items()}))


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


def broken_rules(renderer) -> list[str]:
    """Filter expressions of a rule-based renderer that do not parse (never handed to
    QGIS for drawing: a broken rule must not take the section down)."""
    from qgis.core import QgsExpression
    if renderer is None or renderer.type() != "RuleRenderer":
        return []
    out, todo = [], list(renderer.rootRule().children())
    while todo:
        rule = todo.pop()
        expr = rule.filterExpression()
        if expr and not rule.isElse() and QgsExpression(expr).hasParserError():
            out.append(expr)
        todo.extend(rule.children())
    return out


class IntervalStyler:
    """A stored style prepared once for one interval table: copied and started once, its
    used fields known, and one symbol copy per class (intervals of the same class share it).
    Use as a context manager around all boreholes of a gather. Any failure, or rules that
    do not parse, give the neutral default colours (logged once)."""

    def __init__(self, renderer, fields):
        self.fields = fields
        self.ctx = QgsRenderContext()
        self.renderer = None
        self.used: set[str] = set()
        self._copies: dict[frozenset, object] = {}
        self._defaults: dict[str, object] = {}
        broken = broken_rules(renderer)
        if broken:
            _warn(f"Borehole style has rules that do not parse ({broken[0]!r}); "
                  f"default colours used.")
        elif renderer is not None:
            self.renderer = renderer.clone()

    def __enter__(self):
        if self.renderer is not None:
            try:
                self.renderer.startRender(self.ctx, self.fields)
                self.used = set(self.renderer.usedAttributes(self.ctx)) & set(
                    self.fields.names())
            except Exception as exc:
                _warn(f"Borehole style failed, default colours used: "
                      f"{type(exc).__name__}: {exc}")
                self.renderer = None
        return self

    def __exit__(self, *_exc):
        if self.renderer is not None:
            try:
                self.renderer.stopRender(self.ctx)
            except Exception:
                pass
        return False

    def _default(self, text: str):
        if text not in self._defaults:
            self._defaults[text] = default_symbol(text)
        return self._defaults[text]

    def symbols(self, features, texts) -> list[tuple]:
        """(fill symbol, feature) per feature; shared copies per class and per text."""
        out = []
        for f, text in zip(features, texts):
            sym = None
            if self.renderer is not None:
                try:
                    self.ctx.expressionContext().setFeature(f)
                    found = self.renderer.symbolsForFeature(f, self.ctx)
                    cls = found[0] if found else None
                    if isinstance(cls, QgsFillSymbol) and \
                            self.renderer.willRenderFeature(f, self.ctx):
                        # QGIS's own key for the class (stable; Python wrapper ids are not)
                        key = frozenset(self.renderer.legendKeysForFeature(f, self.ctx))
                        if not key:
                            sym = cls.clone()
                        else:
                            if key not in self._copies:
                                self._copies[key] = cls.clone()
                            sym = self._copies[key]
                except Exception as exc:          # a broken style never breaks the column
                    _warn(f"Borehole style failed, default colours used: "
                          f"{type(exc).__name__}: {exc}")
                    self.renderer = None
            out.append((sym or self._default(text), f))
        return out


def _warn(message: str) -> None:
    QgsMessageLog.logMessage(message, LOG_TAG, Qgis.MessageLevel.Warning)


def interval_symbols(renderer, fields, features, texts) -> list[tuple]:
    """(fill symbol, feature) per feature, for one batch (``IntervalStyler`` for many)."""
    with IntervalStyler(renderer, fields) as styler:
        return styler.symbols(features, texts)
