"""Where each distance-based dataset sits on its profile, resolved every time a section is
built. QGIS-free; plain data in, plain data out, nothing stored.

The order, strongest first:

1. pinned at the known points: two or more stations of the dataset's station set (else the
   profile's first set) with a distance in the file (``core.layout.inline_distances``). A
   guessed spacing whose fit report warns is not used: the stations with a stronger source
   pin when there are two or more, else the next rule applies ("guess_rejected", with a
   note); a set of known points that cannot pin (a station out of order) is not used either,
   with a note;
2. the dataset's own ``reader_options["placement"]`` (``{"zero": chainage, "direction": ±1}``);

Before all of them: the dataset's own pins (``placement["pins"]``), a file the user fitted to
its line's length (source "fitted").
3. 0.8's station-set rule, ``metre0 + direction * x``;
4. file distance 0 at chainage 0.

Stations invented by 0.8 ("from line" / "from points": no heights, on the line, evenly
spaced) are never known points. The dataset's ``chainage_offset`` is added to file x before
the map in every case; the maps returned here already include it."""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from ..core.layout import inline_distances
from ..core.model import Dataset, Profile, StationSet
from ..core.placement import DistanceMap, FitReport, fit_report, pinned_map, rigid_map
from ..core.point_names import station_label

GUESS_REJECTED_NOTE = ("Known points not used: the station spacing guessed from the model "
                       "does not fit them; type the station spacing in Profile Properties")
NOT_USED_NOTE = "Known points not used: {reason}"
#: ``word``: "electrode", or "geophone" for a refraction profile
NO_STATIONS_NOTE = "No {word} positions: import them or type the spacing in Profile Properties"
NO_ELECTRODES_NOTE = NO_STATIONS_NOTE.format(word="electrode")
#: metres: offsets and gaps of invented stations agree to this (float noise on UTM lines)
INVENTED_TOL = 1e-6


@dataclass
class ProfileLayout:
    """What a profile's in-line layout is resolved from: the readings file's electrode x (in
    file order, NaN for a remote pole), the typed electrode spacing, and the electrode
    positions and spacing guessed from the first model."""
    readings_x: np.ndarray | None = None
    spacing: float | None = None
    guess: np.ndarray | None = None
    guessed_spacing: float | None = None


@dataclass
class Resolution:
    map: DistanceMap            # file x -> chainage, the dataset's chainage_offset included
    source: str                 # inline_distances' source when pinned; "rigid", "guess_rejected"
    fit: FitReport | None = None    # of the pins, when pinned
    note: str = ""              # why known points were not used; "" otherwise


def invented(station_set: StationSet) -> bool:
    """True for a station set 0.8 made from a line or points rather than a survey: at least
    three stations, no stored in-line distance, no finite elevation, every offset 0 (or
    NaN), chainage evenly spaced."""
    s = np.asarray(station_set.chainage, dtype=float)
    if s.size < 3 or not np.isfinite(s).all():
        return False
    if np.isfinite(station_set.inline).any():    # 0.8 stored no in-line distances
        return False
    xyz = np.asarray(station_set.xyz, dtype=float)
    if xyz.ndim == 2 and xyz.shape[1] >= 3 and np.isfinite(xyz[:, 2]).any():
        return False
    off = np.asarray(station_set.offset, dtype=float)
    if (np.abs(off[np.isfinite(off)]) > INVENTED_TOL).any():
        return False
    gaps = np.diff(np.sort(s))
    return bool(gaps.min() > INVENTED_TOL and np.ptp(gaps) <= INVENTED_TOL)


def _station_set(sets: list[StationSet], dataset: Dataset) -> StationSet | None:
    by_id = {s.id: s for s in sets}
    return by_id.get(dataset.station_set_id) or (sets[0] if sets else None)


