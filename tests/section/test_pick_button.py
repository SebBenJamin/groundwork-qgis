"""Usability round 1, Task 11 (D3): Pick Profile on Map from the panel."""
import pytest


@pytest.fixture
def plugin(qgis_app, fake_iface, store_with_model):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from groundwork_geophysics import classFactory
    st, p, _ = store_with_model
    QgsProject.instance().clear()
    plug = classFactory(fake_iface)
    plug.initGui()
    plug.set_store(st)
    yield plug
    plug.unload()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
    qgis_app.processEvents()
    QgsProject.instance().removeAllMapLayers()
    QgsProject.instance().clear()


def test_pick_button_next_to_profile_list(plugin):
    button = plugin.dock.pick_button
    assert button.defaultAction() is plugin.pick_action
    assert button.isCheckable() or button.defaultAction().isCheckable()
    assert button.toolTip() == "Pick a profile on the map"
    assert not button.icon().isNull()
    from qgis.PyQt.QtWidgets import QHBoxLayout
    top = next(lay for lay in plugin.dock.findChildren(QHBoxLayout)
               if lay.indexOf(plugin.dock.profile_combo) >= 0)
    assert top.indexOf(button) == top.indexOf(plugin.dock.profile_combo) + 1


def test_empty_hint_link_starts_pick(plugin):
    dock = plugin.dock
    assert "<a " in dock.empty_hint.text() and "pick one on the map" in dock.empty_hint.text()
    dock.empty_hint.linkActivated.emit("pick")
    assert plugin.pick_action.isChecked()
