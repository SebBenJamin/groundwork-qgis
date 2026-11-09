"""Plate layout items: a tunable colour bar for one model of one frame, and a legend of the
borehole classes (and curves) shown in a plate's frames.

Both are ordinary layout items: movable, resizable, kept in the project and in templates.
The colour bar keeps QGIS's own colour-ramp legend settings (orientation, direction, number
format, prefix/suffix, text format) plus its tick choice, title and unit. QGIS's registry can
add item types but not remove them: they are registered once per QGIS session."""
from __future__ import annotations

import math

import numpy as np
from qgis.core import (Qgis, QgsApplication, QgsColorRampLegendNodeSettings,
                       QgsLayoutItem, QgsLayoutItemAbstractMetadata, QgsLayoutItemRegistry,
                       QgsNumericFormatContext, QgsRenderContext,
                       QgsTextFormat, QgsTextRenderer)
from qgis.PyQt.QtCore import QPointF, QRectF, Qt
from qgis.PyQt.QtGui import QColor, QPen, QPolygonF

from ..core.borehole_curves import CurveStyle

COLOUR_BAR_TYPE = QgsLayoutItemRegistry.PluginItem + 4712
BOREHOLE_LEGEND_TYPE = QgsLayoutItemRegistry.PluginItem + 4713
STEPS = 96
_metadata: list = []                    # keeps the registered metadata alive
_provider = None                        # the section data provider (set by the plugin)
#: every live plate item's Python object. A Python subclass of a QGIS item lives as long as
#: something in Python holds it; the layout (C++) owning the item does not count, so without
#: this the item turns into a plain QgsLayoutItem (draws nothing, saved without its settings)
#: as soon as Python lets go of the layout. Dropped when QGIS deletes the item.
_alive: dict[int, object] = {}


def _keep_alive(item) -> None:
    key = id(item)
    _alive[key] = item
    item.destroyed.connect(lambda _obj=None, k=key: _alive.pop(k, None))


def current_provider():
    """The provider of the plugin as loaded now. Read through ``sys.modules``: QGIS keeps the
    item classes registered first until it restarts, so after a plugin reinstall the old
    classes would otherwise read the old module's (cleared) provider."""
    import sys
    module = sys.modules.get(__name__)
    return getattr(module, "_provider", None) if module is not None else _provider


def set_context_provider(provider) -> None:
    """The provider the items read sections and styles from (None when no store)."""
    global _provider
    _provider = provider


# -- colour bar ----------------------------------------------------------------------------
def colour_bar_ticks(vmin: float, vmax: float, log: bool, spec: str) -> list[float]:
    """Tick values: "auto" (decades on a log scale, 1-2-5 steps within decades when there are
    fewer than three, and otherwise 1-2-5 steps), "step:<v>" or
    "list:<a,b,c>" (values outside the scale left out)."""
    lo, hi = min(vmin, vmax), max(vmin, vmax)
    if hi == lo:
        return [float(lo)]
    eps = 1e-9 * max(abs(lo), abs(hi), 1.0)
    spec = (spec or "auto").strip()
    if spec.startswith("list:"):
        out = []
        for part in spec[5:].split(","):
            try:
                v = float(part.strip().replace(" ", ""))
            except ValueError:
                continue
            if lo - eps <= v <= hi + eps:
                out.append(v)
        return sorted(out)
    if spec.startswith("step:"):
        try:
            step = abs(float(spec[5:]))
        except ValueError:
            step = 0.0
    elif log and lo > 0:
        k0, k1 = math.ceil(math.log10(lo) - 1e-9), math.floor(math.log10(hi) + 1e-9)
        decades = [float(10.0 ** k) for k in range(k0, k1 + 1)]
        if len(decades) >= 3:
            return decades
        # a narrow range: 1-2-5 per decade, so the bar still gets labels
        return [float(round(m * 10.0 ** k, 12))
                for k in range(math.floor(math.log10(lo)), math.floor(math.log10(hi)) + 1)
                for m in (1, 2, 5) if lo - eps <= m * 10.0 ** k <= hi + eps]
    else:
        raw = (hi - lo) / 5.0
        mag = 10.0 ** math.floor(math.log10(raw))
        step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    if step <= 0:
        return [float(lo), float(hi)]
    first = math.ceil((lo - eps) / step) * step
    return [round(float(v), 12) for v in np.arange(first, hi + eps, step)]


