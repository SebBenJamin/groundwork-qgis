"""Detect the old plugin, which adds the same menus and section tools."""
from ..ids import LEGACY_ID, LEGACY_NAME, NAME

OLD_PLUGIN_WARNING = (f"The old plugin “{LEGACY_NAME}” is still installed. {NAME} replaces "
                      "it, and both add the same menus and section tools: uninstall it in "
                      "Plugins → Manage and Install Plugins, then restart QGIS.")


def old_plugin_present() -> bool:
    """True when the old plugin is installed and loaded, or enabled in the QGIS settings.

    The enabled setting alone is not enough: QGIS clears it only when the plugin is uninstalled
    through the Plugin Manager, so it can outlive a plugin folder deleted by hand.
    """
    import qgis.utils
    from qgis.core import QgsSettings
    if LEGACY_ID not in getattr(qgis.utils, "available_plugins", []):
        return False
    if LEGACY_ID in getattr(qgis.utils, "active_plugins", []):
        return True
    return QgsSettings().value(f"PythonPlugins/{LEGACY_ID}", False, type=bool)
