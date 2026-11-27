"""Pure geometry for third-party context on a section: crossings, buffered
projection, polygon bands and profile ties. NumPy + matplotlib.path only."""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import numpy as np
from matplotlib.path import Path

from .chainage import Chainage
from .ties import Tie

_EPS = 1e-9
_DEDUP = 1e-6


DEFAULT_LINE_RGB = (90, 90, 90)


@dataclass
class Crossing:
    s: float
    label: str
    kind: str          # "line" or "profile"
    angle_deg: float   # acute angle between profile and line, 0..90
    rgb: tuple = DEFAULT_LINE_RGB
    layer: str = ""    # source layer name


@dataclass
class LogInterval:
    top: float         # depths below the borehole top, metres
    bottom: float
    text: str          # the interval table's text field (shown as layer text)
    #: QgsFillSymbol clone and the QgsFeature that drives it (resolved on the main thread)
    symbol: object = None
    feature: object = None

    @property
    def lithology(self) -> str:        # name before 0.5
        return self.text

    def __deepcopy__(self, memo) -> "LogInterval":
        """The section snapshot deep-copies its context; QGIS objects cannot be pickled, so
        the symbol is cloned (``QgsSymbol.clone``), once per distinct symbol in the copy
        (intervals of one class share it), and the feature copied."""
        symbol = None
        if self.symbol is not None:
            key = id(self.symbol)
            if key not in memo:
                memo[key] = self.symbol.clone()
            symbol = memo[key]
        return LogInterval(self.top, self.bottom, self.text, symbol,
                           None if self.feature is None else type(self.feature)(self.feature))


@dataclass
class Curve:
    """One log curve of a borehole: samples sorted by depth (m below the collar); NULL = nan."""
    key: str           # curve_key(table layer id, field)
    name: str
    unit: str
    depth: np.ndarray
    values: np.ndarray


@dataclass
class ProjectedPoint:
    s: float
    offset: float      # signed, + = left of the profile
    label: str
    kind: str          # "point" or "borehole"
    z_top: float | None = None    # boreholes: elevation field, else DEM (see z_source)
    log: list[LogInterval] = field(default_factory=list)
    depth: float | None = None    # plain points: stick depth below the surface (m)
    entry: int = -1               # boreholes: index into ContextSettings.boreholes
    z_source: str = ""            # "field", "dem" or "" (then the drawn surface is used)
    z_dem: float | None = None    # DEM at the borehole, sampled even when the field is set
    total_depth: float | None = None
    curves: list[Curve] = field(default_factory=list)
    flagged: bool = False         # elevation field and DEM differ by more than the tolerance
    bid: str = ""                 # boreholes: the id in its layer ("" = none: label is the name)
    layer_id: str = ""            # boreholes: the borehole layer
    x: float | None = None        # boreholes: map position (the 3D view stands them there)
    y: float | None = None


def borehole_key(point: "ProjectedPoint") -> tuple[str, str] | None:
    """(layer id, borehole id) - how a borehole is hidden in a profile; ``None`` without an
    id (its label is then the layer's name, shared by every such borehole)."""
    if point.kind != "borehole" or not point.bid or not point.layer_id:
        return None
    return point.layer_id, point.bid


def collar_height(field_z: float | None, dem_z: float | None,
                  surface_z: float | None) -> tuple[float | None, str]:
    """A borehole's top: the elevation field, else the DEM, else the section's drawn surface.
    The second value says which one ("field", "dem", "surface"; "" when none)."""
    for value, source in ((field_z, "field"), (dem_z, "dem"), (surface_z, "surface")):
        if value is not None and np.isfinite(value):
            return float(value), source
    return None, ""


@dataclass(frozen=True)
class BoreholeView:
    """How the section draws one borehole entry's columns (from its Context layers entry)."""
    column_px: float = 16
    opacity: float = 1.0
    layer_text: bool = False
    curve_keys: tuple = ()


@dataclass
class BandSegment:
    s0: float
    s1: float
    label: str
    #: fill colour: the band layer's own style for this unit, or a colour per label;
    #: None = derived from the label when drawn
    rgb: tuple | None = None
    #: position of the strip among the shown strips, top first; its title (the row's title,
    #: or the layer's name)
    strip: int = 0
    title: str = ""


def strips_of(band: list[BandSegment]) -> list[tuple[str, list[BandSegment]]]:
    """(title, segments by s0) per strip that has segments, top first."""
    groups: dict[int, list[BandSegment]] = {}
    for seg in band:
        groups.setdefault(seg.strip, []).append(seg)
    return [(groups[k][0].title, sorted(groups[k], key=lambda b: b.s0)) for k in sorted(groups)]


