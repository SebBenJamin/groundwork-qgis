"""Round 2, F4: boreholes hidden per profile live in the workbench store (the user's borehole
layer is never changed)."""
from groundwork_geophysics.core.model import Profile


def test_hide_and_show_roundtrip(store_with_model):
    st, p, _ = store_with_model
    assert st.hidden_boreholes(p.id) == set()
    st.set_boreholes_hidden(p.id, [("L1", "B1"), ("L1", "B2")], True)
    assert st.hidden_boreholes(p.id) == {("L1", "B1"), ("L1", "B2")}
    st.set_boreholes_hidden(p.id, [("L1", "B1")], True)             # again: no duplicate
    st.set_boreholes_hidden(p.id, [("L1", "B2")], False)
    assert st.hidden_boreholes(p.id) == {("L1", "B1")}


def test_hidden_per_profile(store_with_model):
    st, p, _ = store_with_model
    q = Profile("p2", "Line B", p.chainage.xy + 100.0, st.crs_authid)
    st.save_profile(q)
    st.set_boreholes_hidden(p.id, [("L1", "B1")], True)
    assert st.hidden_boreholes(q.id) == set()


def test_delete_profile_drops_hidden(store_with_model):
    st, p, _ = store_with_model
    st.set_boreholes_hidden(p.id, [("L1", "B1")], True)
    st.delete_profile(p.id)
    assert st.hidden_boreholes(p.id) == set()
