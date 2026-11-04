"""Interpretation drawn on sections: the data model and its geometry (no QGIS/Qt).

The section-space shape of a piece (profile id + chainage/elevation per vertex) is the truth;
its real-world 3D geometry and map footprint are derived from it with the profile's
``Chainage``, exactly on bent profiles (every profile vertex a piece spans is inserted).
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

import numpy as np

KINDS = ("line", "polygon", "point")
CONFIDENCE = ("certain", "probable", "uncertain")
STARTER_TYPES = ["layer boundary", "top of bedrock", "water table", "fault", "anomaly", "body",
                 "unreliable", "artefact (3D effect)", "pick"]


@dataclass
class InterpVersion:
    id: str
    name: str
    frozen: bool
    created: str
    note: str = ""


@dataclass
class InterpFeature:
    id: str
    version_id: str
    type: str = ""
    letter: str = ""
    confidence: str = "probable"
    note: str = ""
    author: str = ""
    created: str = ""
    modified: str = ""
    extra: dict = field(default_factory=dict)       # fields the user added


@dataclass
class InterpPiece:
    id: str
    version_id: str
    feature_id: str
    profile_id: str
    kind: str
    vertices: list
    axis: str = "elevation"
    based_on_dataset: str = ""
    based_on_version: str = ""
    created: str = ""
    modified: str = ""


def new_id() -> str:
    return uuid.uuid4().hex


def _dedup(vertices) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for s, z in vertices:
        v = (float(s), float(z))
        if not out or out[-1] != v:
            out.append(v)
    return out


def normalise(piece: InterpPiece) -> InterpPiece:
    """Validated copy: repeated vertices dropped, polygons closed and counter-clockwise."""
    if piece.kind not in KINDS:
        raise ValueError(f"unknown piece kind '{piece.kind}'")
    v = _dedup(piece.vertices)
    if piece.kind == "point":
        if len(v) != 1:
            raise ValueError("a point needs exactly one vertex")
    elif piece.kind == "line":
        if len(v) < 2:
            raise ValueError("a line needs at least two vertices")
    else:
        if len(v) > 1 and v[0] == v[-1]:
            v = v[:-1]
        if len(set(v)) < 3:
            raise ValueError("a polygon needs at least three distinct vertices")
        a = np.asarray(v + [v[0]], float)
        if np.sum(a[:-1, 0] * a[1:, 1] - a[1:, 0] * a[:-1, 1]) < 0:
            v = v[::-1]
        v = v + [v[0]]
    out = InterpPiece(**{**piece.__dict__, "vertices": v})
    return out


def _densified(vertices, chainage) -> list[tuple[float, float]]:
    """Section vertices with every profile vertex chainage they span inserted (z linear)."""
    knots = np.cumsum(np.r_[0.0, np.hypot(*np.diff(np.asarray(chainage.xy, float), axis=0).T)])
    inner = knots[1:-1]
    out = [vertices[0]]
    for (s0, z0), (s1, z1) in zip(vertices[:-1], vertices[1:]):
        lo, hi = min(s0, s1), max(s0, s1)
        between = [k for k in inner if lo < k < hi]
        between.sort(reverse=s1 < s0)
        for k in between:
            out.append((float(k), z0 + (z1 - z0) * (k - s0) / (s1 - s0)))
        out.append((s1, z1))
    return out


def to_3d(piece: InterpPiece, chainage) -> list[tuple[float, float, float]]:
    """Real-world (x, y, z) vertices of ``piece`` (closed ring for polygons)."""
    verts = [(float(s), float(z)) for s, z in piece.vertices]
    if piece.kind != "point":
        verts = _densified(verts, chainage)
    xy = np.atleast_2d(chainage.to_xy(np.array([s for s, _ in verts])))
    return [(float(x), float(y), float(z)) for (x, y), (_, z) in zip(xy, verts)]


def footprint(piece: InterpPiece, chainage) -> list[tuple[float, float]]:
    """Map trace: the profile between the piece's chainage extremes (a point for points)."""
    s = [float(v[0]) for v in piece.vertices]
    if piece.kind == "point":
        x, y = np.atleast_2d(chainage.to_xy(np.array(s[:1])))[0]
        return [(float(x), float(y))]
    lo, hi = min(s), max(s)
    pts = _densified([(lo, 0.0), (hi, 0.0)], chainage)
    xy = np.atleast_2d(chainage.to_xy(np.array([p[0] for p in pts])))
    return [(float(x), float(y)) for x, y in xy]


def label_point(piece: InterpPiece) -> tuple[float, float]:
    v = [(float(s), float(z)) for s, z in piece.vertices]
    if piece.kind == "point":
        return v[0]
    if piece.kind == "line":
        return v[len(v) // 2]
    ring = v[:-1] if len(v) > 1 and v[0] == v[-1] else v
    a = np.asarray(ring, float)
    return float(a[:, 0].mean()), float(a[:, 1].mean())


def type_suggestions(used: list[str]) -> list[str]:
    seen: dict[str, str] = {}
    for t in list(STARTER_TYPES) + [u for u in used if u and u.strip()]:
        seen.setdefault(t.strip().lower(), t.strip())
    return sorted(seen.values(), key=str.lower)
