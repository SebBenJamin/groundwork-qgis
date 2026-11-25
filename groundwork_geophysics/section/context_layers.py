"""Gather third-party context for one profile from the layers chosen in 'Context Layers…'.

Runs on the main thread only (it reads QGIS layers) and hands back a plain-data
``ContextItems``. Every layer is gathered in its own try/except: a missing or invalid
layer, or a renamed field, logs one warning (once per gatherer and problem) and that layer
is skipped. Layers are never modified; no spatial index is created on user data."""
from __future__ import annotations

import re
from typing import Callable

import numpy as np
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsExpression, QgsFeature, QgsFeatureRequest, QgsGeometry, QgsMapLayer,
                       QgsMessageLog, QgsProject, QgsRectangle, QgsVariantUtils)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QTimer

from ..core.lithology import label_colour
from ..core.context import (BandSegment, ContextItems, Crossing, Curve, LogInterval,
                            ProjectedPoint, collar_height, line_crossings, polygon_intervals,
                            project_points)
from ..core.context_settings import curve_key
from ..core.model import Profile
from ..ids import NAME
from ..ui.context_dialog import read_settings
from .crossing_lines import active_line_settings, line_colour
from .dem_sampling import sample_point, sample_profile

LOG_TAG = NAME
DEBOUNCE_MS = 300
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_VOLTAGE_FIELD = ("volt", "spannung")
_GEOMETRY = {"line": Qgis.GeometryType.Line, "point": Qgis.GeometryType.Point,
             "polygon": Qgis.GeometryType.Polygon}
_SIGNALS = ("featureAdded", "featureDeleted", "geometryChanged", "attributeValueChanged",
            "dataChanged")
_STYLE_SIGNALS = ["rendererChanged", "styleChanged"]
_ALL_SIGNALS = _SIGNALS + ("selectionChanged",) + tuple(_STYLE_SIGNALS)


def voltage_label(value: str, field: str) -> str:
    """Only a field whose name holds "volt" or "spannung" is read as a voltage: its first
    number becomes kV ('380000;110000' -> '380 kV'; >= 1000 means volts). Any other field,
    or a value without a number, is returned unchanged."""
    if not any(w in field.lower() for w in _VOLTAGE_FIELD):
        return value
    match = _NUMBER.search(value)
    if match is None:
        return value
    number = float(match.group().replace(",", "."))
    return f"{number / 1000 if number >= 1000 else number:g} kV"


def _text(value) -> str:
    return "" if QgsVariantUtils.isNull(value) else str(value).strip()


_DECIMAL_COMMA = re.compile(r"\s*-?\d+,\d+\s*")


def _number(value) -> float | None:
    """A finite number; text with a decimal comma ("0,4" from a German CSV) is read too."""
    if isinstance(value, str) and _DECIMAL_COMMA.fullmatch(value):
        value = value.replace(",", ".")
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


def _depth(value) -> float | None:
    """A usable stick depth: a positive finite number, else ``None`` (NULL, text, <= 0)."""
    out = None if QgsVariantUtils.isNull(value) else _number(value)
    return out if out is not None and out > 0 else None


def _value(value) -> float:
    """A curve sample: a finite number, else nan (NULL, text)."""
    out = None if QgsVariantUtils.isNull(value) else _number(value)
    return np.nan if out is None else out


REMOTE_PROVIDERS = ("WFS", "OAPIF", "arcgisfeatureserver")


def _id_text(value) -> str:
    """A borehole id as text: stripped, and a whole number without ".0" (7, 7.0 and " 7 "
    are the same borehole; Excel imports often store ids as Real)."""
    if QgsVariantUtils.isNull(value):
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _id_filter(field: str, bid: str, remote: bool = False, numeric: bool = False) -> str:
    """Rows whose id may equal ``bid``; the caller re-checks every row with ``_id_text``.
    Local tables: compared as stripped text, whatever the field's type. Remote (WFS/OAPIF)
    tables: a plain equality the server can run (trim/to_string would make QGIS download
    the whole table)."""
    column = QgsExpression.quotedColumnRef(field)
    if remote:
        if numeric:
            try:
                return f"{column} = {float(bid):g}"
            except ValueError:
                pass
        return f"{column} = {QgsExpression.quotedString(bid)}"
    return f"trim(to_string({column})) = {QgsExpression.quotedString(bid)}"