@dataclass
class ContextItems:
    """Everything third-party drawn on one section, as plain data (safe for worker threads)."""
    crossings: list[Crossing] = field(default_factory=list)
    points: list[ProjectedPoint] = field(default_factory=list)
    band: list[BandSegment] = field(default_factory=list)
    ties: list[Tie] = field(default_factory=list)
    dem: tuple[np.ndarray, np.ndarray] | None = None    # (s ascending, z); nan = no data
    dem_tolerance: float = 1.0
    #: section look per borehole entry (``ProjectedPoint.entry``) and the curve styles by key
    borehole_views: dict = field(default_factory=dict)
    curve_styles: dict = field(default_factory=dict)
    #: the profile's field notes that are shown (``core.field_notes.FieldNote``)
    field_notes: list = field(default_factory=list)
    #: note id -> its look from the field-note layers' QGIS styles (``NoteLook``)
    note_looks: dict = field(default_factory=dict)

    def mirrored(self, length: float) -> "ContextItems":
        """The same items for the reversed profile: every s becomes ``length - s``. Offsets,
        angles and tie columns are unchanged; ``Tie.s_other`` stays."""
        dem = None
        if self.dem is not None:
            s, z = self.dem
            dem = (length - np.asarray(s, float)[::-1], np.asarray(z, float)[::-1].copy())
        return ContextItems(
            crossings=sorted((replace(c, s=length - c.s) for c in self.crossings),
                             key=lambda c: c.s),
            points=sorted((replace(p, s=length - p.s) for p in self.points), key=lambda p: p.s),
            band=sorted((replace(b, s0=length - b.s1, s1=length - b.s0) for b in self.band),
                        key=lambda b: b.s0),
            ties=sorted((replace(t, s=length - t.s, stretch=None if t.stretch is None else
                                 (length - t.stretch[1], length - t.stretch[0]))
                         for t in self.ties), key=lambda t: t.s),
            dem=dem, dem_tolerance=self.dem_tolerance,
            borehole_views=dict(self.borehole_views), curve_styles=dict(self.curve_styles),
            field_notes=sorted((_mirrored_note(n, length) for n in self.field_notes),
                               key=lambda n: n.s_from),
            note_looks=dict(self.note_looks))


def _mirrored_note(note, length: float):
    """A field note on the reversed profile (a stretch keeps from < to)."""
    if note.s_to is None:
        return replace(note, s_from=length - note.s_from)
    lo, hi = min(note.s_from, note.s_to), max(note.s_from, note.s_to)
    return replace(note, s_from=length - hi, s_to=length - lo)


def _cum(xy: np.ndarray) -> np.ndarray:
    return np.r_[0.0, np.cumsum(np.hypot(*np.diff(xy, axis=0).T))]


def _closed(ring) -> np.ndarray:
    r = np.asarray(ring, float)
    return r if np.array_equal(r[0], r[-1]) else np.vstack([r, r[:1]])


def _intersections(a_xy: np.ndarray, b_xy: np.ndarray) -> list[tuple[float, float, float]]:
    """All crossings of two polylines as (s_a, s_b, acute angle in degrees),
    sorted by s_a, with hits closer than 1e-6 m in both s_a and s_b merged."""
    a = np.asarray(a_xy, float)
    b = np.asarray(b_xy, float)
    ra, rb = np.diff(a, axis=0), np.diff(b, axis=0)
    la, lb = np.hypot(*ra.T), np.hypot(*rb.T)
    ca, cb = _cum(a), _cum(b)
    keep_a, keep_b = la > 0, lb > 0
    if not keep_a.any() or not keep_b.any():
        return []
    # segment i of a vs segment j of b: a_i + t r_i = b_j + u q_j
    r, q = ra[:, None, :], rb[None, :, :]
    w = b[None, :-1, :] - a[:-1, None, :]
    denom = r[..., 0] * q[..., 1] - r[..., 1] * q[..., 0]
    cross_wr = w[..., 0] * r[..., 1] - w[..., 1] * r[..., 0]
    cross_wq = w[..., 0] * q[..., 1] - w[..., 1] * q[..., 0]
    with np.errstate(divide="ignore", invalid="ignore"):
        t = cross_wq / denom
        u = cross_wr / denom
    ea, eb = _EPS / np.where(la > 0, la, 1.0)[:, None], _EPS / np.where(lb > 0, lb, 1.0)[None, :]
    ok = (np.abs(denom) > _EPS * la[:, None] * lb[None, :]) & keep_a[:, None] & keep_b[None, :]
    ok &= (t >= -ea) & (t <= 1 + ea) & (u >= -eb) & (u <= 1 + eb)
    ii, jj = np.nonzero(ok)
    hits: list[tuple[float, float, float]] = []
    for i, j in zip(ii, jj):
        sa = ca[i] + min(max(t[i, j], 0.0), 1.0) * la[i]
        sb = cb[j] + min(max(u[i, j], 0.0), 1.0) * lb[j]
        cosang = abs(ra[i] @ rb[j]) / (la[i] * lb[j])
        hits.append((float(sa), float(sb), float(np.degrees(np.arccos(min(cosang, 1.0))))))
    hits.sort()
    out: list[tuple[float, float, float]] = []
    for h in hits:
        if out and abs(h[0] - out[-1][0]) < _DEDUP and abs(h[1] - out[-1][1]) < _DEDUP:
            continue
        out.append(h)
    return out


