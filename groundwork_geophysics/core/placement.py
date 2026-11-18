"""Where a dataset sits along its profile: the map from a file's own in-line metres to
chainage, and how well the known (surveyed) points fit a straight one-metre-per-metre run.

A ``DistanceMap`` is pinned at known points: file distance ``d[i]`` lands on chainage ``s[i]``.
Between two pins the file's metres are stretched evenly; outside the pins they run one metre
per metre in ``direction`` (1 along the line, -1 against it). A map with a single pin is the
rigid map. Pure NumPy and stdlib (does not import ``core.model``)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(eq=False)
class Positions:
    """Station positions read with a dataset: map coordinates and height, and optionally the
    station numbers, each station's distance in the file's in-line metres and its point
    name ("" where it has none)."""
    xyz: np.ndarray
    numbers: np.ndarray | None = None
    inline: np.ndarray | None = None
    names: list[str] | None = None


@dataclass(eq=False)
class Placement:
    """How a dataset is put on a profile: an existing profile, a new line, or positions read
    with it; where the file's zero lies (``zero`` is "start", "end" or "station1") with an
    ``offset``, and an optional station ``spacing``."""
    profile_id: str | None = None
    line_xy: np.ndarray | None = None
    positions: Positions | None = None
    zero: str = "start"
    offset: float = 0.0
    spacing: float | None = None
    replace_line: bool = False


@dataclass(frozen=True, eq=False)
class DistanceMap:
    d: np.ndarray           # file distances of the pins, ascending
    s: np.ndarray           # their chainages
    direction: int          # 1: file distance grows along the line; -1: against it

    def __call__(self, x) -> np.ndarray:
        x = np.asarray(x, dtype=float)
        d, s, k = self.d, self.s, self.direction
        return np.where(x < d[0], s[0] + k * (x - d[0]),
                        np.where(x > d[-1], s[-1] + k * (x - d[-1]), np.interp(x, d, s)))

    @property
    def pinned(self) -> bool:
        return len(self.d) >= 2


def rigid_map(zero: float, direction: int = 1) -> DistanceMap:
    """File distance 0 at chainage ``zero``, one metre per metre in ``direction``."""
    return DistanceMap(np.array([0.0]), np.array([float(zero)]), direction)


def _sorted_pins(d, s, labels):
    """The pins sorted by file distance, with their labels (1-based input positions when
    ``labels`` is None)."""
    d = np.asarray(d, dtype=float)
    s = np.asarray(s, dtype=float)
    if labels is None:
        labels = [str(i + 1) for i in range(len(d))]
    if not (len(d) == len(s) == len(labels)):
        raise ValueError("Every known point needs a distance in the file and a chainage.")
    order = np.argsort(d, kind="stable")
    return d[order], s[order], [labels[i] for i in order]


def _direction(s: np.ndarray) -> int:
    return 1 if s[-1] > s[0] else -1


def pinned_map(d, s, labels: list[str] | None = None) -> DistanceMap:
    """The map pinned at file distances ``d`` onto chainages ``s``. Raises ValueError naming
    the point when two points share a file distance or a chainage is out of order."""
    d, s, labels = _sorted_pins(d, s, labels)
    if len(d) < 2:
        raise ValueError("At least two known points are needed to pin a dataset.")
    for i in range(1, len(d)):
        if d[i] == d[i - 1]:
            raise ValueError(f"Known points {labels[i - 1]} and {labels[i]} are at the same "
                             f"distance in the file.")
    direction = _direction(s)
    for i in range(1, len(d)):
        if direction * (s[i] - s[i - 1]) <= 0:
            raise ValueError(f"Known point {labels[i]} is out of order along the line.")
    return DistanceMap(d, s, direction)


@dataclass(frozen=True)
class FitReport:
    n: int                  # number of known points
    max_shift: float        # signed shift of the point that moves most, in metres
    at: str                 # that point's label
    warn: bool              # the shift is above half the median gap between known points

    def text(self, word: str = "station", guessed: bool = False) -> str:
        from .numbers import fmt_trim
        out = (f"{self.n} known points, largest shift {fmt_trim(abs(self.max_shift))} m "
               f"at {word} {self.at}")
        return out + " (pinned with a guessed spacing)" if guessed else out


def fit_report(d, s, labels: list[str]) -> FitReport:
    """How far each known point moves from where a rigid map through the first one would put
    it (shift = s[i] − (s[0] + direction·(d[i] − d[0]))), reporting the largest."""
    d, s, labels = _sorted_pins(d, s, labels)
    n = len(d)
    if n < 2:
        return FitReport(n, 0.0, "", False)
    shift = s - (s[0] + _direction(s) * (d - d[0]))
    i = int(np.argmax(np.abs(shift)))
    max_shift = float(shift[i])
    warn = bool(abs(max_shift) > 0.5 * np.median(np.abs(np.diff(s))))
    return FitReport(n, max_shift, labels[i], warn)
