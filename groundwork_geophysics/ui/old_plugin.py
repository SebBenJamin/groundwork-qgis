"""Detect the old plugin, which adds the same menus and section tools."""
from ..ids import LEGACY_ID, LEGACY_NAME, NAME

OLD_PLUGIN_WARNING = (f"The old plugin “{LEGACY_NAME}” is still installed. {NAME} replaces "
                      "it, and both add the same menus and section tools: uninstall it in "
                      "Plugins → Manage and Install Plugins.")


def old_plugin_present() -> bool:
    """True when the old plugin is loaded, or enabled in the QGIS settings (it may load later)."""
    import qgis.utils
    from qgis.core import QgsSettings
    if LEGACY_ID in getattr(qgis.utils, "active_plugins", []):
        return True
    return QgsSettings().value(f"PythonPlugins/{LEGACY_ID}", False, type=bool)
