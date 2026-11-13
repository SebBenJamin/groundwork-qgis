"""The Topography combo next to the profile combo, and context lines in the dock readout."""
import numpy as np
import pytest

from geophysics_workbench.core.context import BandSegment, ContextItems


def _items(with_dem=True):
    s = np.linspace(0.0, 50.0, 11)
    return ContextItems(band=[BandSegment(0.0, 50.0, "Talsand")],
                        dem=(s, np.full(11, 99.0)) if with_dem else None)


def _topo_texts(dock):
    combo = dock.topo_combo
    return [(combo.itemText(i), combo.itemData(i), combo.model().item(i).isEnabled())
            for i in range(combo.count())]


def test_topo_switch_saves_metadata_and_refreshes(store_with_model, make_dock, qgis_app):
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.provider.context_source = lambda profile: _items()
    dock.open_profile(p.id)
    assert _topo_texts(dock) == [("Stations", "stations", True), ("DEM", "dem", True),
                                 ("Local", "local", False)]       # only for no heights
    assert dock.topo_combo.currentData() == "stations"
    changes = []
    dock.provider.on_change.append(lambda: changes.append(1))
    dock.topo_combo.setCurrentIndex(1)
    assert st.profile(p.id).metadata["topography"] == "dem"
    assert changes
    qgis_app.processEvents()
    assert dock.topo_combo.currentData() == "dem"
    dock.topo_combo.setCurrentIndex(0)
    assert st.profile(p.id).metadata["topography"] == "stations"


def test_topo_combo_reflects_saved_choice_and_disables_missing_dem(store_with_model, make_dock):
    st, p, _ = store_with_model
    prof = st.profile(p.id)
    prof.metadata["topography"] = "dem"
    st.save_profile(prof)
    dock = make_dock(st)
    dock.provider.context_source = lambda profile: _items(with_dem=False)
    dock.open_profile(p.id)
    assert _topo_texts(dock)[1] == ("DEM", "dem", False)
    # R19d: saved "dem" without DEM data shows what is used, the stations; the saved
    # choice is kept and the DEM shows again once it has data
    assert dock.topo_combo.currentData() == "stations"
    assert st.profile(p.id).metadata["topography"] == "dem"
    dock.provider.context_source = lambda profile: _items()
    dock.topo.sync()
    assert dock.topo_combo.currentData() == "dem"
    assert _topo_texts(dock)[1] == ("DEM", "dem", True)


def test_readout_lists_context_lines(store_with_model, make_dock):
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.provider.context_source = lambda profile: _items()
    dock.open_profile(p.id)
    dock._show_readout(25.0, 100.0)
    lines = dock.readout.text().split("\n")
    assert lines[1].startswith("Surface geology: Talsand")
    assert "DEM 99.0 m (stations " in lines[1]


def test_switch_fires_once_per_user_change_not_on_sync(store_with_model, make_dock, qgis_app):
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.provider.context_source = lambda profile: _items()
    dock.open_profile(p.id)
    calls = []
    real = dock.provider.set_topography_source
    dock.provider.set_topography_source = lambda pid, src: (calls.append((pid, src)), real(pid, src))
    dock.topo.sync()
    dock.topo.sync()
    assert calls == []
    dock.topo_combo.setCurrentIndex(1)
    assert calls == [(p.id, "dem")]
    qgis_app.processEvents()
    dock.topo.sync()
    assert calls == [(p.id, "dem")]


def test_readout_does_not_read_the_store_per_mouse_move(store_with_model, make_dock, qgis_app):
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.provider.context_source = lambda profile: _items()
    dock.open_profile(p.id)
    qgis_app.processEvents()
    dock._show_readout(25.0, 100.0)                     # fills the caches
    counts = {"profile": 0, "station_sets": 0}
    for name in counts:
        real = getattr(st, name)
        setattr(st, name, lambda *a, _r=real, _n=name, **k: (counts.__setitem__(_n, counts[_n] + 1),
                                                           _r(*a, **k))[1])
    for s in (10.0, 20.0, 30.0, 40.0):
        dock._show_readout(s, 100.0)
    assert counts == {"profile": 0, "station_sets": 0}
    dock._refresh_now()                                 # a refresh re-reads, then it is cached again
    dock._show_readout(25.0, 100.0)
    after = dict(counts)
    dock._show_readout(26.0, 100.0)
    assert counts == after
