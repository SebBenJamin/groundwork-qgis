"""The section's model reads are remembered beside the project: a second opening takes them
from the cache folder, a changed file or line reads again, and no cache is ever needed."""
import os

import numpy as np
import pytest

from tests.section.test_placement_resolve import _map_points, _map_profile


@pytest.fixture
def counted(monkeypatch):
    """Counts the real file reads (``readers.read``)."""
    from groundwork_geophysics import readers
    calls = []
    real = readers.read

    def read(*a, **k):
        calls.append(a[0])
        return real(*a, **k)
    monkeypatch.setattr(readers, "read", read)
    return calls


def _values(provider, pid):
    return provider.layers(pid)[0].mesh.values.copy()


def test_a_second_provider_reads_from_the_cache(qgis_app, store_with_model, counted):
    from groundwork_geophysics.section.data import SectionDataProvider, cache_folder

    st, p, _src = store_with_model
    first = _values(SectionDataProvider(st), p.id)
    assert len(counted) == 1
    assert len(list(cache_folder(st).glob("d1-*.npz"))) == 1
    again = _values(SectionDataProvider(st), p.id)
    assert len(counted) == 1                      # no second file read
    np.testing.assert_array_equal(first, again)


def test_a_changed_file_is_read_again(qgis_app, store_with_model, counted):
    from groundwork_geophysics.section.data import SectionDataProvider, cache_folder

    st, p, src = store_with_model
    _values(SectionDataProvider(st), p.id)
    t = os.stat(src).st_mtime + 60
    os.utime(src, (t, t))
    _values(SectionDataProvider(st), p.id)
    assert len(counted) == 2
    assert len(list(cache_folder(st).glob("d1-*.npz"))) == 1     # the old one is gone


def test_a_new_line_reads_a_map_file_again(qgis_app, tmp_path, counted):
    from groundwork_geophysics.section.data import SectionDataProvider

    pts = _map_points()
    st, p, _d = _map_profile(tmp_path, pts[-1])
    _values(SectionDataProvider(st), p.id)
    p.xy = np.array([pts[len(pts) // 2], pts[-1]])
    st.save_profile(p)
    _values(SectionDataProvider(st), p.id)
    assert len(counted) == 2


def test_an_unwritable_cache_is_skipped(qgis_app, store_with_model, counted):
    from groundwork_geophysics.section.data import SectionDataProvider, cache_folder

    st, p, _src = store_with_model
    cache_folder(st).write_text("a file where the folder should be")
    assert _values(SectionDataProvider(st), p.id).size > 0
    assert _values(SectionDataProvider(st), p.id).size > 0
    assert len(counted) == 2                      # read from the file both times
