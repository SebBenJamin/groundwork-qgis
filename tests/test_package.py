def test_package_imports_without_qgis_side_effects():
    import sys
    import geophysics_workbench
    assert hasattr(geophysics_workbench, "classFactory")
    assert "geophysics_workbench.plugin" not in sys.modules


def test_metadata_targets_qgis4():
    from configparser import ConfigParser
    from pathlib import Path
    cp = ConfigParser()
    cp.read(Path("geophysics_workbench/metadata.txt"), encoding="utf-8")
    g = cp["general"]
    assert g["name"] == "Geophysics Workbench"
    assert g["qgisMinimumVersion"] == "4.2"
    assert g["supportsQt6"] == "True"
    assert g["version"] == "0.1.0"


def test_plugin_loads_and_unloads(qgis_app):
    from qgis.testing.mocked import get_iface
    from geophysics_workbench import classFactory
    p = classFactory(get_iface())
    p.initGui()
    p.unload()


def test_add_action_adds_to_menu(qgis_app):
    from qgis.testing.mocked import get_iface
    from geophysics_workbench import classFactory
    p = classFactory(get_iface())
    p.initGui()
    hits = []
    a = p.add_action("Do thing", lambda: hits.append(1), icon="workbench.svg", checkable=True)
    assert a in p.menu.actions() and a.isCheckable() and not a.icon().isNull()
    a.trigger()
    assert hits == [1]
    p.unload()
