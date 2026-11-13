"""Native QGIS elevation-profile source drawing the stored ERT sections.

``createProfileGenerator`` and ``renderResults`` run on the main thread; ``generateProfile``
runs on Qt worker threads for the profile canvas (main thread during layout export). So
the generator only sees a plain-data ``SectionSnapshot`` taken on the main thread, and
does all per-cell work with numpy: cells are grouped by colour and each group is streamed
into one ``QPainterPath`` from a byte buffer (no per-cell Python objects).
"""
from __future__ import annotations

import math
import struct

import numpy as np
from qgis.core import (Qgis, QgsAbstractProfileGenerator, QgsAbstractProfileResults,
                       QgsAbstractProfileSource, QgsApplication, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsDoubleRange, QgsFeedback, QgsMessageLog,
                       QgsProfileIdentifyResults)
from qgis.PyQt.QtCore import QByteArray, QDataStream, QPointF, QRectF, Qt
from qgis.PyQt.QtGui import (QBrush, QColor, QFont, QPaintEngine, QPainter, QPainterPath, QPen,
                             QPolygonF)

from .context_render import context_z_values, draw_band, draw_over_stations
from .data import SectionDataProvider, SectionSnapshot, identify_layers, matching_profiles
from .topography import measured_line

SOURCE_ID = "geophysics_workbench"
SOURCE_NAME = "Geophysics Workbench"
RESULTS_TYPE = "geophysics_workbench_section"
CURVE_TOLERANCE = 1.0          # metres: end points and length of canvas curve vs profile
_EMPTY_Z = (math.inf, -math.inf)   # neutral for the canvas' min/max union of z ranges
_MM = Qgis.RenderUnit.Millimeters
#: drawn over models beyond the station coverage: white at 55 %, marked but readable
BEYOND_COLOUR = QColor(255, 255, 255, 140)
#: thin line through the measured station heights when the models hang from the DEM
MEASURED_COLOUR = QColor(70, 70, 70)


def _log_failure(what: str, exc: BaseException) -> None:
    """Log instead of raising: these callbacks are invoked from C++ (generateProfile on
    worker threads), where a Python exception would reach sys.excepthook / abort painting.
    QgsMessageLog.logMessage is safe to call from any thread."""
    QgsMessageLog.logMessage(f"Section {what} failed: {type(exc).__name__}: {exc}",
                             SOURCE_NAME, Qgis.MessageLevel.Critical)


def _guarded(what: str, painter, draw, *args) -> None:
    """One drawing step on its own: a failure in it is logged, and the painter state and
    the other steps (the stations above all) survive it."""
    painter.save()
    try:
        draw(painter, *args)
    except Exception as exc:
        _log_failure(f"drawing ({what})", exc)
    finally:
        painter.restore()


def _path_from_elements(elems: np.ndarray) -> QPainterPath:
    """Deserialise a PATH_ELEMENT array into a QPainterPath (QDataStream layout:
    int32 count, elements, int32 cStart, int32 fill rule; big-endian)."""
    n = len(elems)
    buf = (struct.pack(">i", n) + elems.tobytes()
           + struct.pack(">ii", max(n - 5, 0), Qt.FillRule.WindingFill.value))
    data = QByteArray(buf)          # keep a reference: the stream reads it lazily
    stream = QDataStream(data)      # read-only constructor (const QByteArray &)
    path = QPainterPath()
    stream >> path
    if stream.status() != QDataStream.Status.Ok:
        raise ValueError(f"could not build a path from {n} cell elements")
    return path