def default_settings() -> QgsColorRampLegendNodeSettings:
    """QGIS's colour-ramp legend settings with a plain number format (no thousands
    separator: "1000", never "1.000" or "1,000" next to a scale that also has decimals)."""
    from qgis.core import QgsBasicNumericFormat
    settings = QgsColorRampLegendNodeSettings()
    fmt = QgsBasicNumericFormat()
    fmt.setShowThousandsSeparator(False)
    fmt.setShowTrailingZeros(False)
    fmt.setNumberDecimalPlaces(6)
    settings.setNumericFormat(fmt)
    return settings


def tick_labels(values: list[float], settings: QgsColorRampLegendNodeSettings) -> list[str]:
    fmt, ctx = settings.numericFormat(), QgsNumericFormatContext()
    return [settings.prefix() + fmt.formatDouble(v, ctx) + settings.suffix() for v in values]


class ColourBarItem(QgsLayoutItem):
    @staticmethod
    def provider():
        return current_provider()

    def __init__(self, layout):
        super().__init__(layout)
        _keep_alive(self)
        self.frame_id = ""
        self.dataset_id = ""
        self.ticks = "auto"
        self.title = ""
        self.unit = ""
        self.settings = default_settings()

    def type(self):
        return COLOUR_BAR_TYPE

    def displayName(self):
        return self.id() or "Colour bar"

    # -- data ------------------------------------------------------------------------------
    def colour_scale(self):
        """The frame's colour scale for the model (the frame's own, else the model's)."""
        from ..core.colors import ColorScale
        from .sources import read_plates
        project = self.layout().project() if self.layout() else None
        model = None
        for plate in read_plates(project) if project is not None else []:
            for frame in plate.frames:
                if frame.frame_id == self.frame_id:
                    model = next((m for m in frame.look.models
                                  if m.dataset_id == self.dataset_id), None)
        if model is not None and model.scale:
            try:
                return ColorScale(**model.scale)
            except (TypeError, ValueError):
                pass
        provider = self.provider()
        if provider is not None:
            return provider.style(self.dataset_id).scale
        return None

    # -- drawing ---------------------------------------------------------------------------
    def draw(self, context):
        rc = context.renderContext()
        painter = rc.painter()
        px = rc.scaleFactor()
        w, h = self.rect().width() * px, self.rect().height() * px
        fmt = self.settings.textFormat()
        scale = self.colour_scale()
        line_h = QgsTextRenderer.textHeight(rc, fmt, ["0"])
        title = " ".join(x for x in (self.title, f"({self.unit})" if self.unit else "") if x)
        top = 0.0
        if title:
            QgsTextRenderer.drawText(QPointF(0, line_h), 0, Qgis.TextHorizontalAlignment.Left,
                                     [title], rc, fmt)
            top = line_h * 1.6
        if scale is None:
            QgsTextRenderer.drawText(QPointF(0, top + line_h), 0,
                                     Qgis.TextHorizontalAlignment.Left,
                                     ["(model not found)"], rc, fmt)
            return
        vertical = self.settings.orientation() == Qt.Orientation.Vertical
        reverse = self.settings.direction() == \
            QgsColorRampLegendNodeSettings.Direction.MaximumToMinimum
        if vertical:
            bar = QRectF(0, top + line_h / 2, w * 0.3, max(h - top - line_h, 1.0))
        else:
            bar = QRectF(0, top, w, max((h - top) * 0.45, 1.0))
        t = np.linspace(0.0, 1.0, STEPS + 1)
        lo, hi = scale.vmin, scale.vmax
        if scale.log and lo > 0 and hi > 0:
            vals = 10 ** (np.log10(lo) + t * (np.log10(hi) - np.log10(lo)))
        else:
            vals = lo + t * (hi - lo)
        colours = scale.rgba(vals)

        def pos(frac):              # 0 = minimum, 1 = maximum -> along the bar
            frac = 1.0 - frac if reverse else frac
            if vertical:
                return bar.bottom() - frac * bar.height()
            return bar.left() + frac * bar.width()

        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        for i in range(STEPS):
            c = colours[i]
            painter.setBrush(QColor(int(c[0]), int(c[1]), int(c[2])))
            a, b = pos(t[i]), pos(t[i + 1])
            if vertical:
                painter.drawRect(QRectF(bar.left(), min(a, b), bar.width(), abs(b - a) + 0.5))
            else:
                painter.drawRect(QRectF(min(a, b), bar.top(), abs(b - a) + 0.5, bar.height()))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(0, 0, 0), max(1.0, 0.15 * px)))
        painter.drawRect(bar)
        values = colour_bar_ticks(lo, hi, scale.log, self.ticks)
        for v, label in zip(values, tick_labels(values, self.settings)):
            if scale.log and lo > 0 and v > 0:
                frac = (math.log10(v) - math.log10(lo)) / (math.log10(hi) - math.log10(lo))
            else:
                frac = (v - lo) / (hi - lo) if hi != lo else 0.0
            p = pos(frac)
            if vertical:
                painter.drawLine(QPointF(bar.right(), p), QPointF(bar.right() + 0.8 * px, p))
                QgsTextRenderer.drawText(QPointF(bar.right() + 1.2 * px, p + line_h / 3), 0,
                                         Qgis.TextHorizontalAlignment.Left, [label], rc, fmt)
            else:
                painter.drawLine(QPointF(p, bar.bottom()), QPointF(p, bar.bottom() + 0.8 * px))
                QgsTextRenderer.drawText(QPointF(p, bar.bottom() + 1.2 * px + line_h), 0,
                                         Qgis.TextHorizontalAlignment.Center, [label], rc, fmt)
        painter.restore()

    # -- persistence -----------------------------------------------------------------------
    def writePropertiesToElement(self, element, document, context):
        for key in ("frame_id", "dataset_id", "ticks", "title", "unit"):
            element.setAttribute(f"wb_{key}", getattr(self, key))
        node = document.createElement("wbColourBarSettings")
        self.settings.writeXml(document, node, context)
        element.appendChild(node)
        return True

    def readPropertiesFromElement(self, element, document, context):
        for key in ("frame_id", "dataset_id", "ticks", "title", "unit"):
            setattr(self, key, element.attribute(f"wb_{key}", getattr(self, key)))
        node = element.firstChildElement("wbColourBarSettings")
        if not node.isNull():
            self.settings.readXml(node, context)
        return True


