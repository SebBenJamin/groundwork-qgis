"""The plates stored in the project and one registered profile source per plate frame.

A frame item (QGIS's own layout elevation-profile item) remembers its source by id. When the
project is read before the plugin has registered the sources, QGIS leaves the item without
one; ``attach_frame_sources`` (run after every project read and store change) gives every
frame item its source and its profile's curve again. Sources are unregistered only after the
items are detached (they hold raw pointers)."""
from __future__ import annotations

from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem,
                       QgsLayoutItemElevationProfile, QgsLineString, QgsPoint)

from ..core.plates import plates_from_json, plates_to_json
from ..section.profile_source import FrameProfileSource

SCOPE = "geophysics_workbench"
PLATES_KEY = "plates"
FRAME_PROPERTY = "wb_frame_id"
_registered: list[str] = []


def read_plates(project) -> list:
    return plates_from_json(project.readEntry(SCOPE, PLATES_KEY, "")[0])


def write_plates(project, plates) -> None:
    project.writeEntry(SCOPE, PLATES_KEY, plates_to_json(plates))


def frame_items(project) -> list:
    """Every plate frame item (an elevation-profile item carrying a frame id) of the project."""
    out = []
    for layout in project.layoutManager().printLayouts():
        for item in layout.items():
            if isinstance(item, QgsLayoutItemElevationProfile) and \
                    item.customProperty(FRAME_PROPERTY):
                out.append(item)
    return out


def detach_frame_items(project) -> None:
    for item in frame_items(project):
        item.setSources([])


def unregister_frame_sources() -> None:
    registry = QgsApplication.profileSourceRegistry()
    for source_id in _registered:
        if registry.findSourceById(source_id) is not None:
            registry.unregisterProfileSource(source_id)
    _registered.clear()


def register_frame_sources(provider, plates) -> dict:
    """One source per frame of ``plates`` (earlier ones of ours unregistered first: detach
    the items before calling this)."""
    unregister_frame_sources()
    registry = QgsApplication.profileSourceRegistry()
    out = {}
    for plate in plates:
        for frame in plate.frames:
            source = FrameProfileSource(provider, frame)
            if registry.findSourceById(source.profileSourceId()) is not None:
                registry.unregisterProfileSource(source.profileSourceId())
            if registry.registerProfileSource(source):
                _registered.append(source.profileSourceId())
                out[frame.frame_id] = source
    return out


def profile_curve(profile) -> QgsLineString:
    return QgsLineString([QgsPoint(float(x), float(y)) for x, y in profile.chainage.xy])


def attach_frame_sources(project, store, sources: dict) -> None:
    """Give every frame item its source and its profile's curve (none when the frame or its
    profile is gone: the item then shows nothing, see ``build`` for the placeholder)."""
    by_frame = {f.frame_id: f for p in read_plates(project) for f in p.frames}
    profiles = {p.id: p for p in store.profiles()} if store is not None else {}
    for item in frame_items(project):
        fid = item.customProperty(FRAME_PROPERTY)
        frame, source = by_frame.get(fid), sources.get(fid)
        profile = profiles.get(frame.profile_id) if frame is not None else None
        if source is None or profile is None:
            item.setSources([])
            continue
        item.setCrs(QgsCoordinateReferenceSystem(store.crs_authid))
        item.setProfileCurve(profile_curve(profile))
        item.setSources([source])
        item.refresh()
