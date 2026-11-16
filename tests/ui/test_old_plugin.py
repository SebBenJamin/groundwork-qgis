"""A warning when the old Geophysics Workbench plugin is still installed."""
import pytest

from groundwork_geophysics.ids import LEGACY_ID, LEGACY_NAME

SETTING = f"PythonPlugins/{LEGACY_ID}"


@pytest.fixture
def old_state(monkeypatch):
    """Neither loaded nor enabled; the QGIS setting is restored afterwards."""
    import qgis.utils
    from qgis.core import QgsSettings

    monkeypatch.setattr(qgis.utils, "active_plugins", [], raising=False)
    monkeypatch.setattr(qgis.utils, "available_plugins", [LEGACY_ID], raising=False)
    settings = QgsSettings()
    before = settings.value(SETTING, None)
    settings.remove(SETTING)
    yield settings
    if before is None:
        settings.remove(SETTING)
    else:
        settings.setValue(SETTING, before)


def _warnings(iface):
    from qgis.core import Qgis
    return [item.text() for item in iface.messageBar().items()
            if item.level() == Qgis.MessageLevel.Warning]


def _start(iface):
    from groundwork_geophysics.plugin import WorkbenchPlugin
    plugin = WorkbenchPlugin(iface)
    plugin.initGui()
    return plugin


def test_no_old_plugin_no_warning(fake_iface, old_state):
    plugin = _start(fake_iface)
    try:
        assert not [t for t in _warnings(fake_iface) if LEGACY_NAME in t]
    finally:
        plugin.unload()


def test_old_plugin_loaded_warns(fake_iface, old_state, monkeypatch):
    import qgis.utils

    from groundwork_geophysics.ui.old_plugin import OLD_PLUGIN_WARNING
    monkeypatch.setattr(qgis.utils, "active_plugins", [LEGACY_ID], raising=False)
    plugin = _start(fake_iface)
    try:
        assert _warnings(fake_iface) == [OLD_PLUGIN_WARNING]
    finally:
        plugin.unload()


def test_enabled_setting_without_installed_plugin_does_not_warn(fake_iface, old_state,
                                                                 monkeypatch):
    import qgis.utils
    monkeypatch.setattr(qgis.utils, "available_plugins", [], raising=False)
    old_state.setValue(SETTING, True)
    plugin = _start(fake_iface)
    try:
        assert not [t for t in _warnings(fake_iface) if LEGACY_NAME in t]
    finally:
        plugin.unload()


def test_old_plugin_enabled_later_warns(fake_iface, old_state):
    from groundwork_geophysics.ui.old_plugin import OLD_PLUGIN_WARNING
    old_state.setValue(SETTING, True)
    plugin = _start(fake_iface)
    try:
        assert _warnings(fake_iface) == [OLD_PLUGIN_WARNING]
    finally:
        plugin.unload()


def test_warning_text():
    from groundwork_geophysics.ui.old_plugin import OLD_PLUGIN_WARNING
    assert OLD_PLUGIN_WARNING == (
        "The old plugin “Geophysics Workbench” is still installed. Groundwork replaces "
        "it, and both add the same menus and section tools: uninstall it in Plugins → "
        "Manage and Install Plugins, then restart QGIS.")


def test_starts_after_old_source_registered(fake_iface, old_state, project_store):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.profile_source import (register_source,
                                                              unregister_source)
    store, _prj = project_store
    old = register_source(SectionDataProvider(store))      # as the old plugin would
    plugin = None
    try:
        plugin = _start(fake_iface)
        plugin.show_section_panel()
        plugin.unload()
        plugin = None
    finally:
        if plugin is not None:
            plugin.unload()
        unregister_source(old)