class WorkbenchProfileResults(QgsAbstractProfileResults):
    def __init__(self, snapshot: SectionSnapshot | None, layers: list, z_range: tuple,
                 station_z: np.ndarray | None = None, s_range: tuple | None = None):
        super().__init__()
        self.snapshot = snapshot
        self._layers = layers          # [display_render.LayerDrawing] bottom first
        self._contour_px = 1.0
        self._minor_px = 1.0
        self._z = z_range
        self._station_z = station_z    # tick elevations, aligned with snapshot.stations:
        #                                the measured height, else the surface (or mesh top)
        self._s = s_range              # (min, max) chainage of the drawn layers
        self.render_count = 0

    def type(self):
        return RESULTS_TYPE

    def zRange(self):
        return QgsDoubleRange(*self._z)

    def asGeometries(self):
        return []

    def distanceToHeightMap(self):
        return {}

    def sampledPoints(self):
        return []

    def asFeatures(self, type, feedback=None):
        return []

    def identify(self, *args):
        """Values under a *canvas* point: ``point.distance()`` is distance along the
        requested curve, i.e. mirrored profile chainage when the curve runs end-to-start
        (the snapshot is already mirrored). ``SectionDataProvider.identify`` instead takes
        forward profile chainage."""
        # overloads: (QgsProfilePoint, context) and (distance range, elevation range, context)
        if self.snapshot is None or len(args) != 2:
            return []
        try:
            point = args[0]
            hits = identify_layers(self.snapshot.layers, point.distance(), point.elevation())
            return [QgsProfileIdentifyResults(None, [hit]) for hit in hits]
        except Exception as exc:              # called from C++: never raise
            _log_failure("identify", exc)
            return []

    # -- drawing ---------------------------------------------------------------------------
    def renderResults(self, context):
        self.render_count += 1
        try:
            self._render(context)
        except Exception as exc:              # called from C++ paint code: never raise
            _log_failure("drawing", exc)

    def _render(self, context):
        rc = context.renderContext()
        painter = rc.painter()
        if painter is None or self.snapshot is None:
            return
        wt = context.worldTransform()
        topo = self.snapshot.topo
        painter.save()
        try:
            clip = _plot_rect(context, wt)
            if clip is not None:                # never draw past the canvas or layout frame
                painter.setClipRect(clip, Qt.ClipOperation.IntersectClip)
            painter.save()
            try:
                painter.setTransform(wt, True)      # draw in (chainage, elevation) space
                from .display_render import contour_pen_mm
                self._contour_px = max(1.0, rc.convertToPainterUnits(contour_pen_mm(True), _MM))
                # minor levels: thinner, but never a hairline that vanishes on screen
                self._minor_px = max(0.6, rc.convertToPainterUnits(contour_pen_mm(False), _MM))
                self._draw_cells(painter)
                self._draw_beyond_stations(painter)
                self._draw_topography(painter, rc)
                self._draw_measured_line(painter, rc)
            finally:
                painter.restore()
            _guarded("contour labels", painter, self._draw_contour_labels, rc, wt)
            _guarded("reading markers", painter, self._draw_markers, rc, wt)
            ctx = self.snapshot.context
            if ctx is not None and topo is not None:
                _guarded("geology band", painter, draw_band, rc, wt, ctx, topo)
            self._draw_stations(painter, rc, wt)
            if ctx is not None:
                heights = self.snapshot.station_heights
                measured = self._station_z if heights is None else heights
                _guarded("context", painter, draw_over_stations, rc, wt, ctx,
                         self.snapshot.stations, measured, topo, (self._z[0], self._z[1]),
                         self.snapshot.layers)
            if self.snapshot.interpretation or self.snapshot.interp_compare:
                from .interp_render import draw_interpretation
                _guarded("interpretation", painter, draw_interpretation, rc, wt,
                         self.snapshot.interpretation, self.snapshot.interp_features,
                         self.snapshot.interp_symbols, self.snapshot.interp_compare)
            if self.snapshot.interp_crossings:
                from .interp_render import draw_crossing_marks
                _guarded("crossing interpretation", painter, draw_crossing_marks, rc, wt,
                         self.snapshot.interp_crossings, ctx.points if ctx is not None else [],
                         self.snapshot.interp_features, self.snapshot.interp_symbols,
                         ctx.borehole_views if ctx is not None else None)
        finally:
            painter.restore()

    def _draw_cells(self, painter):
        # Raster targets (canvas, image export): no antialiasing, so abutting cells leave
        # no seams and the fill stays cheap (~25 ms per 100k cells vs ~180 ms with AA).
        # Vector targets (PDF/SVG): viewers antialias abutting fills, so outline each cell
        # in its own fill colour to hide the hairline seams.
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        engine = painter.paintEngine()
        vector = engine is not None and engine.type() != QPaintEngine.Type.Raster
        for drawing in self._layers:
            opacity = drawing.opacity
            painter.setOpacity(opacity)
            outline = vector and opacity >= 1.0     # translucent outlines would double-blend
            painter.setPen(Qt.PenStyle.NoPen)
            for colour, path in drawing.groups:
                painter.setBrush(QBrush(colour))
                if outline:
                    pen = QPen(colour, 0)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                painter.drawPath(path)
            if drawing.field is not None:
                image, rect = drawing.field
                painter.save()
                if drawing.clip is not None:
                    painter.setClipPath(drawing.clip, Qt.ClipOperation.IntersectClip)
                painter.drawImage(rect, image)
                painter.restore()
            if drawing.contours:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for colour, path, _lines, _text, major in drawing.contours:
                    pen = QPen(colour, self._contour_px if major else self._minor_px)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                    painter.drawPath(path)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        painter.setOpacity(1.0)

    def _draw_markers(self, painter, rc, wt):
        """Readings layers in Points mode: a filled dot of MARKER_MM per reading, one path per
        colour (thousands of readings draw in a few calls)."""
        from .display_render import MARKER_MM
        drawings = [d for d in self._layers if d.markers]
        if not drawings:
            return
        r = max(1.5, rc.convertToPainterUnits(MARKER_MM, _MM) / 2)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        for drawing in drawings:
            painter.setOpacity(drawing.opacity)
            for colour, pts in drawing.markers:
                path = QPainterPath()
                for s, z in pts:
                    c = wt.map(QPointF(float(s), float(z)))
                    path.addEllipse(c, r, r)
                painter.setBrush(QBrush(colour))
                painter.drawPath(path)
        painter.setOpacity(1.0)

    def _draw_contour_labels(self, painter, rc, wt):
        """One label per contour polyline, at its mid-length on screen, along the line, with
        a halo in the palette's base colour; skipped on lines too short for it."""
        from qgis.PyQt.QtGui import QFontMetricsF, QGuiApplication, QPalette

        from .display_render import LABEL_MM
        drawings = [d for d in self._layers if d.contours]
        if not drawings:
            return
        font = QFont(painter.font())
        font.setPixelSize(max(8, round(rc.convertToPainterUnits(LABEL_MM, _MM))))
        metrics = QFontMetricsF(font)
        halo = QGuiApplication.palette().color(QPalette.ColorRole.Base)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        for drawing in drawings:
            painter.setOpacity(drawing.opacity)
            for colour, _path, lines, text, _major in drawing.contours:
                if not text:
                    continue
                width = metrics.horizontalAdvance(text)
                for line in lines:
                    pts = [wt.map(QPointF(float(s), float(z))) for s, z in line]
                    seg = np.array([[b.x() - a.x(), b.y() - a.y()] for a, b in zip(pts, pts[1:])])
                    if not len(seg):
                        continue
                    lengths = np.hypot(seg[:, 0], seg[:, 1])
                    total = float(lengths.sum())
                    if total < 3 * width:
                        continue
                    i = int(np.searchsorted(np.cumsum(lengths), total / 2))
                    i = min(i, len(seg) - 1)
                    dx, dy = seg[i]
                    angle = float(np.degrees(np.arctan2(dy, dx)))
                    if angle > 90 or angle < -90:           # keep text upright
                        angle += 180
                    mid = QPointF((pts[i].x() + pts[i + 1].x()) / 2,
                                  (pts[i].y() + pts[i + 1].y()) / 2)
                    label = QPainterPath()
                    label.addText(QPointF(-width / 2, metrics.ascent() / 2 - 1), font, text)
                    painter.save()
                    painter.translate(mid)
                    painter.rotate(angle)
                    painter.setPen(QPen(halo, 3))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawPath(label)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(colour))
                    painter.drawPath(label)
                    painter.restore()
        painter.setOpacity(1.0)

    def _beyond_rects(self) -> list[QRectF]:
        """Chainage ranges of the drawn layers outside the station coverage, over the
        drawn z range, as (chainage, elevation) rectangles."""
        cover = self.snapshot.coverage
        if cover is None or self._s is None or not self._layers:
            return []
        (s0, s1), (z0, z1) = self._s, self._z
        spans = [(s0, cover[0]), (cover[1], s1)]
        return [QRectF(QPointF(a, z0), QPointF(b, z1)).normalized() for a, b in spans if b > a]

    def _draw_beyond_stations(self, painter):
        rects = self._beyond_rects()
        if not rects:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(BEYOND_COLOUR))
        for rect in rects:
            painter.drawRect(rect)

    def _draw_topography(self, painter, rc):
        topo = self.snapshot.topo
        if topo is None or len(topo[0]) < 2:
            return
        pen = QPen(QColor(0, 0, 0), max(1.0, rc.convertToPainterUnits(0.26, _MM)))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPolyline(QPolygonF([QPointF(s, z) for s, z in zip(*topo)]))

    def _draw_measured_line(self, painter, rc):
        """When the models hang from the DEM, a thin solid line joins the measured station
        heights, so the two surfaces can be compared (spec 4.2: show both)."""
        snap = self.snapshot
        line = measured_line(snap.stations, snap.station_heights) if snap.dem_topo else None
        if line is None:
            return
        pen = QPen(MEASURED_COLOUR, max(1.0, rc.convertToPainterUnits(0.15, _MM)))
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.drawPolyline(QPolygonF([QPointF(s, z) for s, z in zip(*line)]))

    def _draw_stations(self, painter, rc, wt):
        stations, z = self.snapshot.stations, self._station_z
        if not stations or z is None:
            return
        half = max(3.0, rc.convertToPainterUnits(1.0, _MM))
        font = QFont(painter.font())
        font.setPixelSize(max(10, round(rc.convertToPainterUnits(3.0, _MM))))
        painter.setFont(font)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if self.snapshot.electrode_kind in DERIVED_KINDS:
            # worked out at draw time, not surveyed: the same pen, dashed, nothing filled
            painter.setPen(QPen(QColor(0, 0, 0), 1, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
        else:
            painter.setPen(QPen(QColor(0, 0, 0), 1))
            painter.setBrush(QBrush(QColor(0, 0, 0)))
        fm = painter.fontMetrics()
        spans = [(wt.map(QPointF(si, 0.0)).x(), fm.horizontalAdvance(label))
                 for si, label in stations if label]
        keep = iter(station_labels_to_draw(spans))
        for (si, label), zi in zip(stations, z.tolist()):
            show = bool(label) and next(keep)           # consumed for every labelled station
            if not math.isfinite(zi):                   # no measured height and no surface
                continue
            p = wt.map(QPointF(si, zi))
            x, y = p.x(), p.y()
            # apex on the surface, base above it
            painter.drawPolygon(QPolygonF([QPointF(x, y), QPointF(x - half, y - 2 * half),
                                           QPointF(x + half, y - 2 * half)]))
            if show:
                fs = font.pixelSize()
                box = QRectF(x - 4 * fs, y - 2 * half - fs * 1.6, 8 * fs, fs * 1.4)
                painter.drawText(box, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom),
                                 label)


DERIVED_KINDS = ("readings", "spacing", "guessed")


def station_labels_to_draw(spans, gap: float = 6.0) -> list[bool]:
    """Which station numbers to draw: ``spans`` are (centre x, text width) in drawing order;
    a number that would touch the last drawn one is skipped (its triangle stays)."""
    out, last_right, last_left = [], None, None
    for x, width in spans:
        left, right = x - width / 2, x + width / 2
        ok = last_right is None or left >= last_right + gap or right <= last_left - gap
        if ok:
            last_left, last_right = left, right
        out.append(ok)
    return out


def _plot_rect(context, wt):
    """The plot area in device units, from the context's distance and elevation ranges."""
    d, e = context.distanceRange(), context.elevationRange()
    values = (d.lower(), d.upper(), e.lower(), e.upper())
    if d.isInfinite() or e.isInfinite() or not all(np.isfinite(v) for v in values):
        return None
    a = wt.map(QPointF(d.lower(), e.upper()))
    b = wt.map(QPointF(d.upper(), e.lower()))
    return QRectF(a, b).normalized()


class WorkbenchProfileGenerator(QgsAbstractProfileGenerator):
    def __init__(self, snapshot: SectionSnapshot | None, owner: "WorkbenchProfileSource"):
        super().__init__()
        self._snapshot = snapshot
        self._owner = owner
        self._feedback = QgsFeedback()
        self._results = None

    def sourceId(self):
        owner = getattr(self, "_owner_id", None)
        return owner or SOURCE_ID

    def type(self):
        return RESULTS_TYPE

    def feedback(self):
        return self._feedback

    def generateProfile(self, context=None):
        # worker thread (canvas) or main thread (layout export): never raise into C++
        try:
            return self._generate()
        except Exception as exc:
            _log_failure("generation", exc)
            self._results = None
            return False

    def _generate(self) -> bool:
        # touch only the snapshot (plain data) and value-type Qt classes
        snap = self._snapshot
        layers, zs, tops, ss = [], [], [], []
        station_z = None
        if snap is not None:
            for layer in snap.layers:
                if self._feedback.isCanceled():
                    return False
                if layer.mesh is None or not layer.style.visible or layer.style.scale is None:
                    continue
                from .display_render import build_drawing
                layers.append(build_drawing(layer, snap.topo))
                smin, smax, zmin, zmax = layer.mesh.bounds()
                ss.extend((smin, smax))
                zs.extend((zmin, zmax))
                tops.append(zmax)
            s = np.array([st[0] for st in snap.stations], dtype=float)
            if snap.topo is not None and len(snap.topo[1]):
                zs.extend((float(np.min(snap.topo[1])), float(np.max(snap.topo[1]))))
                station_z = np.interp(s, *snap.topo)
            elif tops:                                  # no topography: top of the meshes
                station_z = np.full(len(s), max(tops))
            heights = snap.station_heights
            if heights is not None and len(heights) == len(s) and np.isfinite(heights).any():
                # ticks at the measured heights, whatever surface the models hang from
                measured = np.isfinite(heights)
                station_z = np.where(measured, heights,
                                     np.nan if station_z is None else station_z)
                zs.extend(heights[measured].tolist())
            zs.extend(context_z_values(snap.context, snap.topo))
        z_range = (min(zs), max(zs)) if zs else _EMPTY_Z
        s_range = (min(ss), max(ss)) if ss else None
        self._results = WorkbenchProfileResults(snap, layers, z_range, station_z, s_range)
        return True

    def takeResults(self):
        results, self._results = self._results, None
        if results is not None:
            self._owner.last_results = results     # test/debug hook only
        return results


class WorkbenchProfileSource(QgsAbstractProfileSource):
    def __init__(self, provider: SectionDataProvider):
        super().__init__()
        self.provider = provider
        # Test/debug hook: the most recent results handed to QGIS. C++ owns generators
        # and results (and deletes them); this is not a keep-alive and may point at a
        # deleted wrapper once QGIS discards those results.
        self.last_results = None

    def profileSourceId(self):
        return SOURCE_ID

    def profileSourceName(self):
        return SOURCE_NAME

    def _curve_xy(self, request) -> np.ndarray | None:
        curve = request.profileCurve()
        if curve is None:
            return None
        line = curve.curveToLine()
        store_crs = QgsCoordinateReferenceSystem(self.provider.store.crs_authid)
        if request.crs().isValid() and request.crs() != store_crs:
            line.transform(QgsCoordinateTransform(request.crs(), store_crs,
                                                  request.transformContext()))
        return np.array([(line.xAt(i), line.yAt(i)) for i in range(line.numPoints())],
                        dtype=float).reshape(-1, 2)

    def createProfileGenerator(self, request):
        # main thread: resolve the profile and copy everything into a snapshot
        snapshot = None
        try:
            xy = self._curve_xy(request)
            match = None if xy is None else self.provider.match_curve(xy, CURVE_TOLERANCE)
            if match is not None:
                profile, reverse = match
                snapshot = self.provider.snapshot(profile.id, reverse=reverse)
        except Exception as exc:              # never raise into QGIS' C++ caller
            _log_failure("profile lookup", exc)
            snapshot = None
        return WorkbenchProfileGenerator(snapshot, self)


def register_source(provider: SectionDataProvider) -> WorkbenchProfileSource:
    """Register a source for ``provider``, replacing any registered workbench source.

    The registry owns the source. Replacing it **destroys the previous source**, so
    callers must first detach that source everywhere it is used (``canvas.setSources([])``
    on every elevation-profile canvas, and clear the sources of any layout elevation-profile
    items); canvases and layout items hold raw pointers to it."""
    registry = QgsApplication.profileSourceRegistry()
    if registry.findSourceById(SOURCE_ID) is not None:
        registry.unregisterProfileSource(SOURCE_ID)
    source = WorkbenchProfileSource(provider)
    if not registry.registerProfileSource(source):
        raise RuntimeError("could not register the Geophysics Workbench profile source")
    return source


def unregister_source(source: WorkbenchProfileSource) -> None:
    """Remove ``source`` from the registry, which **destroys** it; no-op if it is not
    the registered workbench source (e.g. already replaced). Callers must first detach it
    from the canvases they own (``canvas.setSources([])``) and from layout elevation-profile
    items. Canvases the plugin does not own, such as QGIS's own Elevation Profile tool,
    add registered sources and drop unregistered ones themselves in QGIS 4.2
    (tests/section/test_registry_canvases.py)."""
    registry = QgsApplication.profileSourceRegistry()
    if registry.findSourceById(SOURCE_ID) is source:
        registry.unregisterProfileSource(SOURCE_ID)


class FrameProfileSource(WorkbenchProfileSource):
    """One plate frame: its profile with the frame's own look (the frame item is given its
    profile's curve; any other curve gets nothing drawn)."""

    def __init__(self, provider: SectionDataProvider, frame):
        super().__init__(provider)
        self.frame = frame

    def profileSourceId(self):
        return frame_source_id(self.frame.frame_id)

    def profileSourceName(self):
        return f"{SOURCE_NAME} (plate frame)"

    def createProfileGenerator(self, request):
        # QGIS hands every registered source to every profile canvas and layout item: draw
        # only for this frame's own profile line (either direction), nothing elsewhere
        snapshot = None
        try:
            xy = self._curve_xy(request)
            profile = self.provider._profile(self.frame.profile_id)
            match = None
            if xy is not None and profile is not None:
                match = matching_profiles([profile], xy, CURVE_TOLERANCE)
            if match:
                snapshot = self.provider.snapshot(self.frame.profile_id, reverse=match[0][2],
                                                  look=self.frame.look)
        except Exception as exc:              # never raise into QGIS' C++ caller
            _log_failure("plate frame", exc)
            snapshot = None
        gen = WorkbenchProfileGenerator(snapshot, self)
        gen._owner_id = self.profileSourceId()
        return gen


def frame_source_id(frame_id: str) -> str:
    return f"{SOURCE_ID}:frame:{frame_id}"
