"""QGIS 4.2 behaviour the plugin relies on when it unregisters its profile source.

Every QgsElevationProfileCanvas (QGIS's own Elevation Profile tool included) adds a source
when it is registered with the profile source registry and drops it again when it is
unregistered. So unregistering on unload / project change leaves no canvas with a dangling
pointer, even canvases the plugin does not own. Checked against a real QGIS 4.2.3 session
in the 0.1.0 release test; this test fails if QGIS ever stops doing it.
"""
import numpy as np


def _wait(qgis_app, seconds):
    from qgis.PyQt.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(int(seconds * 1000), loop.quit)
    loop.exec()


def test_foreign_profile_canvas_follows_registry(qgis_app, store_with_model):
    from qgis.core import QgsCoordinateReferenceSystem, QgsLineString, QgsPoint, QgsProject
    from qgis.gui import QgsElevationProfileCanvas
    from qgis.PyQt import sip

    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.profile_source import register_source, unregister_source

    st, p, _ = store_with_model
    foreign = QgsElevationProfileCanvas()            # stands in for QGIS's Elevation Profile
    foreign.setProject(QgsProject.instance())
    foreign.resize(600, 300)
    foreign.show()
    foreign.setCrs(QgsCoordinateReferenceSystem(st.crs_authid))
    foreign.setProfileCurve(QgsLineString([QgsPoint(float(x), float(y)) for x, y in p.xy]))
    addresses = lambda: [sip.unwrapinstance(s) for s in foreign.sources()]   # noqa: E731
    try:
        source = register_source(SectionDataProvider(st))
        addr = sip.unwrapinstance(source)
        assert addr in addresses()                   # picked up without our help
        foreign.refresh()
        _wait(qgis_app, 1.0)
        assert source.last_results is not None       # and it generated our section

        unregister_source(source)                    # destroys the source
        assert addr not in addresses()               # the canvas let go of it
        foreign.refresh()                            # regenerating must not touch it
        _wait(qgis_app, 1.0)

        again = register_source(SectionDataProvider(st))      # e.g. plugin reloaded
        addr2 = sip.unwrapinstance(again)
        assert addresses().count(addr2) == 1
        unregister_source(again)
        assert np.isin(addresses(), [addr, addr2]).sum() == 0
    finally:
        foreign.setSources([])
        foreign.close()
        foreign.deleteLater()
        qgis_app.processEvents()
