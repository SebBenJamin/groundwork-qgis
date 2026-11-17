"""The Groundwork menu opens the borehole viewer for the profile open in the section panel."""


def test_menu_opens_the_borehole_viewer(qgis_app, store_with_model, fake_iface):
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from groundwork_geophysics.plugin import WorkbenchPlugin
    from groundwork_geophysics.section.borehole_viewer import NO_BOREHOLES

    st, p, _ = store_with_model
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        action = plugin.viewer_action
        texts = [a.text() for a in plugin.menu.actions()]
        assert texts.index("Show Borehole Viewer") == texts.index("Show Section Panel") + 1
        assert not action.isEnabled()
        assert action.toolTip() == "Open a profile in the section panel first"
        plugin.set_store(st)
        plugin.show_section_panel()
        plugin.dock.open_profile(p.id)
        assert action.isEnabled()
        action.trigger()
        viewer = plugin.borehole_viewer
        assert viewer is not None and viewer.isVisible()
        assert viewer.profile_id == p.id and viewer.highlight is None
        assert viewer.canvas.empty_hint() == NO_BOREHOLES     # this profile has none
        action.trigger()                                      # one window, raised again
        assert plugin.borehole_viewer is viewer
    finally:
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()
