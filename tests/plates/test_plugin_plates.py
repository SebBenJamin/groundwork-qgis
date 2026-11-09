"""The plugin re-attaches plate frames when the store is set (project read) and lets go on
unload."""


def test_plugin_attaches_frames_on_store_and_detaches_on_unload(qgis_app, fake_iface,
                                                               store_with_model):
    from qgis.core import QgsLayoutItemElevationProfile, QgsPrintLayout, QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench import classFactory
    from geophysics_workbench.core.plates import FrameLook, FrameSpec, PlateSpec
    from geophysics_workbench.plates.sources import write_plates
    st, p, _ = store_with_model
    prj = QgsProject.instance()
    prj.clear()
    write_plates(prj, [PlateSpec("pl", "1", "P1", "A4_landscape",
                                 [FrameSpec("f9", p.id, FrameLook())])])
    layout = QgsPrintLayout(prj)
    layout.setName("Plate 1 – P1")
    item = QgsLayoutItemElevationProfile(layout)
    item.setCustomProperty("wb_frame_id", "f9")
    layout.addLayoutItem(item)
    prj.layoutManager().addLayout(layout)
    plugin = classFactory(fake_iface)
    plugin.initGui()
    try:
        plugin.set_store(st)
        assert [s.profileSourceId() for s in item.sources()] == [
            "geophysics_workbench:frame:f9"]
    finally:
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()
    assert item.sources() == []
    prj.clear()


def test_plates_menu_entry_opens_dialog_with_store(qgis_app, fake_iface, store_with_model):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench import classFactory
    st, p, _ = store_with_model
    prj = QgsProject.instance()
    prj.clear()
    plugin = classFactory(fake_iface)
    plugin.initGui()
    try:
        action = next(a for a in plugin.actions if a.text() == "Plates…")
        assert not action.isEnabled()                     # no workbench project yet
        plugin.set_store(st)
        assert action.isEnabled()
        action.trigger()
        assert plugin._plates_dialog is not None and plugin._plates_dialog.isVisible()
    finally:
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()
    assert plugin._plates_dialog is None
    prj.removeAllMapLayers()
    prj.clear()


def test_plate_frames_never_reach_other_canvases(qgis_app, fake_iface, store_with_model):
    """Review C1: QGIS adds every registered source to every elevation-profile canvas, so the
    section panel drew the plate's profile over the open one. The panel keeps its own source
    only."""
    from qgis.core import QgsLayoutItemElevationProfile, QgsPrintLayout, QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench import classFactory
    from geophysics_workbench.core.plates import FrameLook, FrameSpec, PlateSpec
    from geophysics_workbench.plates.sources import write_plates
    st, p, _ = store_with_model
    prj = QgsProject.instance()
    prj.clear()
    write_plates(prj, [PlateSpec("pl", "1", "P1", "A4_landscape",
                                 [FrameSpec("f7", p.id, FrameLook())])])
    layout = QgsPrintLayout(prj)
    layout.setName("Plate 1 – P1")
    item = QgsLayoutItemElevationProfile(layout)
    item.setCustomProperty("wb_frame_id", "f7")
    layout.addLayoutItem(item)
    prj.layoutManager().addLayout(layout)
    plugin = classFactory(fake_iface)
    plugin.initGui()
    try:
        plugin.set_store(st)
        plugin.attach_plates()                                 # e.g. after Create
        assert [s.profileSourceId() for s in item.sources()] == [
            "geophysics_workbench:frame:f7"]
        assert [s.profileSourceId() for s in plugin.dock.canvas.sources()] == [
            plugin.source.profileSourceId()]
        dock_sources = [s.profileSourceId() for s in plugin.dock.canvas.sources()]
        assert dock_sources == [plugin.source.profileSourceId()]   # also after Create again
    finally:
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()
    prj.removeAllMapLayers()
    prj.clear()


def test_plugin_started_after_plates_were_read_warns(qgis_app, fake_iface, monkeypatch):
    """Review I6: QGIS drops item types it does not know while reading a project. When the
    plugin starts after a project with plates was read, it says to reopen the project
    before saving (else colour bars and borehole legends are lost)."""
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench import classFactory
    from geophysics_workbench.core.plates import FrameLook, FrameSpec, PlateSpec
    from geophysics_workbench.plates import items
    from geophysics_workbench.plates.sources import write_plates
    prj = QgsProject.instance()
    prj.clear()
    write_plates(prj, [PlateSpec("pl", "1", "P1", "A4_landscape",
                                 [FrameSpec("f1", "p", FrameLook())])])
    monkeypatch.setattr(items, "items_registered", lambda: False)
    plugin = classFactory(fake_iface)
    plugin.initGui()
    try:
        texts = [i.text() for i in fake_iface.messageBar().items()]
        assert any("reopen the project" in t for t in texts), texts
    finally:
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()
    prj.clear()


def test_no_warning_when_items_were_known(qgis_app, fake_iface):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench import classFactory
    prj = QgsProject.instance()
    prj.clear()
    plugin = classFactory(fake_iface)
    plugin.initGui()
    try:
        assert not any("reopen the project" in i.text()
                       for i in fake_iface.messageBar().items())
    finally:
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()
