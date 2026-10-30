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
from .dem_sampling import sample_point, sample_profile

LOG_TAG = "Geophysics Workbench"
DEBOUNCE_MS = 300
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_GEOMETRY = {"line": Qgis.GeometryType.Line, "point": Qgis.GeometryType.Point,
             "polygon": Qgis.GeometryType.Polygon}
_SIGNALS = ("featureAdded", "featureDeleted", "geometryChanged", "attributeValueChanged",
            "dataChanged")


def voltage_label(value: str) -> str:
    """'380000;110000' -> '380 kV' (first number; >= 1000 means volts). Not a number: as is."""
    match = _NUMBER.match(value.strip())
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
    def __init__(self, project, crs_authid: str, on_change: Callable[[], None]):
        self._project = project
        self._crs_authid = crs_authid
        self._on_change = on_change
        self._logged: set[tuple[str, str]] = set()
        self._watched: dict[str, QgsMapLayer] = {}
        self._drop_slots: dict[str, Callable[[], None]] = {}
        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.setInterval(DEBOUNCE_MS)
        self._timer.timeout.connect(self._fire)
        project.layersRemoved.connect(self._removed)

    # -- public ---------------------------------------------------------------------------
    def items_for(self, profile: Profile) -> ContextItems:
        settings = read_settings(self._project)
        self._watch(settings)
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
        for s in settings.line_layers:
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

    # -- change watching ------------------------------------------------------------------
    def _watch(self, settings) -> None:
        wanted = {}
        for layer_id in _layer_ids(settings):
            layer = self._project.mapLayer(layer_id)
            if layer is not None:
                wanted[layer_id] = layer
        if (set(wanted) == set(self._watched)
                and all(wanted[k] is self._watched[k] for k in wanted)):
            return
        self._unwatch()
        for layer in wanted.values():
            slot = self._drop_slot(layer)
            layer.willBeDeleted.connect(slot)
            self._drop_slots[layer.id()] = slot
            for name in _SIGNALS:
                signal = getattr(layer, name, None)
                if signal is not None:
                    signal.connect(self._kick)
        self._watched = wanted

    def _unwatch(self) -> None:
        watched, self._watched = self._watched, {}
        slots, self._drop_slots = self._drop_slots, {}
        for layer in watched.values():
            if sip.isdeleted(layer):
                continue
            for name, slot in [(n, self._kick) for n in _SIGNALS] + [
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

    def _features(self, layer, box: QgsRectangle, fields: tuple, geometry: bool = True):
        """Features whose bbox meets ``box`` (store CRS) with only ``fields`` read;
        yields (feature, geometry in the store CRS)."""
        ct = self._to_store(layer)
        rect = box if ct is None else ct.transformBoundingBox(
            box, Qgis.TransformDirection.Reverse)
        request = QgsFeatureRequest().setFilterRect(rect)
        request.setSubsetOfAttributes([f for f in fields if f], layer.fields())
        for feature in layer.getFeatures(request):
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
        out = []
        for feature, geom in self._features(layer, box, (setting.label_field,)):
            label = _text(feature[setting.label_field]) if setting.label_field else ""
            if setting.powerline and label:
                label = voltage_label(label)
            kind = "powerline" if setting.powerline else "line"
            parts = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
            for part in parts:
                if len(part) >= 2:
                    pts = np.array([[p.x(), p.y()] for p in part])
                    out += line_crossings(xy, pts, label or layer.name(), kind)
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
            p = geom.asMultiPoint()[0] if geom.isMultipart() else geom.asPoint()
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


def _layer_ids(settings) -> list[str]:
    ids = [s.layer_id for s in settings.line_layers] + [s.layer_id for s in settings.point_layers]
    if settings.borehole is not None:
        ids += [settings.borehole.layer_id, settings.borehole.log_layer_id]
    if settings.band is not None:
        ids.append(settings.band.layer_id)
    ids.append(settings.dem_layer_id)
    return [i for i in ids if i]
