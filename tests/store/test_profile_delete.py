"""Usability round 1, Task 10 (D2): rename and delete profiles in the workbench store."""
import pytest


def _with_content(st, p):
    from geophysics_workbench.core.field_notes import FieldNote
    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id
    st.ensure_interpretation()
    v = st.current_version()
    f = InterpFeature(new_id(), v.id, type="clay", name="A")
    st.save_feature(f)
    st.save_piece(InterpPiece(new_id(), v.id, f.id, p.id, "line", [(1.0, -1.0), (5.0, -2.0)]))
    st.save_field_note(FieldNote("n1", p.id, 2.0, None, "fence"))
    return v


def test_rename_profile(store_with_model):
    st, p, _ = store_with_model
    st.rename_profile(p.id, "  Line A  ")
    assert st.profile(p.id).name == "Line A"
    with pytest.raises(ValueError, match="empty"):
        st.rename_profile(p.id, "  ")


def test_rename_refuses_duplicate(store_with_model):
    from geophysics_workbench.core.model import Profile
    st, p, _ = store_with_model
    other = Profile("p2", "Line B", p.xy + 100.0, st.crs_authid)
    st.save_profile(other)
    with pytest.raises(ValueError, match="already"):
        st.rename_profile(p.id, "line b")


def test_delete_profile_counts_and_rows(store_with_model):
    st, p, _ = store_with_model
    v = _with_content(st, p)
    before = st.profile_contents(p.id)
    assert before["datasets"] == len(st.datasets(p.id)) and before["pieces"] == 1
    assert before["notes"] == 1 and before["stations"] > 0
    counts = st.delete_profile(p.id)
    assert counts == before
    assert all(q.id != p.id for q in st.profiles())
    assert st.datasets(p.id) == [] and st.station_sets(p.id) == []
    assert st.pieces(v.id, p.id) == [] and st.field_notes(p.id) == []


def test_delete_keeps_files_and_frozen_versions(store_with_model):
    import os
    st, p, _ = store_with_model
    _with_content(st, p)
    frozen = st.freeze_current("delivered")
    paths = [os.path.join(os.path.dirname(st.path), d.source_path) for d in st.datasets(p.id)]
    st.delete_profile(p.id)
    assert all(os.path.exists(path) for path in paths)            # files never touched
    assert len(st.pieces(frozen.id, p.id)) == 1                   # the delivered record stays