def _pins(station_set: StationSet, layout: ProfileLayout):
    """(file distances, chainages, labels, source) of the stations with both, or None for
    fewer than two."""
    numbers = np.asarray(station_set.numbers)
    args = (layout.readings_x, layout.spacing, layout.guessed_spacing)
    d, source = inline_distances(numbers, station_set.inline, *args)
    s = np.asarray(station_set.chainage, dtype=float)
    ok = np.isfinite(d) & np.isfinite(s)
    if ok.sum() < 2:
        return None
    if source == "none":
        # some stations have no distance (so neither spacing is usable): the weakest source
        # among the ones that do
        _, source = inline_distances(numbers[ok], station_set.inline[ok], *args)
    labels = [station_label(name, n) for name, n, keep in zip(station_set.names, numbers, ok)
              if keep]
    return d[ok], s[ok], labels, source


def _not_used(exc: ValueError) -> str:
    """``pinned_map``'s reason in station words: "Known point 11 is out of order along the
    line." becomes "station 11 is out of order along the line"."""
    reason = str(exc).rstrip(".")
    for old, new in (("Known points ", "stations "), ("Known point ", "station ")):
        if reason.startswith(old):
            reason = new + reason[len(old):]
            break
    return NOT_USED_NOTE.format(reason=reason)


def _own_pins(dataset: Dataset) -> DistanceMap | None:
    """The dataset's own pins (``placement["pins"]``: [[file distance, chainage], …], a
    file fitted to its line's length in Add Data), or None."""
    placement = dataset.reader_options.get("placement")
    pins = placement.get("pins") if isinstance(placement, dict) else None
    try:
        d, s = zip(*[(float(a), float(b)) for a, b in pins])
        return pinned_map(d, s)
    except (TypeError, ValueError):
        return None


def _own_placement(dataset: Dataset) -> DistanceMap | None:
    placement = dataset.reader_options.get("placement")
    if not isinstance(placement, dict):
        return None
    try:
        zero = float(placement["zero"])
        direction = -1 if float(placement.get("direction", 1)) < 0 else 1
    except (KeyError, TypeError, ValueError):
        return None
    return rigid_map(zero, direction) if np.isfinite(zero) else None


def _unpinned(dataset: Dataset, station_set: StationSet | None) -> DistanceMap:
    own = _own_placement(dataset)
    if own is not None:
        return own
    if station_set is not None:              # 0.8: metre0 + direction * x
        return rigid_map(float(station_set.metre0), station_set.direction)
    return rigid_map(0.0)


def _with_offset(dmap: DistanceMap, offset: float) -> DistanceMap:
    """The map of ``x + offset``: the pins move by ``-offset`` in file distance."""
    return DistanceMap(dmap.d - offset, dmap.s, dmap.direction) if offset else dmap


def resolve(profile: Profile, sets: list[StationSet], dataset: Dataset,
            layout: ProfileLayout) -> Resolution:
    """The placement of a distance-based ``dataset`` on ``profile`` (see the module text)."""
    try:
        offset = float(dataset.reader_options.get("chainage_offset", 0.0) or 0.0)
    except (TypeError, ValueError):
        offset = 0.0
    own = _own_pins(dataset)
    if own is not None:                         # the user fitted the file to its line
        return Resolution(_with_offset(own, offset), "fitted")
    station_set = _station_set(sets, dataset)
    source, note = "rigid", ""
    pins = None if station_set is None or invented(station_set) else _pins(station_set, layout)
    if pins is not None:
        d, s, labels, pin_source = pins
        fit = fit_report(d, s, labels)
        if pin_source == "guessed" and fit.warn:
            # the guess does not fit: the stations with a stronger source still pin
            pins = _pins(station_set, replace(layout, guess=None, guessed_spacing=None))
            if pins is None:
                source, note = "guess_rejected", GUESS_REJECTED_NOTE
            else:
                d, s, labels, pin_source = pins
                fit = fit_report(d, s, labels)
        if pins is not None:
            try:
                return Resolution(_with_offset(pinned_map(d, s, labels), offset), pin_source,
                                  fit)
            except ValueError as exc:            # e.g. a station out of order: next rule
                note = _not_used(exc)
    return Resolution(_with_offset(_unpinned(dataset, station_set), offset), source, None, note)


def resolve_map(profile: Profile, sets: list[StationSet], dataset: Dataset,
                layout: ProfileLayout) -> tuple[DistanceMap, str]:
    """(map from the dataset's file x to chainage, layout source used)."""
    r = resolve(profile, sets, dataset, layout)
    return r.map, r.source
