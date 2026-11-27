"""Trace sections: a picture of traces x samples (a seismic reflection section read from SEG-Y),
the second kind of data beside the cell model (no QGIS/Qt; NumPy and the standard library only).

The amplitudes are never changed: placing a section and moving it along the profile share the
sample array, and the display helpers (gain, colour limits, the reduced picture) work on copies.
Sections can be large (tens of thousands of traces by thousands of samples), so no function here
makes a float64 copy of the whole array: statistics use a regular subsample, and the work on
every sample runs over blocks of traces."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace

import numpy as np

DOMAINS = ("time", "depth")
#: at most this many samples are looked at for the sign and the clip of a section
SAMPLE_LIMIT = 200_000
#: about this many values are worked on at once in float64 (agc, trace balance, the picture)
_BLOCK = 1 << 20

NO_VELOCITY = "The velocity must be greater than 0 m/s."
TURNS_BACK = "The velocity function gives depths that do not increase with time."
TIMES_DO_NOT_INCREASE = "The times of the velocity function must increase."
#: what to do when Dix's formula finds no real interval velocity in an RMS table
RMS_ADVICE = ("Set \"Velocities are\" to Average or Interval if the table holds those, or "
              "correct the table.")
#: how the rows of a velocity function are read (an unknown kind reads as "average")
KINDS = ("average", "interval", "rms")
#: the speed of light in m/ns: radar velocities are often given in m/ns (code works in m/s)
C_M_PER_NS = 0.299792458
_C = C_M_PER_NS * 1e9                 # m/s
BAD_DIELECTRIC = "The dielectric constant must be 1 or greater."
BAD_RADAR_VELOCITY = ("The velocity must be greater than 0 and not above the speed of light "
                      "(0.2998 m/ns).")
BEYOND_RECORD = "Time zero lies beyond the end of the record."
NOT_A_TIME_ZERO = "Time zero must be a number."
NO_DEPTH_TIME_ZERO = "A depth section has no time zero."
#: how the background is removed: "" off, "all" the mean trace of the line, "window" a moving mean
BACKGROUNDS = ("", "all", "window")


def _sample(a) -> np.ndarray:
    """At most ``SAMPLE_LIMIT`` values of ``a`` (1-D), taken with a regular stride; a view when
    ``a`` is contiguous, a small copy otherwise."""
    a = np.asarray(a)
    if a.size <= SAMPLE_LIMIT:
        return a.reshape(-1)
    if a.flags.c_contiguous:
        return a.reshape(-1)[::math.ceil(a.size / SAMPLE_LIMIT)]
    if a.ndim == 2:
        a = a[::max(1, math.ceil(a.size / SAMPLE_LIMIT))]
        if a.size > SAMPLE_LIMIT:
            a = a[:, ::math.ceil(a.size / SAMPLE_LIMIT)]
    flat = a.reshape(-1)
    return flat[::max(1, math.ceil(flat.size / SAMPLE_LIMIT))]


def _signed(a) -> bool:
    return bool((_sample(a) < 0).any())


def _clip(a, percent: float) -> float:
    v = np.abs(_sample(a).astype(np.float64))
    v = v[np.isfinite(v)]
    if not v.size:
        return 0.0
    return float(np.percentile(v, min(max(float(percent), 0.0), 100.0)))


def _edges(c: np.ndarray, single: float = 0.5) -> np.ndarray:
    """Cell edges of increasing centres ``c``: half way to each neighbour, the end cells as
    wide on the outside as on the inside; one centre gets ``single`` on each side."""
    c = np.asarray(c, dtype=np.float64)
    if c.size == 1:
        return np.array([c[0] - single, c[0] + single])
    e = np.empty(c.size + 1)
    e[1:-1] = 0.5 * (c[:-1] + c[1:])
    e[0] = c[0] - 0.5 * (c[1] - c[0])
    e[-1] = c[-1] + 0.5 * (c[-1] - c[-2])
    return e


def _find(edges: np.ndarray, v) -> np.ndarray:
    """Index of the cell holding each ``v`` (``-1`` or ``len(edges) - 1`` outside); the last
    edge belongs to the last cell."""
    i = np.searchsorted(edges, v, side="right") - 1
    return np.where(np.asarray(v) == edges[-1], edges.size - 2, i)


def _row_blocks(n_rows: int, row_len: int):
    """``(start, stop)`` of blocks of rows holding about ``_BLOCK`` values each."""
    step = max(1, _BLOCK // max(1, row_len))
    for r0 in range(0, n_rows, step):
        yield r0, min(n_rows, r0 + step)


def _strongest(values: np.ndarray, starts: np.ndarray, axis: int) -> np.ndarray:
    """Per run of ``values`` along ``axis`` (runs begin at ``starts``): the value with the
    largest absolute value, keeping its sign; NaN only where a run has no number at all."""
    with np.errstate(invalid="ignore"):
        hi = np.fmax.reduceat(values, starts, axis=axis)
        lo = np.fmin.reduceat(values, starts, axis=axis)
        return np.where(hi >= -lo, hi, lo)


@dataclass(eq=False)
class TraceSection:
    """Traces x samples as the file holds them. ``x`` is the file's distance along the line in
    m (or, once placed, the chainage); samples start at ``first`` and are ``step`` apart, in
    seconds (two-way time) for a ``"time"`` section, in metres for a ``"depth"`` one."""
    amplitudes: np.ndarray            # (n_traces, n_samples); float32 or the file's integer type
    x: np.ndarray                     # (n_traces,) float64
    first: float
    step: float
    domain: str                       # "time" | "depth"
    numbers: np.ndarray | None = None  # (n_traces,) CDP or trace numbers for the readout
    quantity: str = "amplitude"
    unit: str = ""
    readings = None                   # not a field: code written for meshes can ask

    def __post_init__(self):
        self.amplitudes = np.asarray(self.amplitudes)
        if self.amplitudes.ndim != 2 or 0 in self.amplitudes.shape:
            raise ValueError("A trace section needs at least one trace with at least one sample.")
        self.x = np.asarray(self.x, dtype=np.float64).reshape(-1)
        if self.x.size != self.amplitudes.shape[0]:
            raise ValueError(f"{self.amplitudes.shape[0]} traces but {self.x.size} positions.")
        if not np.isfinite(self.x).all():
            raise ValueError("Every trace needs a position.")
        self.first, self.step = float(self.first), float(self.step)
        if not (math.isfinite(self.first) and math.isfinite(self.step) and self.step > 0):
            raise ValueError("The sample step must be greater than 0.")
        if self.domain not in DOMAINS:
            raise ValueError(f"domain must be one of {DOMAINS}, got {self.domain!r}")
        if self.numbers is not None:
            self.numbers = np.asarray(self.numbers).reshape(-1)
            if self.numbers.size != self.x.size:
                raise ValueError(f"{self.x.size} traces but {self.numbers.size} trace numbers.")

    @property
    def n_traces(self) -> int:
        return self.amplitudes.shape[0]

    @property
    def n_samples(self) -> int:
        return self.amplitudes.shape[1]

    def sample_axis(self) -> np.ndarray:
        """Time (s) or depth (m) of each sample as the file gives it."""
        return self.first + np.arange(self.n_samples) * self.step

    def with_x(self, fn) -> "TraceSection":
        """The same section with ``x`` replaced by ``fn(x)``; the amplitudes are shared."""
        return replace(self, x=np.asarray(fn(self.x), dtype=np.float64))

    def bounds_x(self) -> tuple[float, float]:
        return float(self.x.min()), float(self.x.max())

    def signed(self) -> bool:
        """True when any sample is negative (looked for in at most ``SAMPLE_LIMIT`` samples)."""
        return _signed(self.amplitudes)

    def clip(self, percent: float = 98.0) -> float:
        """The ``percent`` percentile of the absolute amplitudes (finite samples of a regular
        subsample); 0.0 when there is none."""
        return _clip(self.amplitudes, percent)


@dataclass(frozen=True)
class Velocity:
    """One velocity in m/s (``value``), or a velocity function: rows of (two-way time s,
    velocity m/s) with increasing times, read as average, interval or RMS velocities (stacking
    velocities are close to RMS ones)."""
    value: float | None = None
    table: tuple = ()
    kind: str = "average"             # one of ``KINDS``; only read with ``table``

    @classmethod
    def from_options(cls, options: dict) -> "Velocity":
        """From read options: ``velocity`` (float), ``velocity_table`` ([[t, v], ...]) and
        ``velocity_kind``. Unreadable entries count as missing."""
        options = options or {}
        value = options.get("velocity")
        try:
            value = None if value is None else float(value)
        except (TypeError, ValueError):
            value = None
        try:
            table = tuple((float(t), float(v)) for t, v in (options.get("velocity_table") or ()))
        except (TypeError, ValueError):
            table = ()
        kind = options.get("velocity_kind") or "average"
        return cls(value, table, kind if kind in KINDS else "average")

    def text(self) -> str:
        if self.table:
            vs = [v for _, v in self.table]
            return f"a velocity function ({_number(min(vs))}–{_number(max(vs))} m/s)"
        if self.value is None:
            return "no velocity"
        return f"v = {_number(self.value)} m/s"


def _number(v: float) -> str:
    v = round(float(v), 1)
    return f"{v:.0f}" if v == int(v) else f"{v:.1f}"


def _usable(v) -> bool:
    return v is not None and math.isfinite(v) and v > 0


def velocity_from_dielectric(eps: float) -> float:
    """Radar velocity (m/s) in a material of relative dielectric constant ``eps``:
    ``c / sqrt(eps)``. ValueError for ``eps`` below 1 or not a number."""
    eps = float(eps)
    if not (math.isfinite(eps) and eps >= 1.0):
        raise ValueError(BAD_DIELECTRIC)
    return _C / math.sqrt(eps)


def dielectric_from_velocity(v: float) -> float:
    """Relative dielectric constant for a radar velocity ``v`` (m/s): ``(c / v) ** 2``.
    ValueError for ``v`` not above 0 or above the speed of light."""
    v = float(v)
    if not (math.isfinite(v) and 0.0 < v <= _C):
        raise ValueError(BAD_RADAR_VELOCITY)
    return (_C / v) ** 2


def _time_zero(section: TraceSection, time_zero) -> float:
    """``time_zero`` as a float, checked: 0 for a depth section, not after the last sample."""
    tz = float(time_zero)
    if not math.isfinite(tz):
        raise ValueError(NOT_A_TIME_ZERO)
    if section.domain == "depth":
        if tz != 0.0:
            raise ValueError(NO_DEPTH_TIME_ZERO)
        return 0.0
    if tz > section.first + (section.n_samples - 1) * section.step + 1e-6 * section.step:
        raise ValueError(BEYOND_RECORD)
    return tz


def sample_depths(section: TraceSection, velocity: Velocity | None,
                  time_zero: float = 0.0) -> np.ndarray:
    """Depth below time zero / depth zero of each sample, m.

    ``time_zero`` (s, a time section only) is the time that lies on the top (the ground for a
    radargram): every depth is that of ``t - time_zero``, so samples before it get negative
    depths (they lie above the top). ValueError for a non-zero ``time_zero`` on a depth
    section and for one after the last sample.

    A depth section: ``first + k * step`` (``velocity`` is ignored). A time section with one
    velocity: ``v * t / 2``. With an average velocity function: ``v(t) * t / 2``, ``v`` linear
    between rows and constant outside. With an interval velocity function each row's velocity
    holds from its time to the next row's (the first row's also above it, the last row's below
    it) and depth is the running sum. RMS velocities are turned into interval velocities by
    Dix's formula (the first row's velocity down to its time, the last interval's below the
    last row) and summed the same way. ValueError without a usable velocity, for a table whose
    times do not increase, for an average function whose depths do not increase, and for RMS
    velocities that give no real interval velocity."""
    tz = _time_zero(section, time_zero)
    axis = section.sample_axis()
    if section.domain == "depth":
        return axis
    return _time_depths(axis - tz, velocity)


def _time_depths(axis: np.ndarray, velocity: Velocity | None) -> np.ndarray:
    """Depths (m) of the two-way times ``axis`` (s, increasing) as ``sample_depths`` gives
    them."""
    if velocity is None:
        raise ValueError(NO_VELOCITY)
    if not velocity.table:
        if not _usable(velocity.value):
            raise ValueError(NO_VELOCITY)
        return velocity.value * axis / 2.0
    table = np.asarray(velocity.table, dtype=np.float64).reshape(-1, 2)
    tt, vv = table[:, 0], table[:, 1]
    if not (np.isfinite(vv).all() and (vv > 0).all()):
        raise ValueError(NO_VELOCITY)
    if not np.isfinite(tt).all() or (np.diff(tt) <= 0).any():
        raise ValueError(TIMES_DO_NOT_INCREASE)
    if velocity.kind == "interval":
        at_rows = np.empty(tt.size)
        at_rows[0] = tt[0] * vv[0] / 2.0
        at_rows[1:] = at_rows[0] + np.cumsum(np.diff(tt) * vv[:-1] / 2.0)
        j = np.clip(np.searchsorted(tt, axis, side="right") - 1, 0, tt.size - 1)
        return at_rows[j] + (axis - tt[j]) * vv[j] / 2.0
    if velocity.kind == "rms":
        # Dix: the interval velocity between two rows; the first row's velocity from time
        # zero to its time (and above it), the last interval's below the last row
        radicand = np.diff(vv * vv * tt) / np.diff(tt)
        bad = np.flatnonzero(~(radicand > 0))
        if bad.size:
            i = int(bad[0])
            raise ValueError(f"The RMS velocities give no real interval velocity between "
                             f"{tt[i] * 1000:.0f} ms and {tt[i + 1] * 1000:.0f} ms. "
                             + RMS_ADVICE)
        between = np.sqrt(radicand)                 # from row i down to row i + 1
        below = np.append(between, between[-1] if between.size else vv[0])
        at_rows = np.empty(tt.size)
        at_rows[0] = tt[0] * vv[0] / 2.0
        at_rows[1:] = at_rows[0] + np.cumsum(np.diff(tt) * between / 2.0)
        j = np.clip(np.searchsorted(tt, axis, side="right") - 1, 0, tt.size - 1)
        out = at_rows[j] + (axis - tt[j]) * below[j] / 2.0
        return np.where(axis < tt[0], axis * vv[0] / 2.0, out)
    depths = np.interp(axis, tt, vv) * axis / 2.0
    if (np.diff(depths) <= 0).any():
        raise ValueError(TURNS_BACK)
    return depths


def smoothed_ground(x, z, length: float) -> np.ndarray:
    """The ground ``z`` at the traces ``x`` (chainage, m; in either order) as a centred moving
    average over ``length`` metres of chainage: each trace takes the mean of the traces within
    half of it on either side, the window shrinking near the ends so that it stays centred
    (the first and last trace keep their own height). ``length`` 0 (or not a positive number)
    gives ``z`` unchanged. Used for hanging a section, never for the drawn ground."""
    z = np.asarray(z, dtype=np.float64)
    try:
        length = float(length)
    except (TypeError, ValueError):
        return z
    x = np.asarray(x, dtype=np.float64)
    if not (math.isfinite(length) and length > 0) or z.size < 3:
        return z
    order = np.argsort(x, kind="stable")
    xs, zs = x[order], z[order]
    half = np.minimum(length / 2.0, np.minimum(xs - xs[0], xs[-1] - xs))
    tol = 1e-9 * max(1.0, float(np.abs(xs).max()))     # a trace exactly at the edge counts
    lo = np.searchsorted(xs, xs - half - tol, side="left")
    hi = np.searchsorted(xs, xs + half + tol, side="right")
    sums = np.concatenate([[0.0], np.cumsum(zs)])
    out = np.empty_like(z)
    out[order] = (sums[hi] - sums[lo]) / (hi - lo)
    return out


def ground_time(datum: float, ground: np.ndarray, replacement_velocity: float) -> np.ndarray:
    """Two-way time (s) from the datum down to the ground at each trace with the replacement
    velocity (m/s): ``2 * (datum - ground) / replacement_velocity``, negative where the ground
    lies above the datum."""
    ground = np.asarray(ground, dtype=np.float64)
    return 2.0 * (float(datum) - ground) / float(replacement_velocity)


def depth_at(section: TraceSection, velocity: Velocity | None, times: np.ndarray,
             time_zero: float = 0.0) -> np.ndarray:
    """Depth below time zero (m) at ``times`` (s, as the file counts them), as
    ``sample_depths`` gives it for the samples (with the same ``time_zero``): interpolated
    between them, and beyond the first and last sample continued in a straight line with the
    slope at that end. With one velocity that is ``v * (t - time_zero) / 2`` for any time.
    ValueError for a depth section (it has no times) and as ``sample_depths``."""
    if section.domain != "time":
        raise ValueError("A depth section has no times to give depths for.")
    depths = sample_depths(section, velocity, time_zero)
    tz = float(time_zero)
    times = np.asarray(times, dtype=np.float64) - tz
    if not velocity.table:
        return velocity.value * times / 2.0
    axis = section.sample_axis() - tz
    if axis.size == 1:                       # one sample: the slope from the function itself
        ends = sample_depths(replace(section, amplitudes=np.zeros((1, 2), np.float32),
                                     x=np.zeros(1), numbers=None), velocity, tz)
        lo_slope = hi_slope = (ends[1] - ends[0]) / section.step
    else:
        lo_slope = (depths[1] - depths[0]) / (axis[1] - axis[0])
        hi_slope = (depths[-1] - depths[-2]) / (axis[-1] - axis[-2])
    out = np.interp(times, axis, depths)
    out = np.where(times < axis[0], depths[0] + (times - axis[0]) * lo_slope, out)
    return np.where(times > axis[-1], depths[-1] + (times - axis[-1]) * hi_slope, out)


@dataclass(eq=False)
class PlacedTraces:
    """A section hung in the profile: ``section.x`` is the chainage (increasing), ``z_top`` the
    elevation of time zero / depth zero of each trace, ``depths`` the depth of each sample
    below it (m, increasing; negative for samples before a time zero, which lie above the
    top). ``live_from``, when set, is per trace the first sample that belongs to the earth
    (one corrected to the ground, or the samples before a time zero: those above the ground
    line are not drawn; see ``muted_mask``). ``time_zero`` (s) is the time hung on ``z_top``;
    ``data_start`` the number of leading samples of every trace that are not data (GSSI's
    scan counter and marks): kept as stored, left out of the statistics and never drawn."""
    section: TraceSection
    z_top: np.ndarray
    depths: np.ndarray
    live_from: np.ndarray | None = None
    time_zero: float = 0.0
    data_start: int = 0

    def bounds(self) -> tuple[float, float, float, float]:
        """``(smin, smax, zmin, zmax)``: first to last trace, top of the highest trace to the
        last sample of the lowest (samples above the top, before a time zero, are not
        counted)."""
        x = self.section.x
        return (float(x[0]), float(x[-1]), float(self.z_top.min() - self.depths[-1]),
                float(self.z_top.max()))

    def hit(self, s: float, z: float) -> dict | None:
        """The sample under the profile point ``(s, z)``: the nearest trace when ``s`` lies
        within half a trace spacing of it, the nearest sample when ``z`` lies below the
        trace's top and within half a sample spacing of it; None outside the picture and for
        a sample before the time zero. The amplitude is the file's own number (no gain, no
        polarity swap); ``time`` is the sample's time as the file counts it."""
        sec = self.section
        i = int(_find(_edges(sec.x), s))
        if not 0 <= i < sec.n_traces:
            return None
        d = float(self.z_top[i]) - z
        if d < 0:
            return None
        k = int(_find(_edges(self.depths), d))
        if not 0 <= k < sec.n_samples or k < _zero_sample(sec, self.time_zero):
            return None
        number = None if sec.numbers is None else int(sec.numbers[i])
        time = float(sec.first + k * sec.step) if sec.domain == "time" else None
        return {"trace": i, "number": number, "sample": k, "amplitude": float(sec.amplitudes[i, k]),
                "time": time, "depth": float(self.depths[k])}


