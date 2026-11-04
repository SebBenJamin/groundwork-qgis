"""Gather third-party context for one profile from the layers chosen in 'Context layers…'.

Runs on the main thread only (it reads QGIS layers) and hands back a plain-data
``ContextItems``. Every layer is gathered in its own try/except: a missing or invalid
layer, or a renamed field, logs one warning (once per gatherer and problem) and that layer
is skipped. Layers are never modified; no spatial index is created on user data."""
from __future__ import annotations

import re
from typing import Callable

import numpy as np
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsExpression, QgsFeatureRequest, QgsGeometry, QgsMapLayer,
                       QgsMessageLog, QgsProject, QgsRectangle, QgsVariantUtils)
from qgis.PyQt import sip
from qgis.PyQt.QtCore import QTimer

from ..core.context import (BandSegment, ContextItems, Crossing, LogInterval, ProjectedPoint,
                            line_crossings, polygon_intervals, project_points)
from ..core.model import Profile
from ..ui.context_dialog import read_settings
from .crossing_lines import active_line_settings, line_colour
from .dem_sampling import sample_point, sample_profile

LOG_TAG = "Geophysics Workbench"
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


def _number(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if np.isfinite(out) else None


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
        if settings.borehole is not None:
            b = settings.borehole
            items.points += self._try(b.layer_id, "borehole layer", lambda: self._boreholes(
                b, xy, box, settings.buffer, dem_layer)) or []
        if settings.band is not None:
            b = settings.band
            items.band = self._try(b.layer_id, "geology layer", lambda: self._band(
                b, xy, box)) or []
        items.crossings.sort(key=lambda c: c.s)
        items.points.sort(key=lambda p: p.s)
        return items

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
            if layer.id() in line_ids:
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
        layer = self._vector(setting.layer_id, "point", (setting.label_field,))
        found = self._point_features(layer, box, (setting.label_field,))
        return [ProjectedPoint(s, off, _text(f[setting.label_field]) if setting.label_field
                               and _text(f[setting.label_field]) else layer.name(), "point")
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

    def _boreholes(self, b, xy, box, buffer, dem_layer) -> list[ProjectedPoint]:
        layer = self._vector(b.layer_id, "point", (b.id_field, b.elevation_field))
        found = self._point_features(layer, box, (b.id_field, b.elevation_field))
        out = []
        for (feature, (x, y)), (s, off) in _project(xy, found, buffer):
            bid = _text(feature[b.id_field])
            z_top = _number(feature[b.elevation_field]) if b.elevation_field else None
            if z_top is None and dem_layer is not None:
                try:
                    z_top = sample_point(dem_layer, x, y, self._crs_authid, self._project)
                except Exception as exc:
                    self._warn(b.layer_id, f"DEM sample at borehole failed: "
                                           f"{type(exc).__name__}: {exc}")
            log = self._log(b, bid) if bid else []
            out.append(ProjectedPoint(s, off, bid or layer.name(), "borehole", z_top, log))
        return out

    def _log(self, b, bid: str) -> list[LogInterval]:
        if not b.log_layer_id:
            return []
        fields = (b.log_id_field, b.top_field, b.bottom_field, b.lithology_field)
        try:
            layer = self._vector(b.log_layer_id, None, fields)
            request = QgsFeatureRequest().setFilterExpression(
                QgsExpression.createFieldEqualityExpression(b.log_id_field, bid))
            request.setSubsetOfAttributes([f for f in fields if f], layer.fields())
            rows = []
            for f in layer.getFeatures(request):
                top, bottom = _number(f[b.top_field]), _number(f[b.bottom_field])
                if top is not None and bottom is not None:
                    rows.append(LogInterval(top, bottom, _text(f[b.lithology_field])
                                            if b.lithology_field else ""))
        except _Skip as exc:
            self._warn(b.log_layer_id, f"log table skipped: {exc}")
            return []
        except Exception as exc:
            self._warn(b.log_layer_id, f"log table skipped: {type(exc).__name__}: {exc}")
            return []
        return sorted(rows, key=lambda r: (r.top, r.bottom))

    def _band(self, setting, xy, box) -> list[BandSegment]:
        layer = self._vector(setting.layer_id, "polygon", (setting.label_field,))
        polygons, labels = [], []
        for feature, geom in self._features(layer, box, (setting.label_field,)):
            label = _text(feature[setting.label_field]) or layer.name()
            for poly in (geom.asMultiPolygon() if geom.isMultipart() else [geom.asPolygon()]):
                rings = [np.array([[p.x(), p.y()] for p in ring]) for ring in poly if len(ring) >= 3]
                if rings:
                    polygons.append((rings[0], rings[1:]))
                    labels.append(label)
        return polygon_intervals(xy, polygons, labels) if polygons else []


def _project(xy, found, buffer):
    """[(item, (s, offset))] for the (feature, (x, y)) pairs within ``buffer``."""
    if not found:
        return []
    hits = project_points(xy, np.array([p for _f, p in found]), buffer)
    return [(found[i], (s, off)) for i, s, off in hits]


def _layer_ids(settings, line_ids=()) -> list[str]:
    ids = list(line_ids) + [s.layer_id for s in settings.point_layers]
    if settings.borehole is not None:
        ids += [settings.borehole.layer_id, settings.borehole.log_layer_id]
    if settings.band is not None:
        ids.append(settings.band.layer_id)
    ids.append(settings.dem_layer_id)
    return [i for i in ids if i]
