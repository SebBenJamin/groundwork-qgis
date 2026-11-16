"""Geophysics Workbench - QGIS plugin for georeferenced geophysical profiles and sections."""


def _drop_stale_modules() -> None:
    """Installing a new version while QGIS runs re-imports this package, but QGIS can keep
    the old version's other modules loaded; the new code would then meet old modules
    (initGui failed with a missing function). A submodule imported under an earlier copy of
    this package is not an attribute of this one: then all submodules are leftovers and
    are dropped, so everything imports fresh."""
    import sys
    package = sys.modules.get(__name__)
    prefix = f"{__name__}."
    stale = [n for n in sys.modules if n.startswith(prefix) and "." not in n[len(prefix):]
             and getattr(package, n[len(prefix):], None) is not sys.modules[n]]
    if not stale:
        return
    for name in [n for n in sys.modules if n.startswith(prefix)]:
        del sys.modules[name]


def classFactory(iface):
    """QGIS entry point. Imported lazily so this package has no QGIS import side effects."""
    _drop_stale_modules()
    from .plugin import WorkbenchPlugin

    return WorkbenchPlugin(iface)
