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
    assert _topo_texts(dock) == [("Stations", "stations", True), ("DEM", "dem", True)]
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
    assert dock.topo_combo.currentData() == "dem"
    assert _topo_texts(dock)[1] == ("DEM", "dem", False)


def test_readout_lists_context_lines(store_with_model, make_dock):
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.provider.context_source = lambda profile: _items()
    dock.open_profile(p.id)
    dock._show_readout(25.0, 100.0)
    lines = dock.readout.text().split("\n")
    assert lines[1].startswith("Surface geology: Talsand")
    assert "DEM 99.0 m (stations " in lines[1]
