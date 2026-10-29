"""Section-panel test helpers: a minimal iface with a real QgsMapCanvas and dock factories
that always detach and unregister the profile source on teardown."""
import pytest


class FakeIface:
    """Just enough of QgisInterface for the section dock, map link and plugin."""

    def __init__(self):
        from qgis.gui import QgsMapCanvas
        from qgis.PyQt.QtWidgets import QMainWindow

        self._window = QMainWindow()
        self._window.resize(1200, 800)
        self._canvas = QgsMapCanvas(self._window)
        self._window.setCentralWidget(self._canvas)
        self._window.show()

    def mainWindow(self):
        return self._window

    def mapCanvas(self):
        return self._canvas

    def addDockWidget(self, area, dock):
        self._window.addDockWidget(area, dock)

    def removeDockWidget(self, dock):
        self._window.removeDockWidget(dock)


@pytest.fixture
def fake_iface(qgis_app):
    iface = FakeIface()
    yield iface
    iface.mainWindow().close()
    iface.mainWindow().deleteLater()
    qgis_app.processEvents()


@pytest.fixture
def make_dock(qgis_app):
    """Factory: ``make_dock(store) -> SectionDock`` with a registered source, shown at a
    usable size. Teardown detaches the canvas, unregisters the source, deletes the dock."""
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.section.dock import SectionDock
    from geophysics_workbench.section.profile_source import register_source, unregister_source

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


@pytest.fixture
def make_dock_and_link(make_dock, fake_iface):
    """Factory: ``make_dock_and_link(store) -> (dock, MapLink)``; the map canvas uses the
    store CRS and shows the store's profiles."""
    from qgis.core import QgsCoordinateReferenceSystem, QgsRectangle

    from geophysics_workbench.section.map_link import MapLink

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