def _zero_sample(section: TraceSection, time_zero: float) -> int:
    """The first sample at or after ``time_zero`` (a hair of tolerance for rounding: a sample
    exactly at time zero is earth); 0 for a depth section."""
    if section.domain != "time":
        return 0
    return min(section.n_samples,
               max(0, math.ceil((float(time_zero) - section.first) / section.step - 1e-6)))


def _order(x: np.ndarray):
    """How to put traces at ``x`` in increasing order: None when they are, a reversed slice
    when every step goes back, else a stable sort."""
    step = np.diff(x)
    if not (step < 0).any():
        return None
    return slice(None, None, -1) if (step < 0).all() else np.argsort(x, kind="stable")


def in_order(section: TraceSection) -> TraceSection:
    """``section`` with its traces in increasing ``x`` (stable sort): itself when they are;
    a reversed view when it runs backwards; any other order a copy in the file's type. Done
    once where a placed section is kept, so that ``place`` shares its samples."""
    order = _order(section.x)
    if order is None:
        return section
    numbers = None if section.numbers is None else section.numbers[order]
    return replace(section, amplitudes=section.amplitudes[order], x=section.x[order],
                   numbers=numbers)


def place(section: TraceSection, z_top, velocity: Velocity | None,
          live_from: np.ndarray | None = None, *, time_zero: float = 0.0,
          data_start: int = 0) -> PlacedTraces:
    """Hang ``section`` from ``z_top`` (one elevation or one per trace), with sample depths
    from ``velocity``. Traces whose ``x`` does not increase are put in order as ``in_order``
    does (a copy unless the section runs backwards: give ``place`` a section put in order
    once where it is kept). In order already, the sample array is shared. ``live_from`` (one
    sample index per trace, or None) follows the traces' order.

    ``time_zero`` (s, a time section only) puts the sample at that time on ``z_top`` (see
    ``sample_depths``) and mutes the samples before it: ``live_from`` becomes, for every
    trace, the larger of the given index and the first sample at or after time zero (still
    None when none is given and no sample lies before time zero).

    ``data_start``: the leading samples of every trace that are not data (``PlacedTraces``);
    ``live_from`` is at least that, so they are never drawn."""
    depths = sample_depths(section, velocity, time_zero)
    data_start = min(section.n_samples, max(0, int(data_start)))
    n = section.n_traces
    zt = np.asarray(z_top, dtype=np.float64)
    zt = np.full(n, float(zt)) if zt.ndim == 0 else zt.reshape(-1)
    if zt.size != n:
        raise ValueError(f"{n} traces but {zt.size} top elevations.")
    if not np.isfinite(zt).all():
        raise ValueError("Every trace needs a top elevation.")
    if live_from is not None:
        live_from = np.asarray(live_from, dtype=np.int64).reshape(-1)
        if live_from.size != n:
            raise ValueError(f"{n} traces but {live_from.size} first samples.")
    zero = max(_zero_sample(section, time_zero), data_start)
    if zero > 0:
        live_from = (np.full(n, zero, np.int64) if live_from is None
                     else np.maximum(live_from, zero))
    order = _order(section.x)
    if order is not None:
        section = in_order(section)
        zt = zt[order]
        live_from = None if live_from is None else live_from[order]
    return PlacedTraces(section, np.ascontiguousarray(zt), depths,
                        None if live_from is None else np.ascontiguousarray(live_from),
                        float(time_zero) if section.domain == "time" else 0.0, data_start)


