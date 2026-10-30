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

from .context_render import (context_z_values, draw_band, draw_crossings, draw_dem, draw_ties)
from .context_render_points import draw_points
from .data import SectionDataProvider, SectionSnapshot, cell_path_groups, identify_layers

SOURCE_ID = "geophysics_workbench"
SOURCE_NAME = "Geophysics Workbench"
RESULTS_TYPE = "geophysics_workbench_section"
CURVE_TOLERANCE = 1.0          # metres: end points and length of canvas curve vs profile
_EMPTY_Z = (math.inf, -math.inf)   # neutral for the canvas' min/max union of z ranges
_MM = Qgis.RenderUnit.Millimeters
#: drawn over models beyond the station coverage: white at 55 %, marked but readable
BEYOND_COLOUR = QColor(255, 255, 255, 140)


def _log_failure(what: str, exc: BaseException) -> None:
    """Log instead of raising: these callbacks are invoked from C++ (generateProfile on
    worker threads), where a Python exception would reach sys.excepthook / abort painting.
    QgsMessageLog.logMessage is safe to call from any thread."""
    QgsMessageLog.logMessage(f"Section {what} failed: {type(exc).__name__}: {exc}",
                             SOURCE_NAME, Qgis.MessageLevel.Critical)


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
        self._layers = layers          # [(opacity, [(QColor, QPainterPath), ...])] bottom first
        self._z = z_range
        self._station_z = station_z    # tick elevations, aligned with snapshot.stations
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
            painter.save()
            try:
                painter.setTransform(wt, True)      # draw in (chainage, elevation) space
                self._draw_cells(painter)
                self._draw_beyond_stations(painter)
                self._draw_topography(painter, rc)
            finally:
                painter.restore()
            ctx = self.snapshot.context
            if ctx is not None and topo is not None:
                draw_band(painter, rc, wt, ctx, topo)
            self._draw_stations(painter, rc, wt)
            if ctx is not None:
                z_range = (self._z[0], self._z[1])
                draw_dem(painter, rc, wt, ctx, self.snapshot.stations, self._station_z)
                draw_crossings(painter, rc, wt, ctx, z_range)
                draw_points(painter, rc, wt, ctx, topo)
                draw_ties(painter, rc, wt, ctx, z_range)
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
        for opacity, groups in self._layers:
            painter.setOpacity(opacity)
            outline = vector and opacity >= 1.0     # translucent outlines would double-blend
            painter.setPen(Qt.PenStyle.NoPen)
            for colour, path in groups:
                painter.setBrush(QBrush(colour))
                if outline:
                    pen = QPen(colour, 0)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                painter.drawPath(path)
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

    def _draw_stations(self, painter, rc, wt):
        stations, z = self.snapshot.stations, self._station_z
        if not stations or z is None:
            return
        half = max(3.0, rc.convertToPainterUnits(1.0, _MM))
        font = QFont(painter.font())
        font.setPixelSize(max(10, round(rc.convertToPainterUnits(3.0, _MM))))
        painter.setFont(font)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(QPen(QColor(0, 0, 0), 1))
        painter.setBrush(QBrush(QColor(0, 0, 0)))
        for (si, label), zi in zip(stations, z.tolist()):
            p = wt.map(QPointF(si, zi))
            x, y = p.x(), p.y()
            # apex on the surface, base above it
            painter.drawPolygon(QPolygonF([QPointF(x, y), QPointF(x - half, y - 2 * half),
                                           QPointF(x + half, y - 2 * half)]))
            if label:
                fs = font.pixelSize()
                box = QRectF(x - 4 * fs, y - 2 * half - fs * 1.6, 8 * fs, fs * 1.4)
                painter.drawText(box, int(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom),
                                 label)


class WorkbenchProfileGenerator(QgsAbstractProfileGenerator):
    def __init__(self, snapshot: SectionSnapshot | None, owner: "WorkbenchProfileSource"):
        super().__init__()
        self._snapshot = snapshot
        self._owner = owner
        self._feedback = QgsFeedback()
        self._results = None

    def sourceId(self):
        return SOURCE_ID

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
                groups = [(QColor(*(int(c) for c in rgba)), _path_from_elements(elems))
                          for rgba, elems in cell_path_groups(layer.mesh, layer.style.scale)]
                layers.append((float(layer.style.opacity), groups))
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
            zs.extend(context_z_values(snap))
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