def line_crossings(profile_xy, line_xy, label: str, kind: str = "line",
                   rgb: tuple = DEFAULT_LINE_RGB, layer: str = "") -> list[Crossing]:
    """Where ``line_xy`` crosses the profile, as chainage + acute angle."""
    return [Crossing(sa, label, kind, ang, rgb, layer)
            for sa, _sb, ang in _intersections(profile_xy, line_xy)]


def project_points(profile_xy, points_xy, buffer: float) -> list[tuple[int, float, float]]:
    """Points within ``buffer`` of the profile, as (index, s, signed offset).
    Points whose nearest profile point is an end they lie beyond are dropped."""
    pts = np.atleast_2d(np.asarray(points_xy, float))
    if pts.size == 0:
        return []
    ch = Chainage(profile_xy)
    s, off = ch.project(pts)
    xy = ch.xy
    d0, d1 = xy[0] - xy[1], xy[-1] - xy[-2]
    beyond0 = ((pts - xy[0]) @ d0) / np.hypot(*d0) > _EPS
    beyond1 = ((pts - xy[-1]) @ d1) / np.hypot(*d1) > _EPS
    beyond = ((s <= _EPS) & beyond0) | ((s >= ch.length - _EPS) & beyond1)
    keep = (np.abs(off) <= buffer) & ~beyond
    return [(int(i), float(s[i]), float(off[i])) for i in np.nonzero(keep)[0]]


def polygon_intervals(profile_xy, polygons, labels: list[str]) -> list[BandSegment]:
    """Stretches of the profile inside each polygon (exterior minus holes)."""
    ch = Chainage(profile_xy)
    raw: list[BandSegment] = []
    for (exterior, holes), label in zip(polygons, labels):
        rings = [_closed(r) for r in [exterior, *holes]]
        cuts = [0.0, ch.length]
        for ring in rings:
            cuts += [sa for sa, _sb, _ang in _intersections(ch.xy, ring)]
        cuts = np.unique(np.clip(cuts, 0.0, ch.length))
        paths = [Path(r) for r in rings]
        for s0, s1 in zip(cuts[:-1], cuts[1:]):
            if s1 - s0 < _DEDUP:
                continue
            mid = ch.to_xy(0.5 * (s0 + s1))
            if paths[0].contains_point(mid) and not any(p.contains_point(mid) for p in paths[1:]):
                raw.append(BandSegment(float(s0), float(s1), label))
    # merge touching or overlapping stretches per label, whatever the polygon order
    out: list[BandSegment] = []
    last: dict[str, BandSegment] = {}
    for seg in sorted(raw, key=lambda b: b.s0):
        prev = last.get(seg.label)
        if prev is not None and seg.s0 - prev.s1 < _DEDUP:
            prev.s1 = max(prev.s1, seg.s1)
        else:
            last[seg.label] = seg
            out.append(seg)
    return out


#: crossings of the same two profiles closer than this along both profiles (metres, or this
#: share of the shorter profile's length when that is more) follow each other ...
STRETCH_GAP_M = 10.0
STRETCH_GAP_SHARE = 0.05
#: ... and this many of them in a row are one shared stretch
STRETCH_MIN_CROSSINGS = 3


