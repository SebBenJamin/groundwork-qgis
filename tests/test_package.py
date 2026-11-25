def test_package_imports_without_qgis_side_effects():
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    code = ("import sys, groundwork_geophysics; "
            "assert hasattr(groundwork_geophysics, 'classFactory'); "
            "assert 'groundwork_geophysics.plugin' not in sys.modules")
    r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_metadata_targets_qgis4():
    from configparser import ConfigParser
    from pathlib import Path
    cp = ConfigParser()
    cp.read(Path(__file__).resolve().parent.parent / "groundwork_geophysics" / "metadata.txt", encoding="utf-8")
    g = cp["general"]
    assert g["name"] == "Groundwork"
    assert g["qgisMinimumVersion"] == "4.2"
    assert g["supportsQt6"] == "True"
    assert g["version"] == "0.15.0"


def test_plugin_loads_and_unloads(fake_iface):
    from groundwork_geophysics import classFactory
    p = classFactory(fake_iface)
    p.initGui()
    p.unload()


def test_add_action_adds_to_menu(fake_iface):
    from groundwork_geophysics import classFactory
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
    assert len(zips) == 5
    calhoun_names = zipfile.ZipFile(zips[4]).namelist()
    assert zips[4].name.startswith("groundwork_geophysics-demo-calhoun-")
    for need in ("calhoun_project.qgz", "calhoun_groundwork.gpkg", "ATTRIBUTION.md",
                 "context/dem_3dep.tif", "data/refraction/L10/L10_xzv.txt",
                 "data/refraction/L10/L10_topography.txt", "data/stations/L10_geophones.csv"):
        assert need in calhoun_names
    erfurt = zips[3]
    assert erfurt.name.startswith("groundwork_geophysics-demo-erfurt-")
    erfurt_names = zipfile.ZipFile(erfurt).namelist()
    for need in ("erfurt_project.qgz", "erfurt_groundwork.gpkg", "ATTRIBUTION.md",
                 "context/cores.gpkg", "data/ert/ERT02/dcinv.result.vtk",
                 "data/stations/ERT02_electrodes.csv"):
        assert need in erfurt_names
    assert not any(n.endswith((".qto3settings", "-wal", "-shm")) for n in erfurt_names)
    guelpe = zips[2]
    assert guelpe.name.startswith("groundwork_geophysics-demo-guelpe-")
    names = zipfile.ZipFile(guelpe).namelist()
    for need in ("guelpe_project.qgz", "guelpe_groundwork.gpkg", "ATTRIBUTION.md",
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


def test_the_3d_view_files_are_not_packaged(tmp_path):
    """Point clouds and section pictures are made again from the models wherever a 3D view
    needs them: a demo zip must not carry the ones made while trying it."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import package
    (tmp_path / "site_groundwork.gpkg").write_bytes(b"x")
    cache = tmp_path / "site_groundwork_3d"
    cache.mkdir()
    for name in ("m-0123456789.las", "m-0123456789.copc.laz", "p-0123456789.json",
                 "p-0123456789.glb"):
        (cache / name).write_bytes(b"x")
    assert [p.name for p in package.files_under(tmp_path)] == ["site_groundwork.gpkg"]


def test_remembered_reads_are_not_packaged(tmp_path):
    """The read models kept beside a store are made again wherever a project is opened."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import package
    (tmp_path / "site_groundwork.gpkg").write_bytes(b"x")
    cache = tmp_path / "site_groundwork_cache"
    cache.mkdir()
    (cache / "d1-0123456789ab.npz").write_bytes(b"x")
    assert [p.name for p in package.files_under(tmp_path)] == ["site_groundwork.gpkg"]


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
    root = Path(__file__).resolve().parent.parent / "groundwork_geophysics"
    long = [f"{p.relative_to(root)}:{i}" for p in root.rglob("*.py")
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if len(line) > 110]
    assert long == []