# -- borehole legend -------------------------------------------------------------------------
def legend_rows(intervals, renderer, fields) -> list[tuple[str, object]]:
    """(label, fill symbol) of the classes the ``intervals`` use, in the style's order; values
    without a class get their neutral colour (as drawn)."""
    from ..section.borehole_style import broken_rules, default_symbol
    rows: list = []
    unclassed: list[str] = []
    if renderer is not None and not broken_rules(renderer):
        r = renderer.clone()
        ctx = QgsRenderContext()
        present: set = set()
        r.startRender(ctx, fields)
        try:
            for iv in intervals:
                if iv.feature is None:
                    continue
                ctx.expressionContext().setFeature(iv.feature)
                keys = set(r.legendKeysForFeature(iv.feature, ctx))
                if keys:
                    present |= keys
                elif iv.text not in unclassed:
                    unclassed.append(iv.text)
        finally:
            r.stopRender(ctx)
        items = r.legendSymbolItems()
        rows = [(item.label(), item.symbol().clone()) for item in items
                if item.ruleKey() in present and item.symbol() is not None]
    else:
        for iv in intervals:
            if iv.text not in unclassed:
                unclassed.append(iv.text)
    rows += [(text, default_symbol(text)) for text in unclassed if text]
    return rows


def curve_rows(points, views: dict, styles: dict) -> list[tuple[str, object]]:
    """(label, CurveStyle) of the log curves the section draws (the curves picked for each
    borehole entry's section look), once per curve, with the user's curve style."""
    out, seen = [], set()
    for p in points:
        view = views.get(p.entry) if p.kind == "borehole" else None
        for c in p.curves if view is not None else []:
            if c.key in view.curve_keys and c.key not in seen:
                seen.add(c.key)
                out.append((f"{c.name} ({c.unit})" if c.unit else c.name,
                            styles.get(c.key) or CurveStyle()))
    return out


