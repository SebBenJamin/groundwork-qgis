"""Calhoun CZO refraction lines for the demo: read the authors' files, place each line on
the map, and write Refrapick pick files (numpy only, no QGIS).

Source (CC BY 4.0): HydroShare resource 340773feb3b341d884f6742b55966609, "Supporting Data
Repository: Landscape Curvature and Deep Critical Zone Structure" (Flinchum et al.).

- Picks (``<picks>.txt``): shot position, geophone position (nominal metres along the line),
  first-arrival time in seconds; one pick per row.
- Elevation (``<elev>.txt``): horizontal metres along the line (the authors'
  "topographically adjusted" x), elevation, nominal metres (what the picks use).
- ``allBR.txt``: points every 10 m along the lines in UTM 17N, with the authors' depth to
  bedrock, as unnamed pieces (the distance in column 6 starts again for each line). Column 7
  (mean bedrock elevation) + column 3 (depth to bedrock) is the ground surface; matching it
  with a line's elevation file names the piece and gives the line's offset along it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

#: the demo's lines: piece in allBR.txt, the line's picks and elevation files (as the
#: authors' own StreamLineInversion scripts load them)
LINES = {
    "L10": (0, "SCP_L10_ttxConverted.txt", "SCP_L10_LiDAR.txt"),
    "L11": (1, "SCP_L11_BAF.txt", "SCP_L11_lidarElev.txt"),
    "L12": (2, "SCP_L12_verticalShots_BFPicks.txt", "SCP_L12_lidarElev.txt"),
    "L6": (11, "SCP_L6_ttxConverted.txt", "SCP_L6_LiDAR.txt"),
}
#: name -> (expected piece, None); the offsets come from the match
EXPECTED = {name: (piece, None) for name, (piece, _p, _e) in LINES.items()}
MAX_RMS = 1.5           # m: the surface of a matched piece against the line's elevation file
MIN_INSIDE = 0.8        # of a piece's points must lie on the line for a match to count


@dataclass
class LineData:
    picks: np.ndarray       # (n, 3) shot, geophone (nominal m), t (s)
    x_h: np.ndarray         # horizontal metres along the line, per elevation row
    z: np.ndarray           # elevation per row
    x_nom: np.ndarray       # nominal metres per row (the picks' positions)

    def to_h(self, nominal) -> np.ndarray:
        return np.interp(nominal, self.x_nom, self.x_h)

    def z_at(self, nominal) -> np.ndarray:
        return np.interp(nominal, self.x_nom, self.z)


def line_files(folder: Path, name: str) -> tuple[Path, Path]:
    _piece, picks, elev = LINES[name]
    return Path(folder) / name / picks, Path(folder) / name / elev


def read_pieces(path) -> list[np.ndarray]:
    """``allBR.txt`` split into its lines: a new piece wherever the distance (column 6)
    does not increase."""
    a = np.loadtxt(path, ndmin=2)
    d = a[:, 5]
    starts = [0] + [i for i in range(1, len(d)) if d[i] <= d[i - 1]] + [len(d)]
    return [a[s:e] for s, e in zip(starts[:-1], starts[1:])]


def read_line(picks_path, elev_path) -> LineData:
    """Picks without zero offset or non-positive times, and the elevation file."""
    p = np.loadtxt(picks_path, ndmin=2)[:, :3]
    p = p[(p[:, 2] > 0) & (np.abs(p[:, 0] - p[:, 1]) > 1e-6)]
    e = np.loadtxt(elev_path, ndmin=2)
    return LineData(p, e[:, 0], e[:, 1], e[:, 2])


def match_piece(line: LineData, pieces: list[np.ndarray]) -> tuple[int, float, float]:
    """``(piece index, offset m, rms m)`` of the piece whose surface fits the line's
    elevations best: piece distance + offset = horizontal metres along the line."""
    best = (np.inf, -1, 0.0)
    for k, p in enumerate(pieces):
        surface, d = p[:, 6] + p[:, 2], p[:, 5]
        for off in np.arange(-50.0, line.x_h.max() + 1.0, 1.0):
            q = d + off
            inside = (q >= line.x_h.min()) & (q <= line.x_h.max())
            if inside.sum() < MIN_INSIDE * len(q):
                continue
            rms = float(np.sqrt(np.mean((np.interp(q[inside], line.x_h, line.z)
                                         - surface[inside]) ** 2)))
            if rms < best[0]:
                best = (rms, k, float(off))
    if best[1] < 0:
        raise ValueError("no piece lies along the line")
    return best[1], best[2], best[0]


def _along(piece: np.ndarray, s) -> np.ndarray:
    """Map (E, N) at piece distances ``s``, extended straight beyond the piece's ends."""
    d, e, n = piece[:, 5], piece[:, 0], piece[:, 1]
    s = np.asarray(s, dtype=float)
    out = np.column_stack([np.interp(s, d, e), np.interp(s, d, n)])
    for end, (i, j) in (("lo", (0, 1)), ("hi", (-2, -1))):
        mask = s < d[0] if end == "lo" else s > d[-1]
        if mask.any():
            de, dn = (e[j] - e[i]) / (d[j] - d[i]), (n[j] - n[i]) / (d[j] - d[i])
            ref = 0 if end == "lo" else -1
            out[mask] = np.column_stack([e[ref] + de * (s[mask] - d[ref]),
                                         n[ref] + dn * (s[mask] - d[ref])])
    return out


