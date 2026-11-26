"""Section-panel test helpers: dock factories that always detach and unregister the profile
source on teardown (``fake_iface`` lives in tests/conftest.py)."""
import pytest


@pytest.fixture
def make_dock(qgis_app):
    """Factory: ``make_dock(store) -> SectionDock`` with a registered source, shown at a
    usable size. Teardown detaches the canvas, unregisters the source, deletes the dock."""
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.dock import SectionDock
    from groundwork_geophysics.section.profile_source import register_source, unregister_source

    made = []

    def factory(store, parent=None):
        provider = SectionDataProvider(store)
        source = register_source(provider)
        dock = SectionDock(parent)
        dock.set_provider(provider, source)
        dock.resize(1100, 520)
        dock.show()
        qgis_app.processEvents()
        made.append((dock, source))
        return dock

    yield factory
    for dock, source in made:
        dock.set_provider(None)
        unregister_source(source)
        dock.close()
        dock.deleteLater()
    qgis_app.processEvents()


def trace_amplitudes():
    """11 traces x 50 samples, signed (the trace-layer fixtures' section)."""
    import numpy as np
    return np.sin(np.arange(11 * 50, dtype=np.float32) / 3.0).reshape(11, 50)


@pytest.fixture(scope="session")
def make_trace_layer():
    """Factory: ``make_trace_layer(amplitudes=None, x=None, z_top=500.0, domain="time",
    level_cache=None, **style) -> SectionLayer``: a reflection section built in memory (no
    file), 1 ms (or 1 m) samples, 2000 m/s, traces 10 m apart from 0 m unless ``x`` is
    given; the colour scale as the provider would set it."""
    import numpy as np

    from groundwork_geophysics.core.model import Dataset
    from groundwork_geophysics.core.trace_section import TraceSection, Velocity, place
    from groundwork_geophysics.section.data import LayerStyle, SectionLayer, _trace_scale

    def factory(amplitudes=None, x=None, z_top=500.0, domain="time", level_cache=None,
                did="s1", **style):
        a = trace_amplitudes() if amplitudes is None else amplitudes
        x = np.arange(a.shape[0]) * 10.0 if x is None else x
        step = 0.001 if domain == "time" else 1.0
        section = TraceSection(a, x, 0.0, step, domain, numbers=np.arange(1, a.shape[0] + 1))
        placed = place(section, z_top, Velocity(2000.0) if domain == "time" else None)
        ds = Dataset(did, "p1", "", "refl_section", "line.sgy", 0.0, "", "segy", {}, {},
                     name="Line 1")
        st = LayerStyle(**style)
        if st.scale is None:
            st.scale = _trace_scale(placed, st)
        return SectionLayer(ds, None, st, None, placed, level_cache=level_cache)
    return factory


@pytest.fixture
def trace_layer(make_trace_layer):
    """The 11 x 50 signed section at a datum of 500 m, traces 0 .. 100 m."""
    return make_trace_layer()


@pytest.fixture
def make_dock_and_link(make_dock, fake_iface):
    """Factory: ``make_dock_and_link(store) -> (dock, MapLink)``; the map canvas uses the
    store CRS and shows the store's profiles."""
    from qgis.core import QgsCoordinateReferenceSystem, QgsRectangle

    from groundwork_geophysics.section.map_link import MapLink

    links = []

    def factory(store):
        dock = make_dock(store, fake_iface.mainWindow())
        canvas = fake_iface.mapCanvas()
        canvas.setDestinationCrs(QgsCoordinateReferenceSystem(store.crs_authid))
        canvas.setExtent(QgsRectangle(-25, -50, 75, 50))
        canvas.refresh()
        link = MapLink(fake_iface, dock)
        links.append(link)
        return dock, link

    yield factory
    for link in links:
        link.unload()