def shown_down_to(placed: PlacedTraces, max_depth) -> PlacedTraces:
    """``placed`` shown only down to ``max_depth`` metres below its top (the samples whose
    depth is at most that, a view of the same samples: nothing is copied or cut from the
    data). ``placed`` itself when ``max_depth`` is off (None, not a number, 0 or less) or
    reaches the last sample. The first sample at or after time zero always stays."""
    try:
        limit = float(max_depth)
    except (TypeError, ValueError):
        return placed
    if not (math.isfinite(limit) and limit > 0):
        return placed
    depths = placed.depths
    tol = 1e-9 * max(1.0, abs(limit))
    k = int(np.searchsorted(depths, limit + tol, side="right"))
    sec = placed.section
    zero = max(_zero_sample(sec, placed.time_zero), placed.data_start)
    k = max(k, min(sec.n_samples, zero + 1), 1)
    if k >= sec.n_samples:
        return placed
    return replace(placed, section=replace(sec, amplitudes=sec.amplitudes[:, :k]),
                   depths=depths[:k])


def first_arrival(section: TraceSection, sample_limit: int = 2000, skip: int = 0) -> float:
    """An estimate of time zero (s; m for a depth section) from the mean trace of at most
    ``sample_limit`` traces taken with a regular stride: the first sample where the absolute
    mean trace, after removing its median, exceeds 5 % of its maximum; ``section.first`` when
    no sample does. The first ``skip`` samples of every trace (not data) are left out."""
    skip = min(section.n_samples, max(0, int(skip)))
    a = section.amplitudes[::max(1, math.ceil(section.n_traces / max(1, int(sample_limit))))]
    a = a[:, skip:]
    ns = a.shape[1]
    if ns == 0:
        return section.first
    total, count = np.zeros(ns), np.zeros(ns)
    for r0, r1 in _row_blocks(a.shape[0], ns):
        b = a[r0:r1].astype(np.float64)
        ok = np.isfinite(b)
        total += np.where(ok, b, 0.0).sum(axis=0)
        count += ok.sum(axis=0)
    ok = count > 0
    if not ok.any():
        return section.first
    mean = np.divide(total, count, out=np.zeros(ns), where=ok)
    m = np.where(ok, np.abs(mean - np.median(mean[ok])), 0.0)
    top = float(m.max())
    if not top > 0:
        return section.first
    return float(section.first + (skip + int(np.argmax(m > 0.05 * top))) * section.step)


