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
from ..ids import LEGACY_ID, NAME

STYLE_SCOPE = LEGACY_ID
LOG_TAG = NAME
OUTLINE_MM = 0.15


CURVE_STYLES_KEY = "borehole_curve_styles"


def curve_styles(project, settings=None) -> dict:
    """The user's curve styles by curve key; unusable entries are skipped. With the Context
    layers ``settings``, each of their curves nobody styled yet gets its own colour
    (``default_curve_styles``)."""
    saved = _saved_curve_styles(project)
    if settings is None:
        return saved
    out = default_curve_styles(settings, project)
    out.update(saved)
    return out


#: QGIS's own colour scheme for curves when the project sets no default colour ramp
CURVE_SCHEME, CURVE_SCHEME_COLOURS = "Dark2", 8
FILL_ALPHA_HEX = "40"


def _curve_colours(project, n: int) -> list[str]:
    """``n`` colours "#rrggbb" from the project's default colour ramp, else ColorBrewer's
    Dark2 (dark enough for a thin line on white); repeated after eight."""
    from qgis.core import QgsColorBrewerColorRamp
    ramp = None
    try:
        ramp = project.styleSettings().defaultColorRamp()
    except AttributeError:
        ramp = None
    if ramp is None:
        ramp = QgsColorBrewerColorRamp(CURVE_SCHEME, CURVE_SCHEME_COLOURS)
    steps = CURVE_SCHEME_COLOURS
    return [ramp.color((i % steps) / (steps - 1)).name() for i in range(n)]


def default_curve_styles(settings, project) -> dict:
    """A style per curve of the Context layers ``settings`` (in their order), each in its own
    colour, its fill the same colour see-through."""
    from ..core.borehole_curves import CurveStyle
    from ..core.context_settings import curve_key
    keys = list(dict.fromkeys(curve_key(t.layer_id, c.field) for b in settings.boreholes
                              for t in b.curve_tables for c in t.curves))
    return {k: CurveStyle(colour=c, fill_colour=c + FILL_ALPHA_HEX)
            for k, c in zip(keys, _curve_colours(project, len(keys)))}


def _saved_curve_styles(project) -> dict:
    import json
    from dataclasses import fields

    from ..core.borehole_curves import CurveStyle
    text, ok = project.readEntry(STYLE_SCOPE, CURVE_STYLES_KEY, "")
    try:
        data = json.loads(text) if ok and text else {}
    except ValueError:
        return {}
    out = {}
    for key, value in (data.items() if isinstance(data, dict) else []):
        if isinstance(key, str) and isinstance(value, dict):
            out[key] = _checked_style(value)
    return out


def _checked_style(data: dict):
    """A CurveStyle from saved values, each checked; a wrong value gives its default (a
    hand-edited project must never break the drawing)."""
    import math
    import re

    from ..core.borehole_curves import DASHES, FILLS, CurveStyle
    d = CurveStyle()

    def colour(v, default):
        return v if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}([0-9a-fA-F]{2})?", v) \
            else default

    def number(v, default, lo=-math.inf, hi=math.inf):
        ok = isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) \
            and lo <= v <= hi
        return float(v) if ok else default

    return CurveStyle(
        colour=colour(data.get("colour"), d.colour),
        width_mm=number(data.get("width_mm"), d.width_mm, 0.05, 5.0),
        dash=data.get("dash") if data.get("dash") in DASHES else d.dash,
        fill=data.get("fill") if data.get("fill") in FILLS else d.fill,
        fill_colour=colour(data.get("fill_colour"), d.fill_colour),
        log=data.get("log") if isinstance(data.get("log"), bool) else d.log,
        vmin=number(data.get("vmin"), None), vmax=number(data.get("vmax"), None))


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


def empty_symbol() -> QgsFillSymbol:
    """An interval of a class the user switched off: no fill, a thin outline only."""
    return QgsFillSymbol.createSimple({"style": "no", "outline_color": "0,0,0",
                                       "outline_width": str(OUTLINE_MM),
                                       "outline_width_unit": "MM"})


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
        self._hidden_symbol = None
        self._all_on = None
        broken = broken_rules(renderer)
        if broken:
            _warn(f"Borehole style has rules that do not parse ({broken[0]!r}); "
                  f"default colours used.")
        elif renderer is not None:
            self.renderer = renderer.clone()
            # the same style with every class ticked: tells "switched off" from "no class"
            self._all_on = renderer.clone()
            for item in self._all_on.legendSymbolItems():
                if item.isCheckable():
                    self._all_on.checkLegendSymbolItem(item.ruleKey(), True)

    def __enter__(self):
        if self.renderer is not None:
            try:
                self.renderer.startRender(self.ctx, self.fields)
                self._all_on.startRender(self.ctx, self.fields)
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
                self._all_on.stopRender(self.ctx)
            except Exception:
                pass
        return False

    def _switched_off(self, feature) -> bool:
        """The feature has a class, but the user unticked it in the legend."""
        keys = self._all_on.legendKeysForFeature(feature, self.ctx)
        return any(not self.renderer.legendSymbolItemChecked(k) for k in keys)

    def _hidden(self):
        if self._hidden_symbol is None:
            self._hidden_symbol = empty_symbol()
        return self._hidden_symbol

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
                    drawn = self.renderer.willRenderFeature(f, self.ctx)
                    if (cls is None or not drawn) and self._switched_off(f):
                        sym = self._hidden()          # a class the user switched off
                    elif isinstance(cls, QgsFillSymbol) and drawn:
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
