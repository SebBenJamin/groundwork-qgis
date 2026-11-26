"""Model reads as plain jobs: listed on the main thread, run in one QGIS task, handed back
on the main thread."""
import numpy as np
import pytest

from tests.section.test_read_cache_use import counted  # noqa: F401  (fixture)

pytestmark = pytest.mark.background_reads


def _wait(qgis_app, flag, seconds=30.0):
    import time
    end = time.perf_counter() + seconds
    while not flag() and time.perf_counter() < end:
        qgis_app.processEvents()
        time.sleep(0.01)
    assert flag(), "the reading task did not finish"


def _second_profile(st, src, name="P2"):
    from groundwork_geophysics.core.model import Dataset, file_fingerprint, profile_from_stations
    q, s = profile_from_stations(name, "EPSG:25832", np.array([[0, 10, 100], [50, 10, 102.0]]))
    st.save_profile(q)
    st.save_station_set(s)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset(f"d{name}", q.id, s.id, "ert_model", str(src), mt, sha,
                            "r2_res_dat", {"z_kind": "elevation"}, {}, name=f"{name} model"))
    return q


def test_unread_lists_what_is_not_in_memory(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    st, p, _src = store_with_model
    provider = SectionDataProvider(st)
    [job] = provider.unread([p.id])
    assert job.dataset_id == "d1" and job.profile_name == "P1"
    provider.layers(p.id)
    assert provider.unread([p.id]) == []


def test_take_makes_the_read_instant(qgis_app, store_with_model, counted):  # noqa: F811
    from groundwork_geophysics.section.data import SectionDataProvider, run_job
    st, p, _src = store_with_model
    provider = SectionDataProvider(st)
    [job] = provider.unread([p.id])
    provider.take(job, run_job(job))
    assert len(counted) == 1
    provider.layers(p.id)
    assert len(counted) == 1


def test_request_reads_in_a_task_then_calls_done(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.model_reading import ModelReader
    st, p, _src = store_with_model
    provider = SectionDataProvider(st)
    reader = ModelReader(provider)
    got = []
    assert reader.request([p.id], got.append)
    assert reader.busy
    _wait(qgis_app, lambda: got)
    assert got == [True] and provider.unread([p.id]) == [] and not reader.busy
    assert not reader.request([p.id], got.append)         # nothing left to read
    assert got == [True]


def test_two_requests_share_one_task(qgis_app, store_with_model, counted):  # noqa: F811
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.model_reading import ModelReader
    st, p, src = store_with_model
    q = _second_profile(st, src)
    provider = SectionDataProvider(st)
    reader = ModelReader(provider)
    got = []
    assert reader.request([p.id], lambda ok: got.append(("p", ok)))
    assert reader.request([p.id, q.id], lambda ok: got.append(("pq", ok)))
    _wait(qgis_app, lambda: len(got) == 2)
    assert got == [("p", True), ("pq", True)]
    assert sorted(counted) == sorted([str(src), str(src)])   # each dataset read once


def test_cancel_keeps_nothing_half_read(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.model_reading import ModelReader
    st, p, _src = store_with_model
    provider = SectionDataProvider(st)
    reader = ModelReader(provider)
    got = []
    reader.request([p.id], got.append)
    reader.cancel()
    _wait(qgis_app, lambda: got)
    assert got in ([False], [True])         # cancelled, or done before the cancel arrived
    if got == [False]:
        assert [j.dataset_id for j in provider.unread([p.id])] == ["d1"]
