"""Ties to crossing profiles never wait for those profiles' models: a crossing profile not
read yet is tied without columns, its models are asked for, and the full tie comes once they
are in. Plates always read everything."""
import numpy as np

from groundwork_geophysics.core.model import Dataset, file_fingerprint, profile_from_stations


def _crossing(st, src):
    """A second profile crossing P1 (x 0..50 at y 0) at x 25, with its own model."""
    q, s = profile_from_stations("Q", "EPSG:25832",
                                 np.array([[25, -25, 101], [25, 25, 101.0]]))
    st.save_profile(q)
    st.save_station_set(s)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("dQ", q.id, s.id, "ert_model", str(src), mt, sha, "r2_res_dat",
                            {"z_kind": "elevation"}, {}, name="Q model"))
    return q


def test_unread_crossing_profiles_are_tied_later(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider, run_job
    st, p, src = store_with_model
    q = _crossing(st, src)
    provider = SectionDataProvider(st)
    asked = []
    provider.on_unread_ties = asked.extend
    [tie] = provider.ties(p.id)
    assert tie.other_id == q.id and tie.columns == [] and asked == [q.id]
    for job in provider.unread([q.id]):
        provider.take(job, run_job(job))
    [tie] = provider.ties(p.id)                     # the partial ties were not kept
    assert tie.columns


def test_plate_snapshots_read_crossings_fully(qgis_app, store_with_model):
    from groundwork_geophysics.core.plates import FrameLook, ModelLook
    from groundwork_geophysics.section.data import SectionDataProvider
    st, p, src = store_with_model
    _crossing(st, src)
    provider = SectionDataProvider(st)
    provider.on_unread_ties = lambda ids: None
    snap = provider.snapshot(p.id, look=FrameLook([ModelLook("d1")]))
    assert [len(t.columns) > 0 for t in snap.context.ties] == [True]
