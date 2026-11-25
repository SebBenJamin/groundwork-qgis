"""The section panel reads a profile's models in the background: it says so, and draws the
profile when they are in."""
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


def test_opening_a_profile_reads_in_the_background(qgis_app, reading_dock):
    from groundwork_geophysics.section.dock import READING
    dock, _st, p, _src = reading_dock
    assert dock.open_profile(p.id)
    assert dock.readout.text() == READING.format(name="P1", done=0, total=1)
    assert dock.current_profile_id() is None             # not drawn before it is read
    _wait(qgis_app, lambda: dock.current_profile_id() == p.id)
    assert list(dock.layer_list._rows) == ["d1"]


def test_switching_profile_while_reading(qgis_app, reading_dock):
    dock, st, p, src = reading_dock
    q = _second_profile(st, src)
    dock.provider.notify_changed()
    dock.open_profile(p.id)
    dock.open_profile(q.id)
    _wait(qgis_app, lambda: not dock.reader.busy)
    _wait(qgis_app, lambda: dock.current_profile_id() == q.id)
    assert "P1" not in dock.readout.text()
    assert dock.profile_combo.currentData() == q.id


def test_a_cancelled_read_says_so(qgis_app, reading_dock):
    from groundwork_geophysics.section.dock import READ_CANCELLED
    dock, _st, p, _src = reading_dock
    dock.open_profile(p.id)
    dock.reader.cancel()
    _wait(qgis_app, lambda: not dock.reader.busy)
    if dock.current_profile_id() is None:                # the cancel came in time
        assert dock.readout.text() == READ_CANCELLED


def test_a_file_that_fails_is_not_read_again_and_again(qgis_app, reading_dock, monkeypatch):
    """A read that fails in the background is left to the section, which says why."""
    from groundwork_geophysics.section import data
    dock, _st, p, _src = reading_dock

    def broken(*_a, **_k):
        raise ValueError("not a model file")
    monkeypatch.setattr(data.readers, "read", broken)
    dock.open_profile(p.id)
    _wait(qgis_app, lambda: dock.current_profile_id() == p.id)
    assert not dock.reader.request([p.id], lambda ok: None)
    assert "not a model file" in dock.errors.text()
