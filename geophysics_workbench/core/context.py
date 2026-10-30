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


@dataclass
class Crossing:
    s: float
    label: str
    kind: str          # "line", "powerline" or "profile"
    angle_deg: float   # acute angle between profile and line, 0..90


@dataclass
class LogInterval:
    top: float         # depths below the borehole top, metres
    bottom: float
    lithology: str


@dataclass
class ProjectedPoint:
    s: float
    offset: float      # signed, + = left of the profile
    label: str
    kind: str          # "point" or "borehole"
    z_top: float | None = None
    log: list[LogInterval] = field(default_factory=list)


@dataclass
class BandSegment:
    s0: float
    s1: float
    label: str


@dataclass
class ContextItems:
    """Everything third-party drawn on one section, as plain data (safe for worker threads)."""
    crossings: list[Crossing] = field(default_factory=list)
    points: list[ProjectedPoint] = field(default_factory=list)
    band: list[BandSegment] = field(default_factory=list)
    ties: list[Tie] = field(default_factory=list)
    dem: tuple[np.ndarray, np.ndarray] | None = None    # (s ascending, z); nan = no data
    dem_tolerance: float = 1.0

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
            band=sorted((BandSegment(length - b.s1, length - b.s0, b.label) for b in self.band),
                        key=lambda b: b.s0),
            ties=sorted((replace(t, s=length - t.s) for t in self.ties), key=lambda t: t.s),
            dem=dem, dem_tolerance=self.dem_tolerance)


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


def line_crossings(profile_xy, line_xy, label: str, kind: str) -> list[Crossing]:
    """Where ``line_xy`` crosses the profile, as chainage + acute angle."""
    return [Crossing(sa, label, kind, ang) for sa, _sb, ang in _intersections(profile_xy, line_xy)]


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


def profile_ties(a_xy, b_xy, near_miss: float) -> list[tuple[float, float, float]]:
    """Ties between two profiles as (s_a, s_b, distance). True crossings have
    distance 0; without one, the single closest approach if within ``near_miss``."""
    hits = _intersections(a_xy, b_xy)
    if hits:
        return [(sa, sb, 0.0) for sa, sb, _ang in hits]
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
        return [(best[1], best[2], best[0])]
    return []