@dataclass
class TieHit:
    """Where two profiles tie: ``s`` on the first, ``s_other`` on the second, their gap there
    (0 at a crossing); ``stretch`` (start, end on the first) when they run along each other,
    the tie then at the stretch's middle."""
    s: float
    s_other: float
    distance: float
    stretch: tuple[float, float] | None = None


def _groups(hits: list[tuple], gap: float) -> list[list[int]]:
    """Indices of ``hits`` ((s_a, s_b, …)) in groups: two hits less than ``gap`` apart along
    both profiles belong together, and so do the hits linked through such pairs. The same
    groups whichever profile is first; each group in the order of ``hits``."""
    parent = list(range(len(hits)))

    def root(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(hits)):
        for j in range(i + 1, len(hits)):
            if abs(hits[i][0] - hits[j][0]) < gap and abs(hits[i][1] - hits[j][1]) < gap:
                parent[root(j)] = root(i)
    out: dict[int, list[int]] = {}
    for i in range(len(hits)):
        out.setdefault(root(i), []).append(i)
    return sorted(out.values(), key=lambda g: g[0])


def _first_of_pair(a, b) -> bool:
    """True when ``a`` is the profile whose side a shared stretch's tie is worked out from
    (any fixed choice that does not depend on which profile asks)."""
    return np.asarray(a, float).tobytes() <= np.asarray(b, float).tobytes()


def tie_hits(a_xy, b_xy, near_miss: float) -> list[TieHit]:
    """Ties between two profiles: every true crossing (distance 0), except that crossings
    following each other closely along both profiles (``STRETCH_GAP_M`` /
    ``STRETCH_GAP_SHARE`` of the shorter one), at least ``STRETCH_MIN_CROSSINGS`` of them,
    are one shared stretch with one tie at its middle (on the other profile: the point there
    nearest to that middle). The pair gives the same crossings, stretches and ties whichever
    profile asks: the tie of a stretch is worked out from the same one of the two. Without a
    crossing, the single closest approach if within ``near_miss``. Every tie between
    profiles (markers, tie strips, the ties panel, interpretation marks) comes from here."""
    hits = _intersections(a_xy, b_xy)
    if not hits:
        near = _near_miss(a_xy, b_xy, near_miss)
        return [] if near is None else [TieHit(*near)]
    ca, cb = Chainage(a_xy), Chainage(b_xy)
    shorter = min(float(_cum(ca.xy)[-1]), float(_cum(cb.xy)[-1]))
    gap = max(STRETCH_GAP_M, STRETCH_GAP_SHARE * shorter)
    a_first = _first_of_pair(a_xy, b_xy)
    out = []
    for group in _groups(hits, gap):
        if len(group) < STRETCH_MIN_CROSSINGS:
            out += [TieHit(hits[i][0], hits[i][1], 0.0) for i in group]
            continue
        sa = [hits[i][0] for i in group]
        sb = [hits[i][1] for i in group]
        if a_first:
            s = 0.5 * (min(sa) + max(sa))
            s_other = float(np.ravel(cb.project(ca.to_xy(s)[None, :])[0])[0])
        else:
            s_other = 0.5 * (min(sb) + max(sb))
            s = float(np.ravel(ca.project(cb.to_xy(s_other)[None, :])[0])[0])
        out.append(TieHit(s, s_other, 0.0, (min(sa), max(sa))))
    return sorted(out, key=lambda h: h.s)


def profile_ties(a_xy, b_xy, near_miss: float) -> list[tuple[float, float, float]]:
    """Ties between two profiles as (s_a, s_b, distance) (``tie_hits`` without the
    stretches)."""
    return [(h.s, h.s_other, h.distance) for h in tie_hits(a_xy, b_xy, near_miss)]


def _near_miss(a_xy, b_xy, near_miss: float) -> tuple[float, float, float] | None:
    """(s_a, s_b, distance) of the closest approach of two profiles that do not cross, when
    within ``near_miss``."""
    ca, cb = Chainage(a_xy), Chainage(b_xy)
    best = None   # (distance, s_a, s_b)
    for one, other, flip in ((ca, cb, False), (cb, ca, True)):
        cum = _cum(one.xy)
        s_o, off = other.project(one.xy)
        k = int(np.argmin(np.abs(off)))
        cand = (float(abs(off[k])), float(cum[k]), float(s_o[k]))
        if flip:
            cand = (cand[0], cand[2], cand[1])
        if best is None or cand[0] < best[0]:
            best = cand
    if best is not None and best[0] <= near_miss:
        return best[1], best[2], best[0]
    return None
