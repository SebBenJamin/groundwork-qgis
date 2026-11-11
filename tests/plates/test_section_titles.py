"""Round 2, F1: each section frame on a plate gets a title (the profile's name) inside its top
edge; the section keeps clear of it; Update keeps the user's edits and moves."""
from dataclasses import replace

from tests.plates.test_build import _plate, env  # noqa: F401


def _build(prj, st, prov, plate):
    from geophysics_workbench.plates.build import create_or_update_plate
    return create_or_update_plate(prj, st, prov, plate)


def _rect(item):
    from geophysics_workbench.plates.build import _rect
    return _rect(item)


def _second_profile(st, p):
    from geophysics_workbench.core.model import Profile
    q = Profile("p2", "Line B", p.chainage.xy + 100.0, st.crs_authid)
    st.save_profile(q)
    return q


def test_title_per_frame(env):
    st, p, prov, prj = env
    layout = _build(prj, st, prov, _plate(st, p, frames=2))
    for n in (1, 2):
        title = layout.itemById(f"wb_section_title_{n}")
        assert title is not None and title.text() == p.name
        assert title.textFormat().font().bold()
        from geophysics_workbench.plates.build import SECTION_TITLE_MM, _interior_rect_mm
        frame = layout.itemById(f"wb_frame_{n}")
        fx, fy, fw, fh = _rect(frame)
        left, top, width, _h = _interior_rect_mm(frame)
        tx, ty, tw, th = _rect(title)                    # in the plot area's top strip
        assert fx + left <= tx and tx + tw <= fx + left + width
        assert fy + top <= ty and ty + th <= fy + top + SECTION_TITLE_MM
        assert title.hasBackground()


def test_title_does_not_overlap_section(env):
    from geophysics_workbench.plates.build import (SECTION_TITLE_MM, frame_scale_and_ve,
                                                   label_room_mm, snapshot_extent)
    st, p, prov, prj = env
    plate = _plate(st, p)
    layout = _build(prj, st, prov, plate)
    snap = prov.snapshot(p.id, look=plate.frames[0].look)
    room = label_room_mm(snap) + SECTION_TITLE_MM
    item = layout.itemById("wb_frame_1")
    scale, ve = frame_scale_and_ve(item)
    top = snapshot_extent(snap, p.chainage.length)[3]
    assert item.plot().yMaximum() - top >= room * scale / (1000.0 * ve) * 0.98


def test_edited_title_kept_on_update(env):
    st, p, prov, prj = env
    plate = _plate(st, p)
    layout = _build(prj, st, prov, plate)
    layout.itemById("wb_section_title_1").setText("Profil 3 – Nordteil")
    layout = _build(prj, st, prov, plate)
    assert layout.itemById("wb_section_title_1").text() == "Profil 3 – Nordteil"


def test_profile_change_updates_unedited_title(env):
    st, p, prov, prj = env
    q = _second_profile(st, p)
    plate = _plate(st, p)
    _build(prj, st, prov, plate)
    moved = replace(plate, frames=[replace(plate.frames[0], profile_id=q.id)])
    layout = _build(prj, st, prov, moved)
    assert layout.itemById("wb_section_title_1").text() == "Line B"


def test_moved_title_stays(env):
    from geophysics_workbench.plates.build import _place
    st, p, prov, prj = env
    plate = _plate(st, p)
    layout = _build(prj, st, prov, plate)
    title = layout.itemById("wb_section_title_1")
    _place(title, 20.0, 15.0, 80.0, 8.0)
    layout = _build(prj, st, prov, plate)
    assert _rect(layout.itemById("wb_section_title_1")) == (20.0, 15.0, 80.0, 8.0)


def test_existing_plate_gets_title_on_update(env):
    st, p, prov, prj = env
    plate = _plate(st, p)
    layout = _build(prj, st, prov, plate)
    title = layout.itemById("wb_section_title_1")
    if title is not None:                           # never pass None: QGIS crashes
        layout.removeLayoutItem(title)              # as on a 0.7 plate
    layout = _build(prj, st, prov, plate)
    assert layout.itemById("wb_section_title_1").text() == p.name


def test_title_removed_with_frame(env):
    st, p, prov, prj = env
    plate = _plate(st, p, frames=2)
    _build(prj, st, prov, plate)
    layout = _build(prj, st, prov, replace(plate, frames=plate.frames[:1]))
    assert layout.itemById("wb_section_title_2") is None
    assert layout.itemById("wb_section_title_1") is not None
