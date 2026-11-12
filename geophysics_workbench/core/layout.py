"""A profile's in-line layout: which distance in a dataset's file belongs to which station
number, and electrode positions derived when none were imported.

A station's file distance comes from, in this order: the distance stored with it, the
readings file's electrode block (station ``n`` is electrode ``n``), a typed spacing, a
spacing guessed from the model. Derived electrodes come from the readings file, a typed
spacing over the model's extent, or a guess from the model's top edge. Only a row or column
model gives a guess: a triangulated mesh's surface nodes are denser than the electrodes and
reach past the line ends. Nothing guessed here is stored. Pure NumPy and stdlib."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .placement import DistanceMap
from .section_mesh import SectionMesh

#: in-line sources, strongest first
SOURCES = ("distances", "readings", "spacing", "guessed")

KIND_TEXT = {"readings": "electrodes from the readings file",
             "spacing": "electrodes from a spacing of {spacing} m",
             "guessed": "electrodes guessed from the model"}


def _usable(spacing: float | None) -> bool:
    return spacing is not None and bool(np.isfinite(spacing)) and spacing > 0


def inline_distances(numbers, stored, readings_x=None, spacing: float | None = None,
                     guessed_spacing: float | None = None) -> tuple[np.ndarray, str]:
    """Each station's distance in the file: the stored one when finite, else the readings
    file's electrode x (station ``n`` takes ``readings_x[n - 1]``), else ``spacing`` or
    ``guessed_spacing`` counted from the lowest station number. Returns the distances and
    the weakest source used ("distances", "readings", "spacing", "guessed"), or "none" when
    a station has no distance (its value is NaN)."""
    numbers = np.asarray(numbers, dtype=float).ravel()
    out = np.asarray(stored, dtype=float).ravel().copy()
    if out.shape != numbers.shape:
        raise ValueError("Every station needs a stored distance (NaN when unknown).")
    if numbers.size == 0:
        return out, "none"
    used = np.full(numbers.size, -1)
    used[np.isfinite(out)] = 0
    candidates = []
    if readings_x is not None:
        rx = np.asarray(readings_x, dtype=float).ravel()
        k = numbers - 1
        inside = (k == np.round(k)) & (k >= 0) & (k < rx.size)
        values = np.full(numbers.size, np.nan)
        values[inside] = rx[k[inside].astype(int)]
        candidates.append((1, values))
    first = numbers.min()
    for rank, sp in ((2, spacing), (3, guessed_spacing)):
        if _usable(sp):
            candidates.append((rank, (numbers - first) * float(sp)))
    for rank, values in candidates:
        take = (used < 0) & np.isfinite(values)
        out[take] = values[take]
        used[take] = rank
    if (used < 0).any():
        out[used < 0] = np.nan
        return out, "none"
    return out, SOURCES[int(used.max())]


def _quad_grid(mesh: SectionMesh) -> bool:
    """All cells are quads whose edges run along x or z (a row or column model)."""
    c = mesh.cells
    if len(c) == 0 or (c[:, 3] < 0).any():
        return False
    ring = mesh.vertices[c]
    step = np.roll(ring, -1, axis=1) - ring
    tol = 1e-9 * max(1.0, float(np.abs(mesh.vertices).max()))
    return bool(((np.abs(step[..., 0]) <= tol) | (np.abs(step[..., 1]) <= tol)).all())


def _height(z: np.ndarray, z_kind: str) -> np.ndarray:
    """Upward height: z itself, or minus the depth for a depth model (top = smallest |z|)."""
    return -np.abs(z) if z_kind == "depth" else z


def _distinct(x: np.ndarray) -> np.ndarray:
    x = np.sort(np.asarray(x, dtype=float))
    if x.size == 0:
        return x
    tol = 1e-6 * max(1.0, float(np.abs(x).max()))
    return x[np.r_[True, np.diff(x) > tol]]


def _quad_top(mesh: SectionMesh, z_kind: str) -> np.ndarray:
    """x of the vertices on the model's top edge: the edges of the cells seen from above
    (for each stretch of x, the cell whose top is highest)."""
    ring = mesh.vertices[mesh.cells]
    x_lo, x_hi = ring[..., 0].min(1), ring[..., 0].max(1)
    top = _height(ring[..., 1], z_kind).max(1)
    edges = _distinct(np.r_[x_lo, x_hi])
    mids = 0.5 * (edges[:-1] + edges[1:])
    winner = np.full(mids.size, -1)
    for i in np.argsort(-top, kind="stable"):
        part = winner[np.searchsorted(mids, x_lo[i], "right"):
                      np.searchsorted(mids, x_hi[i], "left")]
        part[part < 0] = i
        if (winner >= 0).all():
            break
    won = np.unique(winner[winner >= 0])
    return _distinct(np.r_[x_lo[won], x_hi[won]])


def guess_electrodes(mesh: SectionMesh, z_kind: str) -> np.ndarray:
    """Guessed electrode positions in file distance, ascending: the x of the top-edge vertices
    of a row or column model (all cells axis-parallel quads). The top is the highest z
    ("elevation", "local", "unknown") or the smallest |z| ("depth"). Empty for any other
    mesh: a triangulated mesh's surface nodes include refinement nodes between the electrodes
    and padding beyond the line ends, so they would give a misleading guess."""
    if not _quad_grid(mesh):
        return np.empty(0)
    top = _quad_top(mesh, z_kind)
    return top if top.size >= 2 else np.empty(0)


def guessed_spacing(mesh: SectionMesh, z_kind: str) -> float | None:
    """The median gap of ``guess_electrodes``, or None without a guess (always None for a
    triangulated mesh, see ``guess_electrodes``)."""
    g = guess_electrodes(mesh, z_kind)
    return float(np.median(np.diff(g))) if g.size >= 2 else None


@dataclass(eq=False)
class Electrodes:
    numbers: np.ndarray     # 1..n in ascending file distance
    chainage: np.ndarray
    kind: str               # "imported", "readings", "spacing" or "guessed"


def _positions(values) -> np.ndarray:
    x = np.asarray(values, dtype=float).ravel()
    return np.sort(x[np.isfinite(x)])


def derived_electrodes(dmap: DistanceMap, extent: tuple[float, float], readings_x=None,
                       spacing: float | None = None, guess=None) -> Electrodes | None:
    """Electrodes to show when none were imported, from the readings file's electrode x
    (remote poles, None or NaN, left out), else ``spacing`` laid over the file-distance
    ``extent`` from its start, else the ``guess``; None when there is nothing to go on."""
    x, kind = np.empty(0), ""
    if readings_x is not None:
        x, kind = _positions(readings_x), "readings"
    if x.size == 0 and _usable(spacing):
        lo, hi = sorted(float(v) for v in extent)
        n = int(np.floor((hi - lo) / spacing + 1e-9)) + 1
        x, kind = lo + float(spacing) * np.arange(n), "spacing"
    if x.size == 0 and guess is not None:
        x, kind = _positions(guess), "guessed"
    if x.size == 0:
        return None
    return Electrodes(np.arange(1, x.size + 1), np.asarray(dmap(x), dtype=float), kind)
