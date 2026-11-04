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
    assert g["version"] == "0.2.1"


def test_plugin_loads_and_unloads(fake_iface):
    from geophysics_workbench import classFactory
    p = classFactory(fake_iface)
    p.initGui()
    p.unload()


def test_add_action_adds_to_menu(fake_iface):
    from geophysics_workbench import classFactory
    p = classFactory(fake_iface)
    p.initGui()
    hits = []
    a = p.add_action("Do thing", lambda: hits.append(1), icon="workbench.svg", checkable=True)
    assert a in p.menu.actions() and a.isCheckable() and not a.icon().isNull()
    a.trigger()
    assert hits == [1]
    p.unload()


def test_package_builds_guelpe_demo_zip(tmp_path):
    import shutil
    import sys
    import zipfile
    from pathlib import Path

    import pytest
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "scripts"))
    import package

    zips = package.build(tmp_path)
    assert len(zips) == 3
    guelpe = zips[2]
    assert guelpe.name.startswith("geophysics_workbench-demo-guelpe-")
    names = zipfile.ZipFile(guelpe).namelist()
    for need in ("guelpe_project.qgz", "guelpe_workbench.gpkg", "ATTRIBUTION.md",
                 "context/cores.gpkg", "data/ert/T1/dcinv.result.vtk"):
        assert need in names
    assert not any(".cache" in n for n in names)
    copy = tmp_path / "copy"
    shutil.copytree(root / "demo_guelpe", copy)
    (copy / "guelpe_project.qgz").unlink()
    with pytest.raises(RuntimeError):
        package._demo_zip(copy, "x", "guelpe_project.qgz", tmp_path)
