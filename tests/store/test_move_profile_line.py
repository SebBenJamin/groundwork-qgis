"""Moving a profile's line to surveyed points: what sits on the line goes along."""
import numpy as np
import pytest


@pytest.fixture
def populated(tmp_path):
    from geophysics_workbench.core.field_notes import FieldNote
    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id
    from geophysics_workbench.core.model import profile_from_stations
    from geophysics_workbench.store.gpkg_store import ProjectStore

    st = ProjectStore.create(tmp_path / "m.gpkg", "EPSG:25832")
    xyz = np.column_stack([np.linspace(0, 100, 5), np.zeros(5), np.zeros(5)])
    p, s = profile_from_stations("P", "EPSG:25832", xyz)
    st.save_profile(p)
    st.save_station_set(s)
    st.ensure_interpretation()
    v = st.current_version()
    f = InterpFeature(new_id(), v.id, type="clay", name="A")
    st.save_feature(f)
    st.save_piece(InterpPiece(new_id(), v.id, f.id, p.id, "line", [(40.0, -5.0), (60.0, -5.0)]))
    st.save_field_note(FieldNote("n1", p.id, 40.0, None, "fence"))
    return st, p, np.array([[0, 2], [50, 2], [100, 6.0]])


def test_move_profile_line_remaps_notes_and_pieces(populated):
    st, p, new_xy = populated
    counts = st.move_profile_line(p.id, new_xy)
    assert counts == {"stations": 5, "pieces": 1, "notes": 1}
    moved = st.profile(p.id)
    assert np.allclose(moved.xy, new_xy)
    note = st.field_notes(p.id)[0]
    assert np.hypot(*(moved.chainage.to_xy(note.s_from) - [40, 0])) < 3
    [piece] = st.pieces(st.current_version().id, p.id)
    assert piece.vertices[0][1] == -5.0 and piece.vertices[1][0] > piece.vertices[0][0]
    [sset] = st.station_sets(p.id)
    assert sset.offset[0] == pytest.approx(-2.0) and "station 5" in sset.warnings[0]
    assert sset.chainage[-1] == pytest.approx(moved.chainage.length, abs=1.0)


def test_move_leaves_frozen_versions_alone(populated):
    st, p, new_xy = populated
    frozen = st.freeze_current("Delivered")
    before = [q.vertices for q in st.pieces(frozen.id, p.id)]
    st.move_profile_line(p.id, new_xy)
    assert [q.vertices for q in st.pieces(frozen.id, p.id)] == before
    assert st.pieces(st.current_version().id, p.id)[0].vertices != before[0]
