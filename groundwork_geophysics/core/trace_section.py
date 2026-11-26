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
#: how the rows of a velocity function are read (an unknown kind reads as "average")
KINDS = ("average", "interval", "rms")


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


def sample_depths(section: TraceSection, velocity: Velocity | None) -> np.ndarray:
    """Depth below time zero / depth zero of each sample, m.

    A depth section: ``first + k * step`` (``velocity`` is ignored). A time section with one
    velocity: ``v * t / 2``. With an average velocity function: ``v(t) * t / 2``, ``v`` linear
    between rows and constant outside. With an interval velocity function each row's velocity
    holds from its time to the next row's (the first row's also above it, the last row's below
    it) and depth is the running sum. RMS velocities are turned into interval velocities by
    Dix's formula (the first row's velocity down to its time, the last interval's below the
    last row) and summed the same way. ValueError without a usable velocity, for a table whose
    times do not increase, for an average function whose depths do not increase, and for RMS
    velocities that give no real interval velocity."""
    axis = section.sample_axis()
    if section.domain == "depth":
        return axis
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
                             f"{tt[i] * 1000:.0f} ms and {tt[i + 1] * 1000:.0f} ms.")
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


def ground_time(datum: float, ground: np.ndarray, replacement_velocity: float) -> np.ndarray:
    """Two-way time (s) from the datum down to the ground at each trace with the replacement
    velocity (m/s): ``2 * (datum - ground) / replacement_velocity``, negative where the ground
    lies above the datum."""
    ground = np.asarray(ground, dtype=np.float64)
    return 2.0 * (float(datum) - ground) / float(replacement_velocity)


def depth_at(section: TraceSection, velocity: Velocity | None, times: np.ndarray) -> np.ndarray:
    """Depth below time zero (m) at ``times`` (s), as ``sample_depths`` gives it for the
    samples: interpolated between them, and beyond the first and last sample continued in a
    straight line with the slope at that end. With one velocity that is ``v * t / 2`` for any
    time. ValueError for a depth section (it has no times) and as ``sample_depths``."""
    if section.domain != "time":
        raise ValueError("A depth section has no times to give depths for.")
    times = np.asarray(times, dtype=np.float64)
    depths = sample_depths(section, velocity)
    if not velocity.table:
        return velocity.value * times / 2.0
    axis = section.sample_axis()
    if axis.size == 1:                       # one sample: the slope from the function itself
        ends = sample_depths(replace(section, amplitudes=np.zeros((1, 2), np.float32),
                                     x=np.zeros(1), numbers=None), velocity)
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
    below it (m, increasing). ``live_from``, when set, is per trace the first sample that
    belongs to the earth (one corrected to the ground: the samples above the ground line are
    not drawn; see ``muted_mask``)."""
    section: TraceSection
    z_top: np.ndarray
    depths: np.ndarray
    live_from: np.ndarray | None = None

    def bounds(self) -> tuple[float, float, float, float]:
        """``(smin, smax, zmin, zmax)``: first to last trace, top of the highest trace to the
        last sample of the lowest."""
        x = self.section.x
        return (float(x[0]), float(x[-1]), float(self.z_top.min() - self.depths[-1]),
                float(self.z_top.max()))

    def hit(self, s: float, z: float) -> dict | None:
        """The sample under the profile point ``(s, z)``: the nearest trace when ``s`` lies
        within half a trace spacing of it, the nearest sample when ``z`` lies below the
        trace's top and within half a sample spacing of it; None outside the picture. The
        amplitude is the file's own number (no gain, no polarity swap)."""
        sec = self.section
        i = int(_find(_edges(sec.x), s))
        if not 0 <= i < sec.n_traces:
            return None
        d = float(self.z_top[i]) - z
        if d < 0:
            return None
        k = int(_find(_edges(self.depths), d))
        if not 0 <= k < sec.n_samples:
            return None
        number = None if sec.numbers is None else int(sec.numbers[i])
        time = float(sec.first + k * sec.step) if sec.domain == "time" else None
        return {"trace": i, "number": number, "sample": k, "amplitude": float(sec.amplitudes[i, k]),
                "time": time, "depth": float(self.depths[k])}


def place(section: TraceSection, z_top, velocity: Velocity | None,
          live_from: np.ndarray | None = None) -> PlacedTraces:
    """Hang ``section`` from ``z_top`` (one elevation or one per trace), with sample depths
    from ``velocity``. Traces whose ``x`` does not increase are put in order (stable sort); a
    section that runs backwards is a reversed view, any other order a copy in the file's type.
    In order already, the sample array is shared. ``live_from`` (one sample index per trace,
    or None) follows the traces' order."""
    depths = sample_depths(section, velocity)
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
    step = np.diff(section.x)
    if (step < 0).any():
        order = slice(None, None, -1) if (step < 0).all() else np.argsort(section.x, kind="stable")
        numbers = None if section.numbers is None else section.numbers[order]
        section = replace(section, amplitudes=section.amplitudes[order], x=section.x[order],
                          numbers=numbers)
        zt = zt[order]
        live_from = None if live_from is None else live_from[order]
    return PlacedTraces(section, np.ascontiguousarray(zt), depths,
                        None if live_from is None else np.ascontiguousarray(live_from))


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

    def active(self) -> bool:
        """True when the values shown differ from the file's (a gained copy is needed);
        ``show_muted`` only decides which samples are painted, so it does not count."""
        return bool((self.agc_window is not None and self.agc_window > 0)
                    or (self.time_power is not None and self.time_power != 0)
                    or self.balance_traces or self.reverse_polarity)

    def to_dict(self) -> dict:
        """The options as plain data; ``show_muted`` only when it is set (as stored before)."""
        out = {"agc_window": self.agc_window, "time_power": self.time_power,
               "balance_traces": self.balance_traces, "reverse_polarity": self.reverse_polarity}
        if self.show_muted:
            out["show_muted"] = True
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

        return cls(number("agc_window"), number("time_power"), bool(d.get("balance_traces", False)),
                   bool(d.get("reverse_polarity", False)), bool(d.get("show_muted", False)))


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


def display_values(section: TraceSection, gain: DisplayGain) -> np.ndarray:
    """The values to draw: the section's own array when ``gain`` is not active, else one
    float32 copy with, in this order, time power, AGC, trace balance and polarity applied."""
    if not gain.active():
        return section.amplitudes
    out = section.amplitudes.astype(np.float32)
    if gain.time_power is not None and gain.time_power != 0:
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            f = np.abs(section.sample_axis()) ** gain.time_power
        out *= np.where(np.isfinite(f), f, 0.0).astype(np.float32)
    if gain.agc_window is not None and gain.agc_window > 0:
        _agc_into(out, out, max(1, round(gain.agc_window / section.step)), quiet_floor(out))
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
    return out


def color_limits(values, percent: float) -> tuple[float, float]:
    """Colour range for ``values`` (a TraceSection or an array) clipped at the ``percent``
    percentile of the absolute values: ``(-c, c)`` for signed data, ``(0, c)`` for data that
    are never negative; never empty (``(-1, 1)`` / ``(0, 1)`` without a usable ``c``)."""
    a = values.amplitudes if isinstance(values, TraceSection) else np.asarray(values)
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