class BoreholeLegendItem(QgsLayoutItem):
    @staticmethod
    def provider():
        return current_provider()

    def __init__(self, layout):
        super().__init__(layout)
        _keep_alive(self)
        self.frame_ids: list[str] = []
        self.text_format = QgsTextFormat()
        self.text_format.setSize(8.0)

    def type(self):
        return BOREHOLE_LEGEND_TYPE

    def displayName(self):
        return self.id() or "Borehole legend"

    def rows(self) -> list[tuple[str, object]]:
        """The classes of every interval table shown in the item's frames."""
        from ..section.borehole_style import load_renderer
        from ..ui.context_dialog import read_settings
        from .sources import read_plates
        project = self.layout().project() if self.layout() else None
        provider = self.provider()
        if project is None or provider is None:
            return []
        frames = [f for p in read_plates(project) for f in p.frames
                  if f.frame_id in self.frame_ids and f.look.boreholes]
        entries = read_settings(project).boreholes
        by_entry: dict[int, list] = {}
        curves: list = []
        for f in frames:
            if not provider.store_has_profile(f.profile_id):
                continue
            ctx = provider.context(f.profile_id)
            for p in ctx.points if ctx is not None else []:
                if p.kind == "borehole" and 0 <= p.entry < len(entries):
                    by_entry.setdefault(p.entry, []).extend(p.log)
            if ctx is not None:
                curves += curve_rows(ctx.points, ctx.borehole_views, ctx.curve_styles)
        out = []
        for entry, intervals in sorted(by_entry.items()):
            layer = project.mapLayer(entries[entry].log_layer_id)
            if layer is None:
                continue
            out += legend_rows(intervals, load_renderer(project, entries[entry].log_layer_id),
                               layer.fields())
        seen: set = set()
        for label, style in curves:                     # once per curve across frames
            if label not in seen:
                seen.add(label)
                out.append((label, style))
        return out

    def draw(self, context):
        rc = context.renderContext()
        px = rc.scaleFactor()
        line_h = QgsTextRenderer.textHeight(rc, self.text_format, ["0"])
        rows = self.rows()
        if not rows:
            QgsTextRenderer.drawText(QPointF(0, line_h), 0, Qgis.TextHorizontalAlignment.Left,
                                     ["(no boreholes on this plate)"], rc, self.text_format)
            return
        swatch_w, swatch_h, gap = 6.0 * px, max(line_h * 1.2, 3.0 * px), 1.5 * px
        y = 0.0
        for label, symbol in rows:
            if isinstance(symbol, CurveStyle):          # a log curve: its line
                from ..section.borehole_draw import _DASH
                painter = rc.painter()
                painter.save()
                painter.setPen(QPen(QColor(symbol.colour), max(symbol.width_mm * px, 1.0),
                                    _DASH.get(symbol.dash, Qt.PenStyle.SolidLine)))
                painter.drawLine(QPointF(0, y + swatch_h / 2), QPointF(swatch_w, y + swatch_h / 2))
                painter.restore()
            else:
                poly = QPolygonF([QPointF(0, y), QPointF(swatch_w, y),
                                  QPointF(swatch_w, y + swatch_h), QPointF(0, y + swatch_h),
                                  QPointF(0, y)])
                symbol.startRender(rc)
                try:
                    symbol.renderPolygon(poly, None, None, rc)
                finally:
                    symbol.stopRender(rc)
            QgsTextRenderer.drawText(QPointF(swatch_w + gap, y + swatch_h / 2 + line_h / 3), 0,
                                     Qgis.TextHorizontalAlignment.Left, [label], rc,
                                     self.text_format)
            y += swatch_h + gap

    def writePropertiesToElement(self, element, document, context):
        element.setAttribute("wb_frame_ids", ",".join(self.frame_ids))
        node = document.createElement("wbTextFormat")
        node.appendChild(self.text_format.writeXml(document, context))
        element.appendChild(node)
        return True

    def readPropertiesFromElement(self, element, document, context):
        self.frame_ids = [x for x in element.attribute("wb_frame_ids", "").split(",") if x]
        node = element.firstChildElement("wbTextFormat")
        if not node.isNull():
            self.text_format.readXml(node.firstChildElement(), context)
        return True


# -- registration ----------------------------------------------------------------------------
class _Metadata(QgsLayoutItemAbstractMetadata):
    def __init__(self, type_id, name, cls):
        super().__init__(type_id, name)
        self.cls = cls

    def createItem(self, layout):
        return self.cls(layout)


def register_items() -> None:
    """Register the item types once per QGIS session (and their property widgets when a
    GUI is running)."""
    registry = QgsApplication.layoutItemRegistry()
    for type_id, name, cls in ((COLOUR_BAR_TYPE, "Colour bar (Geophysics Workbench)",
                                ColourBarItem),
                               (BOREHOLE_LEGEND_TYPE, "Borehole legend (Geophysics Workbench)",
                                BoreholeLegendItem)):
        if registry.itemMetadata(type_id) is None:
            meta = _Metadata(type_id, name, cls)
            if registry.addLayoutItemType(meta):
                _metadata.append(meta)
    try:
        from .item_widgets import register_widgets
        register_widgets()
    except ImportError:                          # no GUI (headless use)
        pass
