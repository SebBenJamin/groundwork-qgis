"""Cheap redraws keep the gathered context; profiles without station heights use the DEM."""
import numpy as np

from geophysics_workbench.core.context import ContextItems


def _dem_items():
    s = np.linspace(0.0, 50.0, 11)
    return ContextItems(dem=(s, np.full(11, 99.0)))


def _provider(store, calls, items=_dem_items):
    from geophysics_workbench.section.data import SectionDataProvider
    prov = SectionDataProvider(store)
    prov.context_source = lambda profile: (calls.append(profile.id), items())[1]
    return prov


def test_set_style_keeps_gathered_context(store_with_model):
    st, p, _ = store_with_model
    calls = []
    prov = _provider(st, calls)
    prov.context(p.id)
    n = len(calls)
    prov.set_style("d1", prov.style("d1"))
    prov.context(p.id)
    assert len(calls) == n
    prov.notify_redraw()
    prov.context(p.id)
    assert len(calls) == n
    prov.notify_changed()
    prov.context(p.id)
    assert len(calls) == n + 1


def test_notify_redraw_tells_listeners(store_with_model):
    st, _p, _ = store_with_model
    prov = _provider(st, [])
    seen = []
    prov.on_change.append(lambda: seen.append(1))
    prov.notify_redraw()
    assert seen == [1]


def _store_without_heights(tmp_path):
    from geophysics_workbench.core.model import profile_from_stations
    from geophysics_workbench.store.gpkg_store import ProjectStore
    st = ProjectStore.create(tmp_path / "n.gpkg", "EPSG:25832")
    p, s = profile_from_stations("P1", "EPSG:25832",
                                 np.array([[0, 0, np.nan], [50, 0, np.nan]]))
    st.save_profile(p)
    st.save_station_set(s)
    return st, p


def test_no_station_heights_falls_back_to_dem(tmp_path):
    st, p = _store_without_heights(tmp_path)
    prov = _provider(st, [])
    s, z = prov.topography(p.id)
    assert len(s) >= 2 and np.allclose(z, 99.0)


def test_no_heights_no_dem_gives_no_topography(tmp_path):
    st, p = _store_without_heights(tmp_path)
    prov = _provider(st, [], items=ContextItems)
    assert prov.topography(p.id) is None
