"""Geophysics Workbench - QGIS plugin for georeferenced geophysical profiles and sections."""


def classFactory(iface):
    """QGIS entry point. Imported lazily so this package has no QGIS import side effects."""
    from .plugin import WorkbenchPlugin

    return WorkbenchPlugin(iface)
