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
    assert g["version"] == "0.5.1"


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


def test_zips_take_committed_content_of_modified_files(tmp_path):
    """Local edits (e.g. drawings made while testing in QGIS) never ship in a demo zip."""
    import subprocess
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import package

    assert package.GIT is not None, "git is needed to keep local edits out of the zips"

    def git(*args):
        subprocess.run([package.GIT, "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "a.gpkg").write_bytes(b"clean")
    git("add", "a.gpkg")
    git("commit", "-q", "-m", "a")
    (tmp_path / "a.gpkg").write_bytes(b"my test drawings")
    (tmp_path / "new.txt").write_bytes(b"untracked")
    assert package.entry_bytes(tmp_path / "a.gpkg", tmp_path) == b"clean"
    assert package.entry_bytes(tmp_path / "new.txt", tmp_path) == b"untracked"


def test_qgis_sidecar_files_are_not_packaged(tmp_path):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import package
    for name in ("p.qgz", "p.qgz.qto3settings", "dgm1.tif", "dgm1.tif.aux.xml"):
        (tmp_path / name).write_bytes(b"x")
    assert sorted(p.name for p in package.files_under(tmp_path)) == ["dgm1.tif", "p.qgz"]


def test_guelpe_zip_can_come_from_a_fresh_build_folder(tmp_path):
    """The Gülpe demo zip from a separately built folder (``--guelpe``), so a release ships
    a clean demo with all its files while the committed demo (the user's test drawings)
    stays untouched."""
    import shutil
    import sys
    import zipfile
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(root / "scripts"))
    import package

    fresh = root / ".cache" / "test_guelpe_fresh"
    shutil.rmtree(fresh, ignore_errors=True)
    shutil.copytree(root / "demo_guelpe", fresh)
    (fresh / "context" / "synthetic_logs.gpkg").write_bytes(b"x")
    try:
        zips = package.build(tmp_path, guelpe_src=fresh)
        names = zipfile.ZipFile(zips[2]).namelist()
        assert "context/synthetic_logs.gpkg" in names and "guelpe_project.qgz" in names
    finally:
        shutil.rmtree(fresh, ignore_errors=True)



def test_plugin_lines_are_wrapped():
    """Minor 10: no line in the plugin's Python is longer than 110 characters."""
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent / "geophysics_workbench"
    long = [f"{p.relative_to(root)}:{i}" for p in root.rglob("*.py")
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if len(line) > 110]
    assert long == []