def _id_request_filter(layer, field: str, bid: str) -> str:
    idx = layer.fields().indexOf(field)
    numeric = idx >= 0 and layer.fields().at(idx).isNumeric()
    return _id_filter(field, bid, layer.providerType() in REMOTE_PROVIDERS, numeric)


class _Skip(Exception):
    """A layer cannot be used; the message is logged once and the layer skipped."""


class ContextGatherer:
    def __init__(self, project, crs_authid: str, on_change: Callable[[], None],
                 exclude: Callable[[], set[str]] = lambda: set()):
        self._project = project
        self._exclude = exclude
        self._crs_authid = crs_authid
        self._on_change = on_change
        self._logged: set[tuple[str, str]] = set()
        self._watched: dict[str, QgsMapLayer] = {}
        self._drop_slots: dict[str, Callable[[], None]] = {}
        self._watch_key: tuple = ()
        self._last_settings = None
        self._last_active: frozenset[str] | None = None
        self._root = project.layerTreeRoot()
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._fire)
        project.layersRemoved.connect(self._removed)
        project.layersAdded.connect(self._active_set_maybe_changed)
        self._root.visibilityChanged.connect(self._active_set_maybe_changed)
        self._root.addedChildren.connect(self._active_set_maybe_changed)   # tree node may follow layersAdded

    # -- public ---------------------------------------------------------------------------
    def items_for(self, profile: Profile) -> ContextItems:
        settings = read_settings(self._project)
        active = active_line_settings(self._project, settings, self._exclude())
        self._last_settings = settings
        self._last_active = frozenset(layer.id() for layer, _s in active)
        self._watch(settings, active)
        chain = profile.chainage
        xy = chain.xy
        pad = settings.buffer
        box = QgsRectangle(xy[:, 0].min() - pad, xy[:, 1].min() - pad,
                           xy[:, 0].max() + pad, xy[:, 1].max() + pad)
        items = ContextItems(dem_tolerance=settings.dem_tolerance)
        dem_layer = self._try(settings.dem_layer_id, "DEM", lambda: self._raster(settings.dem_layer_id))
        if dem_layer is not None:
            items.dem = self._try(settings.dem_layer_id, "DEM",
                                  lambda: sample_profile(dem_layer, chain, self._crs_authid,
                                                         self._project))
            if items.dem is None:
                self._warn(settings.dem_layer_id, "DEM has no data along the profile")
        for _layer, s in active:
            items.crossings += self._try(s.layer_id, "line layer", lambda: self._lines(
                s, xy, box)) or []
        for s in settings.point_layers:
            items.points += self._try(s.layer_id, "point layer", lambda: self._points(
                s, xy, box, settings.buffer)) or []
        from .borehole_style import curve_styles
        items.borehole_views = borehole_views(settings)
        items.curve_styles = curve_styles(self._project)
        for index, b in enumerate(settings.boreholes):
            items.points += self._try(b.layer_id, "borehole layer", lambda: self._boreholes(
                b, xy, box, settings.buffer, dem_layer, index, settings.dem_tolerance)) or []
        for strip, b in enumerate(settings.shown_bands()):
            items.band += self._try(b.layer_id, "strip layer", lambda: self._band(
                b, xy, box, strip)) or []
        items.crossings.sort(key=lambda c: c.s)
        items.points.sort(key=lambda p: p.s)
        return items

    def borehole_keys(self, profiles: list[Profile]) -> dict[str, list]:
        """Per profile id: ``borehole_key`` of each borehole within the search distance of
        its line (None for one without an id), read from the borehole layers alone (no logs,
        DEM, strips or crossing lines), one request per layer for all ``profiles``. Show in
        3D… asks this for every profile; a live layer once per profile took seconds each."""
        out: dict[str, list] = {p.id: [] for p in profiles}
        if not profiles:
            return out
        settings = read_settings(self._project)
        pad = settings.buffer
        xy_all = np.vstack([p.chainage.xy for p in profiles])
        box = QgsRectangle(xy_all[:, 0].min() - pad, xy_all[:, 1].min() - pad,
                           xy_all[:, 0].max() + pad, xy_all[:, 1].max() + pad)
        for b in settings.boreholes:
            def found_near(b=b):
                layer = self._vector(b.layer_id, "point", (b.id_field,))
                return self._point_features(layer, box, (b.id_field,))
            found = self._try(b.layer_id, "borehole layer", found_near) or []
            for p in profiles:
                out[p.id] += [(b.layer_id, _id_text(f[b.id_field]))
                              if _id_text(f[b.id_field]) else None
                              for (f, _xy), _so in _project(p.chainage.xy, found, pad)]
        return out

    def close(self) -> None:
        self._timer.stop()
        self._unwatch()
        try:
            self._project.layersRemoved.disconnect(self._removed)
        except (TypeError, RuntimeError):
            pass
        try:
            signals = (self._project.layersAdded, self._root.visibilityChanged,
                       self._root.addedChildren)
        except RuntimeError:                              # the project is already deleted
            return
        for signal in signals:
            try:
                signal.disconnect(self._active_set_maybe_changed)
            except (TypeError, RuntimeError):
                pass

    # -- change watching ------------------------------------------------------------------
    def _watch(self, settings, active=()) -> None:
        line_ids = [layer.id() for layer, _s in active]
        selected = {layer.id() for layer, s in active if s.selected_only}
        wanted = {}
        for layer_id in _layer_ids(settings, line_ids):
            layer = self._project.mapLayer(layer_id)
            if layer is not None:
                wanted[layer_id] = layer
        key = (frozenset(line_ids), frozenset(selected))
        if (key == self._watch_key and set(wanted) == set(self._watched)
                and all(wanted[k] is self._watched[k] for k in wanted)):
            return
        self._unwatch()
        for layer in wanted.values():
            slot = self._drop_slot(layer)
            layer.willBeDeleted.connect(slot)
            self._drop_slots[layer.id()] = slot
            names = list(_SIGNALS)
            band_ids = {b.layer_id for b in settings.shown_bands()}
            if layer.id() in line_ids or layer.id() in band_ids:     # colours come from styles
                names += _STYLE_SIGNALS
            if layer.id() in selected:
                names.append("selectionChanged")
            for name in names:
                signal = getattr(layer, name, None)
                if signal is not None:
                    signal.connect(self._kick)
        self._watched = wanted
        self._watch_key = key

    def _unwatch(self) -> None:
        watched, self._watched = self._watched, {}
        slots, self._drop_slots = self._drop_slots, {}
        for layer in watched.values():
            if sip.isdeleted(layer):
                continue
            for name, slot in [(n, self._kick) for n in _ALL_SIGNALS] + [
                    ("willBeDeleted", slots.get(layer.id()))]:
                try:
                    getattr(layer, name).disconnect(slot)
                except (TypeError, RuntimeError, AttributeError):   # never connected
                    pass

    def _drop_slot(self, layer):
        layer_id = layer.id()

        def drop():
            """The layer is going away: forget it (its signals die with it) and refresh."""
            self._watched.pop(layer_id, None)
            self._drop_slots.pop(layer_id, None)
            self._kick()
        return drop

    def _active_set_maybe_changed(self, *_args) -> None:
        """A layer was added or a visibility toggled: redraw only if that changes which
        line layers are active."""
        if self._last_settings is None:
            return
        try:
            active = active_line_settings(self._project, self._last_settings, self._exclude())
            ids = frozenset(layer.id() for layer, _s in active)
            if ids != self._last_active:
                self._last_active = ids
                self._kick()
        except Exception as exc:                        # a Qt slot must never raise
            self._warn("active_set", f"live check failed: {type(exc).__name__}: {exc}")

    def _removed(self, layer_ids) -> None:
        if any(i in self._watched for i in layer_ids):
            self._kick()

    def _kick(self, *_args) -> None:
        self._timer.start()

    def _fire(self) -> None:
        try:
            self._on_change()
        except Exception as exc:                        # a callback must not break the timer
            self._warn("on_change", f"refresh failed: {type(exc).__name__}: {exc}")

    # -- logging / layer access -----------------------------------------------------------
    def _warn(self, key: str, message: str) -> None:
        if (key, message) in self._logged:
            return
        self._logged.add((key, message))
        QgsMessageLog.logMessage(f"Context: {message}", LOG_TAG, Qgis.MessageLevel.Warning)

    def _try(self, layer_id: str, what: str, fn):
        try:
            return fn()
        except _Skip as exc:
            self._warn(layer_id, f"{what} skipped: {exc}")
        except Exception as exc:
            self._warn(layer_id, f"{what} skipped: {type(exc).__name__}: {exc}")
        return None

    def _vector(self, layer_id: str, geometry: str | None, fields: tuple = ()):
        layer = self._project.mapLayer(layer_id) if layer_id else None
        if layer is None:
            raise _Skip(f"layer {layer_id or '(none)'} is not in the project")
        if not layer.isValid() or not hasattr(layer, "getFeatures"):
            raise _Skip(f"layer '{layer.name()}' is not a valid vector layer")
        if geometry is not None and layer.geometryType() != _GEOMETRY[geometry]:
            raise _Skip(f"layer '{layer.name()}' is not a {geometry} layer")
        names = layer.fields().names()
        for name in fields:
            if name and name not in names:
                raise _Skip(f"layer '{layer.name()}' has no field '{name}'")
        return layer

    def _raster(self, layer_id: str):
        if not layer_id:
            return None
        layer = self._project.mapLayer(layer_id)
        if layer is None or not layer.isValid() or not hasattr(layer, "rasterUnitsPerPixelX"):
            raise _Skip(f"layer {layer_id} is not a valid raster layer")
        return layer

    def _features(self, layer, box: QgsRectangle, fields: tuple, fids: set[int] | None = None):
        """Features whose bbox meets ``box`` (store CRS) with only ``fields`` read, and
        whose id is in ``fids`` when that is given; yields (feature, geometry in the
        store CRS)."""
        ct = self._to_store(layer)
        rect = box if ct is None else ct.transformBoundingBox(
            box, Qgis.TransformDirection.Reverse)
        request = QgsFeatureRequest().setFilterRect(rect)
        request.setSubsetOfAttributes([f for f in fields if f], layer.fields())
        for feature in layer.getFeatures(request):
            if fids is not None and feature.id() not in fids:
                continue
            geom = QgsGeometry(feature.geometry())
            if geom.isNull():
                continue
            if ct is not None:
                geom.transform(ct)
            yield feature, geom

    def _to_store(self, layer):
        store = QgsCoordinateReferenceSystem(self._crs_authid)
        if layer.crs() == store:
            return None
        return QgsCoordinateTransform(layer.crs(), store, self._project)

    # -- one method per kind of layer -----------------------------------------------------
    def _lines(self, setting, xy, box) -> list[Crossing]:
        layer = self._vector(setting.layer_id, "line", (setting.label_field,))
        fids = None
        if setting.selected_only:
            fids = set(layer.selectedFeatureIds())
            if not fids:
                return []
        rgb = line_colour(setting, layer)
        out = []
        for feature, geom in self._features(layer, box, (setting.label_field,), fids):
            label = _text(feature[setting.label_field]) if setting.label_field else ""
            if label:
                label = voltage_label(label, setting.label_field)
            parts = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
            for part in parts:
                if len(part) >= 2:
                    pts = np.array([[p.x(), p.y()] for p in part])
                    out += line_crossings(xy, pts, label or layer.name(), "line", rgb,
                                          layer.name())
        return out

    def _points(self, setting, xy, box, buffer) -> list[ProjectedPoint]:
        names = (setting.label_field, setting.depth_field)
        layer = self._vector(setting.layer_id, "point", names)
        found = self._point_features(layer, box, names)
        return [ProjectedPoint(s, off, _text(f[setting.label_field]) if setting.label_field
                               and _text(f[setting.label_field]) else layer.name(), "point",
                               depth=_depth(f[setting.depth_field]) if setting.depth_field
                               else None)
                for (f, _p), (s, off) in _project(xy, found, buffer)]

    def _point_features(self, layer, box, fields):
        out = []
        for feature, geom in self._features(layer, box, fields):
            try:
                p = geom.asMultiPoint()[0] if geom.isMultipart() else geom.asPoint()
            except (IndexError, TypeError, ValueError):   # empty geometry: skip the feature
                continue
            out.append((feature, (p.x(), p.y())))
        return out

    def _boreholes(self, b, xy, box, buffer, dem_layer, entry: int = -1,
                   tolerance: float = 1.0) -> list[ProjectedPoint]:
        wanted = tuple(f for f in (b.id_field, b.elevation_field, b.total_depth_field) if f)
        layer = self._vector(b.layer_id, "point", wanted)
        found = self._point_features(layer, box, wanted)
        with self._styler(b) as styler:
            return self._borehole_points(b, xy, found, buffer, dem_layer, entry, tolerance,
                                         layer, styler)

    def _styler(self, b):
        """The entry's interval style, prepared once for all its boreholes in this gather."""
        import contextlib

        from . import borehole_style
        if not b.log_layer_id:
            return contextlib.nullcontext(None)
        try:
            log_layer = self._vector(b.log_layer_id, None, ())
        except Exception:                           # reported by _log for each borehole
            return contextlib.nullcontext(None)
        return borehole_style.IntervalStyler(
            borehole_style.load_renderer(self._project, b.log_layer_id), log_layer.fields())

    def _borehole_points(self, b, xy, found, buffer, dem_layer, entry, tolerance, layer,
                         styler) -> list[ProjectedPoint]:
        out = []
        for (feature, (x, y)), (s, off) in _project(xy, found, buffer):
            bid = _id_text(feature[b.id_field])
            field_z = _number(feature[b.elevation_field]) if b.elevation_field else None
            dem_z = None
            if dem_layer is not None:
                try:
                    dem_z = sample_point(dem_layer, x, y, self._crs_authid, self._project)
                except Exception as exc:
                    self._warn(b.layer_id, f"DEM sample at borehole failed: "
                                           f"{type(exc).__name__}: {exc}")
            dem_z = dem_z if dem_z is not None and np.isfinite(dem_z) else None
            z_top, source = collar_height(field_z, dem_z, None)
            log = self._log(b, bid, styler) if bid else []
            curves = [c for t in b.curve_tables for c in self._curves(t, bid)] if bid else []
            total = _depth(feature[b.total_depth_field]) if b.total_depth_field else None
            flagged = (source == "field" and dem_z is not None
                       and abs(z_top - dem_z) > tolerance)
            out.append(ProjectedPoint(s, off, bid or layer.name(), "borehole", z_top, log,
                                      entry=entry, z_source=source, z_dem=dem_z,
                                      total_depth=total, curves=curves, flagged=flagged,
                                      bid=bid, layer_id=b.layer_id, x=float(x), y=float(y)))
        return out

    def _curves(self, t, bid: str) -> list[Curve]:
        """The curves of one curve table for borehole ``bid``, sorted by depth."""
        if not (t.layer_id and t.id_field and t.depth_field and t.curves):
            return []
        names = [c.field for c in t.curves]
        fields = (t.id_field, t.depth_field, *names)
        try:
            layer = self._vector(t.layer_id, None, fields)
            request = QgsFeatureRequest().setFilterExpression(
                _id_request_filter(layer, t.id_field, bid))
            request.setSubsetOfAttributes(list(fields), layer.fields())
            rows = []
            for f in layer.getFeatures(request):
                if _id_text(f[t.id_field]) != bid:
                    continue
                d = _number(f[t.depth_field])
                if d is not None:
                    rows.append((d, [_value(f[n]) for n in names]))
        except _Skip as exc:
            self._warn(t.layer_id, f"curve table skipped: {exc}")
            return []
        except Exception as exc:
            self._warn(t.layer_id, f"curve table skipped: {type(exc).__name__}: {exc}")
            return []
        if not rows:
            return []
        rows.sort(key=lambda r: r[0])
        depth = np.array([r[0] for r in rows], float)
        return [Curve(curve_key(t.layer_id, c.field), c.field, c.unit, depth,
                      np.array([r[1][i] for r in rows], float))
                for i, c in enumerate(t.curves)]

    def _log(self, b, bid: str, styler=None) -> list[LogInterval]:
        if not b.log_layer_id:
            return []
        from .borehole_style import default_symbol
        fields = (b.log_id_field, b.top_field, b.bottom_field, b.lithology_field)
        try:
            layer = self._vector(b.log_layer_id, None, fields)
            styled = styler.used if styler is not None else set()
            request = QgsFeatureRequest().setFilterExpression(
                _id_request_filter(layer, b.log_id_field, bid))
            request.setSubsetOfAttributes(sorted({f for f in fields if f} | styled),
                                          layer.fields())
            rows, features, swapped = [], [], 0
            for f in layer.getFeatures(request):
                if _id_text(f[b.log_id_field]) != bid:
                    continue
                top, bottom = _number(f[b.top_field]), _number(f[b.bottom_field])
                if top is not None and bottom is not None:
                    swapped += top > bottom
                    rows.append(LogInterval(min(top, bottom), max(top, bottom),
                                            _text(f[b.lithology_field])
                                            if b.lithology_field else ""))
                    features.append(QgsFeature(f))
            if swapped:
                self._warn(b.log_layer_id, f"{swapped} interval(s) of borehole {bid} have their "
                                           f"top below the bottom; used swapped")
            pairs = (styler.symbols(features, [r.text for r in rows]) if styler is not None
                     else [(default_symbol(r.text), f) for r, f in zip(rows, features)])
            for row, (symbol, feature) in zip(rows, pairs):
                row.symbol, row.feature = symbol, feature
        except _Skip as exc:
            self._warn(b.log_layer_id, f"log table skipped: {exc}")
            return []
        except Exception as exc:
            self._warn(b.log_layer_id, f"log table skipped: {type(exc).__name__}: {exc}")
            return []
        return sorted(rows, key=lambda r: (r.top, r.bottom))

    def _band(self, setting, xy, box, strip: int = 0) -> list[BandSegment]:
        """Units along the profile. Colours come from the band layer's own style, so the band
        matches the map; a single-symbol style says nothing about units, so each label then
        gets its own colour. Only features near the profile are read (never the whole
        layer: a WFS would download it all)."""
        from qgis.core import QgsExpressionContextUtils, QgsRenderContext
        layer = self._vector(setting.layer_id, "polygon", (setting.label_field,))
        renderer = layer.renderer()
        styled = renderer is not None and renderer.type() != "singleSymbol"
        ctx = QgsRenderContext()
        fields = [setting.label_field] if setting.label_field else []
        if styled:
            ctx.expressionContext().appendScopes(
                QgsExpressionContextUtils.globalProjectLayerScopes(layer))
            renderer = renderer.clone()
            renderer.startRender(ctx, layer.fields())
            fields += sorted(renderer.usedAttributes(ctx))
        polygons, labels, colours = [], [], {}
        try:
            for feature, geom in self._features(layer, box, tuple(fields)):
                label = (_text(feature[setting.label_field]) if setting.label_field else "") or layer.name()
                if styled and label not in colours:     # first feature of a label decides
                    ctx.expressionContext().setFeature(feature)
                    symbols = renderer.symbolsForFeature(feature, ctx)
                    if symbols:
                        c = symbols[0].color()
                        colours[label] = (c.red(), c.green(), c.blue())
                for poly in (geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]):
                    rings = [np.array([[p.x(), p.y()] for p in ring]) for ring in poly
                             if len(ring) >= 3]
                    if rings:
                        polygons.append((rings[0], rings[1:]))
                        labels.append(label)
        finally:
            if styled:
                renderer.stopRender(ctx)
        if not polygons:
            return []
        segments = polygon_intervals(xy, polygons, labels)
        for seg in segments:
            seg.rgb = colours.get(seg.label) or label_colour(seg.label)
            seg.strip, seg.title = strip, setting.title or layer.name()
        return segments


def borehole_views(settings) -> dict:
    """How the section draws each borehole entry (from its settings, set in the viewer)."""
    from ..core.context import BoreholeView
    return {i: BoreholeView(b.column_px, b.opacity, b.layer_text, tuple(b.section_curves))
            for i, b in enumerate(settings.boreholes)}


def _project(xy, found, buffer):
    """[(item, (s, offset))] for the (feature, (x, y)) pairs within ``buffer``."""
    if not found:
        return []
    hits = project_points(xy, np.array([p for _f, p in found]), buffer)
    return [(found[i], (s, off)) for i, s, off in hits]


def _layer_ids(settings, line_ids=()) -> list[str]:
    ids = list(line_ids) + [s.layer_id for s in settings.point_layers]
    for b in settings.boreholes:
        ids += [b.layer_id, b.log_layer_id] + [c.layer_id for c in b.curve_tables]
    ids += [b.layer_id for b in settings.shown_bands()]
    ids.append(settings.dem_layer_id)
    return [i for i in ids if i]
