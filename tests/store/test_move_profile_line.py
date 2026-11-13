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


def test_move_keeps_a_model_placed_from_the_end_in_place(populated, tmp_path):
    """A dataset without a station set stores where its file's zero lies as a chainage
    (``placement.zero`` with direction -1): the move carries it, so the model stays put."""
    import shutil

    from geophysics_workbench.core.model import Dataset, file_fingerprint
    from geophysics_workbench.section.data import SectionDataProvider
    from tests.conftest import FIXTURES

    st, p, _ = populated
    src = tmp_path / "f001_res.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    mt, sha = file_fingerprint(src)
    opts = {"z_kind": "depth", "placement": {"zero": 100.0, "direction": -1}}
    st.save_dataset(Dataset("d1", p.id, "", "ert_model", str(src), mt, sha, "r2_res_dat",
                            opts, {}, name="model"))

    def ends():
        prof = st.profile(p.id)
        x0, x1 = SectionDataProvider(st).layers(p.id)[0].mesh.bounds()[:2]
        return prof.chainage.to_xy(np.array([x0, x1]))[:, 0]

    before = ends()
    st.move_profile_line(p.id, np.array([[-20.0, 0.0], [100.0, 0.0]]))   # starts 20 m earlier
    [d] = st.datasets(p.id)
    assert d.reader_options["placement"]["zero"] == pytest.approx(120.0, abs=0.1)
    assert d.reader_options["placement"]["direction"] == -1
    assert np.allclose(np.sort(ends()), np.sort(before), atol=1.0)


def test_a_failed_move_changes_nothing(populated, monkeypatch):
    st, p, new_xy = populated
    before = (st.profile(p.id), st.field_notes(p.id), st.station_sets(p.id),
              st.pieces(st.current_version().id, p.id))

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(st, "_write_piece", boom)        # after the notes were written
    with pytest.raises(RuntimeError):
        st.move_profile_line(p.id, new_xy, metadata={"electrode_spacing": 5.0}, name="Other")
    monkeypatch.undo()
    after = st.profile(p.id)
    assert after.name == before[0].name == "P" and np.allclose(after.xy, before[0].xy)
    assert after.metadata == before[0].metadata
    assert [(n.s_from, n.s_to) for n in st.field_notes(p.id)] == \
        [(n.s_from, n.s_to) for n in before[1]]
    [s0], [s1] = before[2], st.station_sets(p.id)
    assert np.allclose(s0.chainage, s1.chainage) and np.allclose(s0.offset, s1.offset)
    assert st.pieces(st.current_version().id, p.id)[0].vertices == before[3][0].vertices
