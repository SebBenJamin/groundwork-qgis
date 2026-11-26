"""What can happen while models or strips are read in the background (review of the
background-reading branch): every case a user can run into."""
import os
import threading

import pytest

from tests.section.test_model_reading import _second_profile, _wait

pytestmark = pytest.mark.background_reads


@pytest.fixture
def reading_dock(qgis_app, store_with_model, make_dock):
    from groundwork_geophysics.section.model_reading import ModelReader
    st, p, src = store_with_model
    dock = make_dock(st)
    dock.reader = ModelReader(dock.provider)
    return dock, st, p, src


# -- 1: callers act after the profile has opened ---------------------------------------------
def test_open_profile_calls_after_once_it_is_open(qgis_app, reading_dock):
    dock, _st, p, _src = reading_dock
    seen = []
    dock.open_profile(p.id, after=lambda: seen.append(dock.current_profile_id()))
    _wait(qgis_app, lambda: seen)
    assert seen == [p.id]
    dock.open_profile(p.id, after=lambda: seen.append("again"))    # read: at once
    assert seen == [p.id, "again"]


# -- 2: a refresh never drops the profile asked for meanwhile -------------------------------
def test_a_refresh_read_does_not_drop_a_profile_chosen_meanwhile(qgis_app, reading_dock):
    dock, st, p, src = reading_dock
    q = _second_profile(st, src)
    dock.provider.notify_changed()
    dock.open_profile(p.id)
    _wait(qgis_app, lambda: dock.current_profile_id() == p.id)
    t = os.stat(src).st_mtime + 60                      # the open profile's file changed
    os.utime(src, (t, t))
    dock.provider.notify_changed()
    dock._refresh_now()                                 # reads it again in the background
    dock.open_profile(q.id)                             # meanwhile the user picks Q
    _wait(qgis_app, lambda: not dock.reader.busy)
    _wait(qgis_app, lambda: dock.current_profile_id() == q.id)
    assert dock.profile_combo.currentData() == q.id


# -- 3: one unreadable model does not hide a crossing profile's other columns ---------------
def test_a_failed_read_does_not_keep_a_tie_waiting(qgis_app, store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider
    from tests.section.test_ties_reading import _crossing
    st, p, src = store_with_model
    q = _crossing(st, src)
    provider = SectionDataProvider(st)
    asked = []
    provider.on_unread_ties = asked.extend
    [job] = provider.unread([q.id])
    provider.mark_failed(job)                           # as a reading task reports it
    assert provider.unread([q.id]) == []
    [tie] = provider.ties(p.id)
    assert asked == [] and tie.columns                  # read here, as before


# -- 7: remembered reads end with the plugin version ---------------------------------------
def test_remembered_reads_belong_to_one_plugin_version(qgis_app, store_with_model,
                                                       monkeypatch):
    from groundwork_geophysics.section import data
    from groundwork_geophysics.section.data import SectionDataProvider
    st, p, _src = store_with_model
    [before] = SectionDataProvider(st).unread([p.id])
    monkeypatch.setattr(data, "_cache_version", lambda: "99.0.0/1")
    [after] = SectionDataProvider(st).unread([p.id])
    assert before.cache_file != after.cache_file


# -- minor: temporary files are never shared ------------------------------------------------
def test_two_writers_never_share_a_temporary_file(tmp_path, monkeypatch):
    from groundwork_geophysics.core import read_cache
    from tests.core.test_read_cache import _result
    names = []
    real = read_cache._temporary
    monkeypatch.setattr(read_cache, "_temporary", lambda path: names.append(real(path)) or names[-1])
    threads = [threading.Thread(target=read_cache.save_result, args=(tmp_path / "r.npz",
                                                                     _result()))
               for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(set(names)) == 2 and read_cache.load_result(tmp_path / "r.npz") is not None
