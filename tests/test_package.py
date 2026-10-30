def test_package_imports_without_qgis_side_effects():
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    code = ("import sys, geophysics_workbench; "
            "assert hasattr(geophysics_workbench, 'classFactory'); "
            "assert 'geophysics_workbench.plugin' not in sys.modules")
    r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_metadata_targets_qgis4():
    from configparser import ConfigParser
    from pathlib import Path
    cp = ConfigParser()
    cp.read(Path(__file__).resolve().parent.parent / "geophysics_workbench" / "metadata.txt", encoding="utf-8")
    g = cp["general"]
    assert g["name"] == "Geophysics Workbench"
    assert g["qgisMinimumVersion"] == "4.2"
    assert g["supportsQt6"] == "True"
    assert g["version"] == "0.1.1"


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