#: AGC and trace balance divide by at least this share of the section's RMS: a muted or dead
#: part (zeros and numerical leftovers) stays quiet instead of being lifted to full strength
QUIET_SHARE = 0.001


def quiet_floor(amplitudes) -> float:
    """``QUIET_SHARE`` of the RMS of the finite, non-zero samples (a subsample of at most
    ``SAMPLE_LIMIT``); 0 when there are none."""
    v = _sample(amplitudes).astype(np.float64)
    v = v[np.isfinite(v) & (v != 0)]
    if not v.size:
        return 0.0
    return QUIET_SHARE * float(np.sqrt(np.mean(v * v)))


def _agc_into(src: np.ndarray, dst: np.ndarray, window: int, floor: float) -> np.ndarray:
    """``src`` with AGC written to ``dst`` (float32, may be ``src`` itself), block by block."""
    n = src.shape[1]
    window = max(1, int(window))
    k = np.arange(n)
    lo = np.clip(k - (window - 1) // 2, 0, n)
    hi = np.clip(k - (window - 1) // 2 + window, 0, n)
    for r0, r1 in _row_blocks(src.shape[0], n):
        a = src[r0:r1].astype(np.float64)
        ok = np.isfinite(a)
        sq = np.zeros((a.shape[0], n + 1))
        np.cumsum(np.where(ok, a * a, 0.0), axis=1, out=sq[:, 1:])
        cnt = np.zeros((a.shape[0], n + 1))
        np.cumsum(ok, axis=1, out=cnt[:, 1:])
        num = cnt[:, hi] - cnt[:, lo]
        with np.errstate(invalid="ignore", divide="ignore"):
            rms = np.fmax(np.sqrt(np.maximum(sq[:, hi] - sq[:, lo], 0.0) / num), floor)
            out = np.where(rms > 0, a / rms, np.where(ok, 0.0, a))
        dst[r0:r1] = out
    return dst


def agc(amplitudes: np.ndarray, window: int, floor: float | None = None) -> np.ndarray:
    """A float32 copy with each sample divided by the RMS of the ``window`` samples centred on
    it (fewer at the ends of a trace), but by no less than ``floor`` (None: ``quiet_floor``,
    so muted and dead parts stay quiet; 0: the plain division). Where the divisor is zero the
    sample becomes zero."""
    src = np.asarray(amplitudes)
    floor = quiet_floor(src) if floor is None else float(floor)
    return _agc_into(src, np.empty(src.shape, np.float32), window, floor)


@dataclass(frozen=True)
class DisplayGain:
    """How a section is shown (display only: the data are never changed)."""
    agc_window: float | None = None   # seconds (time section) or metres (depth); None = off
    time_power: float | None = None   # multiply by t**p (depth**p for a depth section)
    balance_traces: bool = False      # divide each trace by its own RMS
    reverse_polarity: bool = False
    #: paint the muted zones (``muted_mask``) too; by default they are left transparent
    show_muted: bool = False
    #: subtract a running mean along each trace over this window, seconds (metres for a depth
    #: section); None = off
    dewow_window: float | None = None
    #: one of ``BACKGROUNDS``: "" off, "all" subtract the mean trace of the whole line,
    #: "window" subtract the mean of the ``background_traces`` traces centred on each trace
    background: str = ""
    background_traces: int = 0        # odd; an even or smaller number is read as the next odd >= 3
    #: a band-pass along each trace (time sections only): its low and high corner, Hz; None
    #: or 0 = that corner off (one corner alone is a high-pass or a low-pass)
    band_low: float | None = None
    band_high: float | None = None

    def band_on(self) -> bool:
        """True when a corner of the band-pass is set (it may still be unusable for a
        section: ``band_weights``)."""
        return _corner(self.band_low) > 0 or _corner(self.band_high) > 0

    def active(self) -> bool:
        """True when the values shown differ from the file's (a gained copy is needed);
        ``show_muted`` only decides which samples are painted, so it does not count."""
        return bool((self.agc_window is not None and self.agc_window > 0)
                    or (self.time_power is not None and self.time_power != 0)
                    or self.balance_traces or self.reverse_polarity
                    or (self.dewow_window is not None and self.dewow_window > 0)
                    or self.background in ("all", "window") or self.band_on())

    def to_dict(self) -> dict:
        """The options as plain data; ``show_muted`` and the filters only when they are set
        (so options without them are stored as before)."""
        out = {"agc_window": self.agc_window, "time_power": self.time_power,
               "balance_traces": self.balance_traces, "reverse_polarity": self.reverse_polarity}
        if self.show_muted:
            out["show_muted"] = True
        if self.dewow_window is not None:
            out["dewow_window"] = self.dewow_window
        if self.background:
            out["background"] = self.background
        if self.background_traces:
            out["background_traces"] = self.background_traces
        if self.band_low is not None:
            out["band_low"] = self.band_low
        if self.band_high is not None:
            out["band_high"] = self.band_high
        return out

    @classmethod
    def from_dict(cls, d: dict | None) -> "DisplayGain":
        """From ``to_dict``; missing or unreadable keys take the defaults."""
        d = d if isinstance(d, dict) else {}

        def number(key):
            try:
                v = d.get(key)
                return None if v is None else float(v)
            except (TypeError, ValueError):
                return None

        try:
            traces = max(0, int(d.get("background_traces") or 0))
        except (TypeError, ValueError):
            traces = 0
        background = d.get("background") or ""
        return cls(number("agc_window"), number("time_power"), bool(d.get("balance_traces", False)),
                   bool(d.get("reverse_polarity", False)), bool(d.get("show_muted", False)),
                   number("dewow_window"), background if background in BACKGROUNDS else "", traces,
                   number("band_low"), number("band_high"))


def muted_mask(amplitudes: np.ndarray, live_from: np.ndarray | None = None) -> np.ndarray:
    """True (bool, the shape of ``amplitudes``) for the muted samples: the run of exact zeros
    at the start of each trace, the run at its end, and the whole of a trace that is all zero.
    Zeros between the first and last other sample are data and stay False. ``live_from`` (per
    trace, ``PlacedTraces.live_from``) also mutes every sample before that index."""
    a = np.asarray(amplitudes)
    n = a.shape[1]
    out = np.empty(a.shape, bool)
    k = np.arange(n)
    for r0, r1 in _row_blocks(a.shape[0], n):
        live = a[r0:r1] != 0                    # NaN counts as live: it is not a zero
        first = np.where(live.any(axis=1), live.argmax(axis=1), n)
        if live_from is not None:
            first = np.maximum(first, live_from[r0:r1])
        last = n - 1 - live[:, ::-1].argmax(axis=1)
        out[r0:r1] = (k[None, :] < first[:, None]) | (k[None, :] > last[:, None])
    return out


def _odd(n: float) -> int:
    """The nearest odd whole number to ``n`` (an even one goes up), at least 3."""
    return max(3, 2 * math.floor((float(n) - 1.0) / 2.0 + 0.5) + 1)


def trace_spacing(section: TraceSection) -> float | None:
    """The usual distance between neighbouring traces (m, the median), None when the traces
    give none (one trace, or all at one place)."""
    if section.n_traces < 2:
        return None
    gaps = np.abs(np.diff(np.asarray(section.x, dtype=np.float64)))
    spacing = float(np.median(gaps))
    return spacing if math.isfinite(spacing) and spacing > 0 else None


def window_traces(metres: float, spacing: float) -> int:
    """A window of ``metres`` along the line as an odd number of traces ``spacing`` apart
    (at least three)."""
    return _odd(float(metres) / float(spacing))


def _dewow_into(out: np.ndarray, window: int) -> None:
    """Subtract from each trace of ``out`` (float32, in place) the mean of the ``window``
    samples centred on each sample (fewer at the ends of a trace; NaN left out and kept)."""
    n = out.shape[1]
    k = np.arange(n)
    lo = np.clip(k - (window - 1) // 2, 0, n)
    hi = np.clip(k - (window - 1) // 2 + window, 0, n)
    for r0, r1 in _row_blocks(out.shape[0], n):
        a = out[r0:r1].astype(np.float64)
        ok = np.isfinite(a)
        s = np.zeros((a.shape[0], n + 1))
        if ok.all():                                # the usual case: every window is full
            np.cumsum(a, axis=1, out=s[:, 1:])
            a -= (s[:, hi] - s[:, lo]) / (hi - lo)
            out[r0:r1] = a
            continue
        np.cumsum(np.where(ok, a, 0.0), axis=1, out=s[:, 1:])
        cnt = np.zeros((a.shape[0], n + 1))
        np.cumsum(ok, axis=1, out=cnt[:, 1:])
        with np.errstate(invalid="ignore", divide="ignore"):
            out[r0:r1] = a - (s[:, hi] - s[:, lo]) / (cnt[:, hi] - cnt[:, lo])


def _background_all_into(out: np.ndarray) -> None:
    """Subtract the mean trace of the whole line (float64, NaN left out) from ``out``."""
    ns = out.shape[1]
    total, count = np.zeros(ns), np.zeros(ns)
    for r0, r1 in _row_blocks(out.shape[0], ns):
        a = out[r0:r1].astype(np.float64)
        ok = np.isfinite(a)
        total += np.where(ok, a, 0.0).sum(axis=0)
        count += ok.sum(axis=0)
    mean = np.divide(total, count, out=np.zeros(ns), where=count > 0)
    for r0, r1 in _row_blocks(out.shape[0], ns):
        out[r0:r1] = out[r0:r1].astype(np.float64) - mean


def _background_window_into(out: np.ndarray, width: int) -> None:
    """Subtract from each trace of ``out`` the mean of the ``width`` (odd) traces centred on
    it (fewer at the ends of the line; NaN left out and kept). The blocks of traces are worked
    through in order; the original values of the last ``width // 2`` traces of a block are
    kept aside before it is overwritten, as the next block's windows reach back into them."""
    nt, ns = out.shape
    h = (width - 1) // 2
    kept = np.zeros((0, ns))                       # original rows max(0, r0 - h) .. r0
    for r0, r1 in _row_blocks(nt, ns):
        lo, hi = r0 - kept.shape[0], min(nt, r1 + h)
        a = np.concatenate([kept, out[r0:hi].astype(np.float64)])     # rows lo .. hi
        ok = np.isfinite(a)
        s = np.zeros((a.shape[0] + 1, ns))
        i = np.arange(r0, r1)
        w0, w1 = np.maximum(i - h, 0) - lo, np.minimum(i + h + 1, nt) - lo
        if ok.all():                                # the usual case: no count needed
            np.cumsum(a, axis=0, out=s[1:])
            mean = (s[w1] - s[w0]) / (w1 - w0)[:, None]
        else:
            np.cumsum(np.where(ok, a, 0.0), axis=0, out=s[1:])
            cnt = np.zeros((a.shape[0] + 1, ns))
            np.cumsum(ok, axis=0, out=cnt[1:])
            with np.errstate(invalid="ignore", divide="ignore"):
                mean = (s[w1] - s[w0]) / (cnt[w1] - cnt[w0])
        del ok, s
        kept = a[max(0, r1 - h) - lo:r1 - lo].copy()
        out[r0:r1] = a[r0 - lo:r1 - lo] - mean


#: a band-pass corner is tapered with half a cosine: up from this share of the low corner to
#: the low corner, down from the high corner to this share of it
BAND_TAPER = (0.6, 1.4)


def _corner(v) -> float:
    """A band-pass corner as a usable number of Hz; 0.0 for off (None, 0, negative, NaN)."""
    try:
        v = float(v)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) and v > 0 else 0.0


def _rise(f: np.ndarray, a: float, b: float) -> np.ndarray:
    """0 below ``a``, 1 above ``b``, half a cosine between."""
    return 0.5 - 0.5 * np.cos(np.pi * np.clip((f - a) / (b - a), 0.0, 1.0))


def band_weights(n: int, step: float, low, high) -> np.ndarray | None:
    """The weights of the ``np.fft.rfftfreq(n, step)`` frequencies for a band-pass from
    ``low`` to ``high`` (Hz), the corners tapered as ``BAND_TAPER`` says; None when there is
    nothing to do: no corner set, ``low`` at or above Nyquist, or ``low`` at or above
    ``high``. A ``high`` at or above Nyquist is left out (only the low corner works)."""
    low, high = _corner(low), _corner(high)
    nyquist = 0.5 / float(step)
    if high >= nyquist:
        high = 0.0
    if low >= nyquist or (low and high and low >= high) or not (low or high):
        return None
    f = np.fft.rfftfreq(int(n), float(step))
    w = np.ones(f.size)
    if low:
        w *= _rise(f, BAND_TAPER[0] * low, low)
    if high:
        w *= 1.0 - _rise(f, high, BAND_TAPER[1] * high)
    return w


def _fft_size(n: int) -> int:
    """The smallest product of 2, 3 and 5 not below ``n`` (fast for the FFT)."""
    best = 1 << max(0, (int(n) - 1).bit_length())
    p5 = 1
    while p5 < best:
        p35 = p5
        while p35 < best:
            p = p35
            while p < n:
                p *= 2
            best = min(best, p)
            p35 *= 3
        p5 *= 5
    return best


def _band_pass_into(out: np.ndarray, step: float, low, high) -> None:
    """A zero-phase band-pass along each trace of ``out`` (float32, in place), block by block
    of traces. Each trace is continued past its end by a straight line back to its first
    value (so the FFT sees no jump where it wraps round) over at least as many samples as it
    has; NaN samples count as zero and are kept."""
    n = out.shape[1]
    nfft = _fft_size(2 * n)
    w = band_weights(nfft, step, low, high)
    if w is None or n < 2:
        return
    pad = nfft - n
    ramp = (np.arange(1, pad + 1) / (pad + 1))[None, :]
    for r0, r1 in _row_blocks(out.shape[0], nfft):
        a = out[r0:r1].astype(np.float64)
        bad = ~np.isfinite(a)
        if bad.any():
            a[bad] = 0.0
        buf = np.empty((a.shape[0], nfft))
        buf[:, :n] = a
        last, first = a[:, -1:], a[:, :1]
        buf[:, n:] = last + (first - last) * ramp
        del a
        spec = np.fft.rfft(buf, axis=1)
        del buf
        spec *= w
        got = np.fft.irfft(spec, n=nfft, axis=1)[:, :n]
        del spec
        if bad.any():
            got[bad] = np.nan
        out[r0:r1] = got


def display_values(section: TraceSection, gain: DisplayGain, *, time_zero: float = 0.0,
                   skip: int = 0) -> np.ndarray:
    """The values to draw: the section's own array when ``gain`` is not active, else one
    float32 copy with, in this order, dewow, band-pass (a time section only), background
    removal, time power, AGC, trace balance and polarity applied (each worked through in
    blocks of traces). Dewow and band-pass are both filters along the trace and would give
    the same in either order; dewow goes first so that the band-pass starts from traces
    without their slow drift.

    ``skip``: the leading samples of every trace that are not data; in the copy they are NaN
    and no filter sees them. ``time_zero`` (s): the time power counts from it (``t -
    time_zero``, 0 before it); the other options do not depend on it."""
    if not gain.active():
        return section.amplitudes
    copy = section.amplitudes.astype(np.float32)
    skip = min(section.n_samples, max(0, int(skip)))
    if skip:
        copy[:, :skip] = np.nan
    out = copy[:, skip:]                        # the data samples (a view of the copy)
    if out.shape[1]:
        _gain_into(out, section.sample_axis()[skip:], section.step, gain, float(time_zero),
                   section.domain == "time")
    return copy


def _gain_into(out: np.ndarray, axis: np.ndarray, step: float, gain: DisplayGain,
               time_zero: float, time: bool = True) -> None:
    """``display_values``' options applied to ``out`` (float32, in place); ``axis`` the time
    (or depth) of each of its samples; ``time`` False for a depth section (no band-pass)."""
    if gain.dewow_window is not None and gain.dewow_window > 0:
        _dewow_into(out, _odd(gain.dewow_window / step))
    if time and gain.band_on():
        _band_pass_into(out, step, gain.band_low, gain.band_high)
    if gain.background == "all":
        _background_all_into(out)
    elif gain.background == "window":
        _background_window_into(out, _odd(gain.background_traces))
    if gain.time_power is not None and gain.time_power != 0:
        t = axis - time_zero
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            f = np.abs(t) ** gain.time_power
        if time_zero:
            f = np.where(t < 0, 0.0, f)         # nothing before time zero
        out *= np.where(np.isfinite(f), f, 0.0).astype(np.float32)
    if gain.agc_window is not None and gain.agc_window > 0:
        _agc_into(out, out, max(1, round(gain.agc_window / step)), quiet_floor(out))
    if gain.balance_traces:
        floor = quiet_floor(out)                # a dead trace stays dead
        for r0, r1 in _row_blocks(out.shape[0], out.shape[1]):
            a = out[r0:r1].astype(np.float64)
            ok = np.isfinite(a)
            n = ok.sum(axis=1)
            with np.errstate(invalid="ignore", divide="ignore"):
                rms = np.sqrt(np.where(ok, a * a, 0.0).sum(axis=1) / n)
            rms = np.where(np.isfinite(rms) & (rms > 0), np.fmax(rms, floor), 1.0)
            out[r0:r1] = a / rms[:, None]
    if gain.reverse_polarity:
        np.negative(out, out=out)


def placed_values(placed: PlacedTraces, gain: DisplayGain) -> np.ndarray:
    """``display_values`` of a hung section: with its time zero and its leading samples that
    are not data."""
    return display_values(placed.section, gain, time_zero=placed.time_zero,
                          skip=placed.data_start)


#: at most about this many values are gained for the colour limits of a display option
LIMIT_VALUES = 1 << 21


def limit_traces(section: TraceSection, gain: DisplayGain,
                 limit: int = LIMIT_VALUES) -> TraceSection:
    """A part of ``section``'s traces that is enough for the colour limits of
    ``display_values(…, gain)`` (only a regular subsample of the values counts for them):
    ``section`` itself when it holds at most ``limit`` values; else runs of neighbouring
    traces spread evenly over the line, about ``limit`` values in all. A run is one trace,
    or, with the moving-window background removal, four windows wide (so that most of its
    traces see a whole window). The amplitudes of the part are a copy of those traces."""
    n, ns = section.n_traces, section.n_samples
    keep = max(1, int(limit) // ns)
    if n <= keep:
        return section
    run = 4 * _odd(gain.background_traces) if gain.background == "window" else 1
    run = min(run, keep)
    starts = np.unique(np.linspace(0, n - run, max(1, keep // run)).round().astype(np.int64))
    idx = np.unique((starts[:, None] + np.arange(run)[None, :]).reshape(-1))
    return replace(section, amplitudes=section.amplitudes[idx], x=section.x[idx], numbers=None)


def _data_part(a: np.ndarray, skip: int) -> np.ndarray:
    """``a`` (traces x samples) without its first ``skip`` samples; ``a`` itself otherwise."""
    return a[:, max(0, int(skip)):] if skip and a.ndim == 2 else a


def limit_sample(values, skip: int = 0) -> np.ndarray:
    """The values ``color_limits`` looks at (a regular subsample of at most ``SAMPLE_LIMIT``,
    as a small array of its own), without the first ``skip`` samples of every trace."""
    return np.array(_sample(_data_part(np.asarray(values), skip)))


def color_limits(values, percent: float, skip: int = 0) -> tuple[float, float]:
    """Colour range for ``values`` (a TraceSection or an array) clipped at the ``percent``
    percentile of the absolute values: ``(-c, c)`` for signed data, ``(0, c)`` for data that
    are never negative; never empty (``(-1, 1)`` / ``(0, 1)`` without a usable ``c``).
    ``skip``: the leading samples of every trace (traces x samples) that are not data are
    left out; a one-dimensional sample (``limit_sample``) is taken as it is."""
    a = values.amplitudes if isinstance(values, TraceSection) else np.asarray(values)
    a = _data_part(a, skip)
    signed, c = _signed(a), _clip(a, percent)
    if not (math.isfinite(c) and c > 0):
        c = 1.0
    return (-c, c) if signed else (0.0, c)


def reduce_image(placed: PlacedTraces, max_width: int = 4096, max_height: int = 4096,
                 amplitudes: np.ndarray | None = None, mute: np.ndarray | None = None
                 ) -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """The section as a picture on a regular s/z grid: ``(values, (smin, smax, zmin, zmax))``,
    ``values`` (h, w) float32 with row 0 at ``zmax`` and NaN where no trace reaches.

    Each trace's column reaches half way to its neighbours and each sample half way to the
    next; the extent includes that half spacing on every side. Columns are as narrow as the
    closest traces and rows as thin as the closest samples (an uneven depth grid from a
    velocity function becomes an even one), capped at ``max_width`` / ``max_height``. A cell
    that holds trace or sample centres keeps the one with the largest absolute value, with its
    sign; any other cell takes the nearest trace and sample. Where ``z_top`` varies, columns
    shift and cells below or above a trace are NaN.

    ``amplitudes`` (default the section's own) are the values to draw, such as a gained copy
    from ``display_values(placed.section, ...)``; they must be in the placed trace order.
    ``mute`` (bool, same shape and order, such as ``muted_mask`` of the placed samples) leaves
    out the samples it marks: a cell all of whose samples are muted stays NaN, any other cell
    keeps the strongest of its samples that are not."""
    sec = placed.section
    a = sec.amplitudes if amplitudes is None else np.asarray(amplitudes)
    if a.shape != sec.amplitudes.shape:
        raise ValueError(f"{a.shape} values for a section of {sec.amplitudes.shape} samples.")
    if mute is not None:
        mute = np.asarray(mute, bool)
        if mute.shape != a.shape:
            raise ValueError(f"A mute of {mute.shape} for a section of {a.shape} samples.")
    s_edges = _edges(sec.x)
    d_edges = _edges(placed.depths)
    zt = placed.z_top
    s0, s1 = float(s_edges[0]), float(s_edges[-1])
    zmax = float(zt.max() - d_edges[0])
    zmin = float(zt.min() - d_edges[-1])
    w = _cells(s1 - s0, np.diff(s_edges), max_width)
    h = _cells(zmax - zmin, np.diff(d_edges), max_height)
    ds, dz = (s1 - s0) / w, (zmax - zmin) / h

    # the traces each column draws from: those centred in it, else the one covering its centre
    col = np.clip(((sec.x - s0) / ds).astype(np.int64), 0, w - 1)
    own = np.bincount(col, minlength=w)
    nearest = np.clip(_find(s_edges, s0 + (np.arange(w) + 0.5) * ds), 0, sec.n_traces - 1)
    first_own = np.searchsorted(col, np.arange(w))
    count = np.where(own > 0, own, 1)
    start = np.where(own > 0, first_own, 0)
    src = np.concatenate([np.arange(st, st + c) if o else np.array([nearest[j]])
                          for j, (st, c, o) in enumerate(zip(start, count, own))])
    col_start = np.concatenate([[0], np.cumsum(count)[:-1]])

    if (zt == zt[0]).all() and w * sec.n_samples <= 32 * _BLOCK:
        # one top for all traces: every trace maps samples to rows alike, so the columns can be
        # reduced first (same result, far less work)
        a = _columns(a, src, col_start, count, mute)
        mute = None                                 # the columns hold NaN where muted
        zt = np.full(w, zt[0])
        src, col_start, count = np.arange(w), np.arange(w), np.ones(w, np.int64)

    image = np.full((h, w), np.nan, np.float32)
    zc = zmax - (np.arange(h) + 0.5) * dz           # row centres
    budget = max(1, _BLOCK // max(h, sec.n_samples))
    j0 = 0
    while j0 < w:
        j1 = j0 + 1
        while j1 < w and col_start[j1] + count[j1] - col_start[j0] <= budget:
            j1 += 1
        lo, hi = col_start[j0], col_start[j1 - 1] + count[j1 - 1]
        rows = _trace_rows(a, src[lo:hi], zt, placed.depths, d_edges, zc, zmax, dz, mute)
        image[:, j0:j1] = _strongest(rows, col_start[j0:j1] - lo, axis=0).T
        j0 = j1
    return image, (s0, s1, zmin, zmax)


def _columns(a, src, col_start, count, mute=None) -> np.ndarray:
    """(w, n_samples) float32: per column the strongest of its source traces, sample by
    sample (muted samples left out, NaN where all are), worked through in blocks of whole
    columns."""
    w, ns = col_start.size, a.shape[1]
    out = np.empty((w, ns), np.float32)
    budget = max(1, _BLOCK // ns)
    j0 = 0
    while j0 < w:
        j1 = j0 + 1
        while j1 < w and col_start[j1] + count[j1] - col_start[j0] <= budget:
            j1 += 1
        lo, hi = col_start[j0], col_start[j1 - 1] + count[j1 - 1]
        vals = a[src[lo:hi]].astype(np.float32)
        if mute is not None:
            vals[mute[src[lo:hi]]] = np.nan
        out[j0:j1] = vals if hi - lo == j1 - j0 else _strongest(vals, col_start[j0:j1] - lo, axis=0)
        j0 = j1
    return out


def _cells(span: float, widths: np.ndarray, cap: int) -> int:
    """How many even cells cover ``span``: as narrow as the narrowest positive width, at most
    ``cap`` and at least one."""
    widths = widths[widths > 0]
    if not widths.size or not span > 0:
        return 1
    return int(min(max(1, cap), max(1, math.ceil(span / widths.min() - 1e-6))))


def _trace_rows(a, traces, zt, depths, d_edges, zc, zmax, dz, mute=None) -> np.ndarray:
    """(len(traces), h) float32: each trace on the image rows (strongest sample per row, else
    the nearest sample, NaN above and below the trace and where the samples are muted)."""
    h = zc.size
    tz = zt[traces]
    vals = a[traces].astype(np.float32)
    if mute is not None:
        vals[mute[traces]] = np.nan
    d = tz[:, None] - zc[None, :]                      # depth of each row centre below the top
    k = np.searchsorted(d_edges, d, side="right") - 1
    k = np.where(d == d_edges[-1], depths.size - 1, k)
    inside = (k >= 0) & (k < depths.size)
    rows = np.ascontiguousarray(np.take_along_axis(vals, np.clip(k, 0, depths.size - 1), axis=1))
    rows[~inside] = np.nan
    # rows that hold sample centres keep the strongest of them
    r = np.clip(np.floor((zmax - tz[:, None] + depths[None, :]) / dz).astype(np.int64), 0, h - 1)
    cell = (np.arange(traces.size)[:, None] * h + r).reshape(-1)
    starts = np.flatnonzero(np.r_[True, cell[1:] != cell[:-1]])
    rows.reshape(-1)[cell[starts]] = _strongest(vals.reshape(-1), starts, axis=0)
    return rows