def stations_xy(line: LineData, piece: np.ndarray, offset: float
                ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """The geophones as stations: ``(xyz, numbers 1..n, inline)``, ordered along the line;
    ``inline`` is each geophone's horizontal metres (the model file's x)."""
    nominal = np.unique(line.picks[:, 1])
    x_h = line.to_h(nominal)
    order = np.argsort(x_h, kind="stable")
    nominal, x_h = nominal[order], x_h[order]
    xy = _along(piece, x_h - offset)
    xyz = np.column_stack([xy, line.z_at(nominal)])
    return xyz, np.arange(1, len(x_h) + 1), x_h


def sensor_points(line: LineData) -> tuple[np.ndarray, np.ndarray, dict]:
    """The shot and geophone points as sensors: ``(x_h, z, nominal -> 1-based index)``.
    Points that land on the same horizontal centimetre are one sensor: a shot beyond the
    elevation file's end lands on its last point, as the authors' script snaps it."""
    nominal = np.unique(np.r_[line.picks[:, 0], line.picks[:, 1]])
    keys = np.round(line.to_h(nominal), 2)
    xs, first = np.unique(keys, return_index=True)
    index = {float(n): int(np.searchsorted(xs, k)) + 1 for n, k in zip(nominal, keys)}
    return xs, line.z_at(nominal[first]), index


def write_sgt(path, line: LineData) -> int:
    """Refrapick's pick file: every shot and geophone point (horizontal x, elevation), then
    ``s g t`` with 1-based indices; a pick whose shot and geophone are one sensor, or that
    repeats a pair, is left out. Returns the number of picks written."""
    xs, zs, index = sensor_points(line)
    rows, seen = [], set()
    for s, g, t in line.picks:
        pair = (index[float(s)], index[float(g)])
        if pair[0] == pair[1] or pair in seen:
            continue
        seen.add(pair)
        rows.append(f"{pair[0]} {pair[1]} {t:.6f}\n")
    with open(path, "w", newline="\n") as f:
        f.write(f"{len(xs)} # shot/geophone points\n#x y\n")
        for x, z in zip(xs, zs):
            f.write(f"{x:.2f} {z:.2f}\n")
        f.write(f"{len(rows)} # measurements\n#s g t\n")
        f.writelines(rows)
    return len(rows)


def thinned(line: LineData, step: int) -> LineData:
    """Only the picks at geophones on multiples of ``step`` nominal metres (every shot kept):
    a lighter inversion of a long line with 1 m geophone spacing."""
    keep = np.isclose(np.mod(line.picks[:, 1], step), 0.0) | \
        np.isclose(np.mod(line.picks[:, 1], step), step)
    return LineData(line.picks[keep], line.x_h, line.z, line.x_nom)
