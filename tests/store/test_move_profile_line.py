"""Moving a profile's line to surveyed points: what sits on the line goes along."""
import numpy as np
import pytest


@pytest.fixture
def populated(tmp_path):
    from groundwork_geophysics.core.field_notes import FieldNote
    from groundwork_geophysics.core.interpretation import InterpFeature, InterpPiece, new_id
    from groundwork_geophysics.core.model import profile_from_stations
    from groundwork_geophysics.store.gpkg_store import ProjectStore

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

    from groundwork_geophysics.core.model import Dataset, file_fingerprint
    from groundwork_geophysics.section.data import SectionDataProvider
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


OVERHANG = [-20.0, -10.0, 50.0, 115.0, 120.0]     # on the 100 m line: two before, two after


def _overhanging(st, p):
    """A line piece and a polygon reaching past both ends, and a note range past both."""
    from groundwork_geophysics.core.field_notes import FieldNote
    from groundwork_geophysics.core.interpretation import InterpPiece, new_id
    v = st.current_version()
    [f] = st.features(v.id)
    st.save_piece(InterpPiece("over", v.id, f.id, p.id, "line",
                              [(s, -2.0) for s in OVERHANG]))
    st.save_piece(InterpPiece("poly", v.id, f.id, p.id, "polygon",
                              [(-20.0, -1.0), (120.0, -1.0), (120.0, -9.0), (-20.0, -9.0)]))
    st.save_field_note(FieldNote("range", p.id, -15.0, 110.0, "wet meadow"))


def _moved(st, p):
    pieces = {q.id: [s for s, _z in q.vertices]
              for q in st.pieces(st.current_version().id, p.id)}
    note = next(n for n in st.field_notes(p.id) if n.id == "range")
    return pieces["over"], pieces["poly"], (note.s_from, note.s_to)


def test_a_move_keeps_what_lies_beyond_the_line_ends(populated):
    st, p, _ = populated
    _overhanging(st, p)
    st.move_profile_line(p.id, np.array([[0.0, 1.0], [100.0, 1.0]]))     # 1 m sideways
    line, poly, note = _moved(st, p)
    assert line == pytest.approx(OVERHANG)
    assert poly == pytest.approx([-20.0, 120.0, 120.0, -20.0, -20.0])     # ring closed
    assert note == pytest.approx((-15.0, 110.0))


def test_a_move_onto_a_reversed_line_keeps_what_lies_beyond_the_ends(populated):
    st, p, _ = populated
    _overhanging(st, p)
    st.move_profile_line(p.id, np.array([[100.0, 1.0], [0.0, 1.0]]))     # runs the other way
    line, poly, note = _moved(st, p)
    assert line == pytest.approx([120.0, 110.0, 50.0, -15.0, -20.0])
    assert poly == pytest.approx([120.0, -20.0, -20.0, 120.0, 120.0])
    assert note == pytest.approx((115.0, -10.0))


def test_a_move_failing_after_the_datasets_leaves_their_placement(populated, tmp_path,
                                                                    monkeypatch):
    """The last write (the new station set) fails after a placed dataset was rewritten:
    the whole move rolls back, ``placement.zero`` included."""
    import shutil

    from groundwork_geophysics.core.model import Dataset, attach_station_set, file_fingerprint
    from tests.conftest import FIXTURES

    st, p, new_xy = populated
    src = tmp_path / "f001_res.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    mt, sha = file_fingerprint(src)
    opts = {"z_kind": "depth", "placement": {"zero": 100.0, "direction": -1}}
    st.save_dataset(Dataset("d1", p.id, "", "ert_model", str(src), mt, sha, "r2_res_dat",
                            opts, {}, name="model"))
    before = (st.profile(p.id), st.station_sets(p.id), st.field_notes(p.id),
              st.pieces(st.current_version().id, p.id), st.datasets(p.id))
    new_set = attach_station_set(st.profile(p.id), "new", "ert",
                                 np.column_stack([new_xy, np.zeros(len(new_xy))]))
    real = st._write_station_set

    def fail_on_the_new_set(ds, station_set):
        if station_set.id == new_set.id:
            raise RuntimeError("disk full")
        real(ds, station_set)

    monkeypatch.setattr(st, "_write_station_set", fail_on_the_new_set)
    with pytest.raises(RuntimeError):
        st.move_profile_line(p.id, new_xy, new_set)
    monkeypatch.undo()
    assert [d.reader_options for d in st.datasets(p.id)] == \
        [d.reader_options for d in before[4]]
    assert st.datasets(p.id)[0].reader_options["placement"]["zero"] == 100.0
    assert np.allclose(st.profile(p.id).xy, before[0].xy)
    assert [s.id for s in st.station_sets(p.id)] == [s.id for s in before[1]]
    assert np.allclose(st.station_sets(p.id)[0].chainage, before[1][0].chainage)
    assert [(n.s_from, n.s_to) for n in st.field_notes(p.id)] == \
        [(n.s_from, n.s_to) for n in before[2]]
    assert [q.vertices for q in st.pieces(st.current_version().id, p.id)] == \
        [q.vertices for q in before[3]]


def test_move_carries_the_pins_of_a_file_fitted_to_the_line(populated):
    from groundwork_geophysics.core.model import Dataset
    st, p, _ = populated
    opts = {"placement": {"zero": 0.0, "direction": 1, "pins": [[0.0, 0.0], [98.0, 100.0]]}}
    st.save_dataset(Dataset("g1", p.id, "", "gpr_section", "a.dzt", 0.0, "", "gssi_dzt", opts,
                            {}, name="radar"))
    st.move_profile_line(p.id, np.array([[-20.0, 0.0], [100.0, 0.0]]))   # starts 20 m earlier
    [d] = st.datasets(p.id)
    pins = d.reader_options["placement"]["pins"]
    assert [a for a, _b in pins] == [0.0, 98.0]
    assert [b for _a, b in pins] == pytest.approx([20.0, 120.0], abs=0.1)
