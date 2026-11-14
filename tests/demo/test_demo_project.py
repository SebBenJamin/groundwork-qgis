import shutil
from pathlib import Path

DEMO = Path(__file__).resolve().parent.parent.parent / "demo"


# -- brief test ----------------------------------------------------------------------------
def _sha1(path):
    import hashlib
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()


def test_demo_project_opens_and_resolves_sources(qgis_app, tmp_path):
    """On a copy: opening a store may update it (0.8: schema 1 -> 2); the suite must never
    write to the committed demo."""
    from qgis.core import QgsProject
    from geophysics_workbench.ui.project_actions import attach_store
    from geophysics_workbench.section.data import SectionDataProvider
    before = _sha1(DEMO / "demo_workbench.gpkg")
    copy = tmp_path / "demo"
    shutil.copytree(DEMO, copy)
    prj = QgsProject(); assert prj.read(str(copy / "demo_project.qgz"))
    st = attach_store(prj)
    assert _sha1(DEMO / "demo_workbench.gpkg") == before
    prov = SectionDataProvider(st)
    profs = st.profiles()
    assert len(profs) == 3
    assert all(l.error is None for p in profs for l in prov.layers(p.id))


# -- portability and content ---------------------------------------------------------------
def test_demo_works_from_another_folder(qgis_app, tmp_path):
    """Unpacked anywhere, the project finds the store, the store finds the model files and
    every layer (including the powerline GeoJSON) loads from the new folder."""
    from qgis.core import QgsProject

    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.ui.project_actions import attach_store

    copy = tmp_path / "unpacked demo"
    shutil.copytree(DEMO, copy)
    prj = QgsProject()
    assert prj.read(str(copy / "demo_project.qgz"))
    st = attach_store(prj)
    assert st.path.resolve() == (copy / "demo_workbench.gpkg").resolve()
    prov = SectionDataProvider(st)
    layers = [la for p in st.profiles() for la in prov.layers(p.id)]
    assert len(layers) == 3 and all(la.error is None for la in layers)
    for layer in prj.mapLayers().values():
        assert layer.isValid(), layer.name()
        if layer.providerType() == "ogr":
            src = Path(layer.source().split("|")[0]).resolve()
            assert src.is_relative_to(copy.resolve()), layer.source()


def test_demo_project_content(qgis_app):
    from qgis.core import QgsProject

    from geophysics_workbench.ui.project_actions import GROUP_NAME, SCOPE, STORE_KEY

    prj = QgsProject()
    assert prj.read(str(DEMO / "demo_project.qgz"))
    assert prj.crs().authid() == "EPSG:25832"
    assert prj.readEntry(SCOPE, STORE_KEY, "")[0] == "demo_workbench.gpkg"
    names = {l.name(): l for l in prj.mapLayers().values()}
    assert "OpenStreetMap" in names and names["OpenStreetMap"].providerType() == "wms"
    powerline = [l for n, l in names.items() if n.lower().startswith("powerline")]
    assert powerline and powerline[0].labelsEnabled()
    group = prj.layerTreeRoot().findGroup(GROUP_NAME)
    assert sorted(l.name() for l in group.findLayers()) == ["profiles", "stations"]
    extent = prj.viewSettings().defaultViewExtent()
    assert not extent.isNull() and extent.crs().authid() == "EPSG:25832"


def test_demo_store_datasets_use_relative_paths(qgis_app, tmp_path):
    from geophysics_workbench.store.gpkg_store import ProjectStore

    copy = tmp_path / "demo_workbench.gpkg"                    # never the committed file
    shutil.copy(DEMO / "demo_workbench.gpkg", copy)
    st = ProjectStore.open(copy)
    by_name = {p.name: p for p in st.profiles()}
    assert sorted(by_name) == ["P1", "P2", "P3"]
    got = {}
    for name, p in by_name.items():
        [d] = st.datasets(p.id)
        assert not Path(d.source_path).is_absolute()
        got[name] = (d.source_path, d.reader, d.reader_options["z_kind"])
        assert len(st.station_sets(p.id)) == 1
    assert got == {"P1": ("data/ert/P1/f001_res.dat", "r2_res_dat", "elevation"),
                   "P2": ("data/ert/P2/P2_model.dat", "zondres_xyz", "depth"),
                   "P3": ("data/ert/P3/f001_res.vtk", "vtk_legacy", "elevation")}


def test_demo_project_carries_no_personal_data():
    """No account or full name of whoever built the demo: saveUser/saveUserFull are blank
    and the metadata author is the plugin author."""
    import re
    import zipfile
    from configparser import ConfigParser

    with zipfile.ZipFile(DEMO / "demo_project.qgz") as zf:
        [qgs] = [n for n in zf.namelist() if n.endswith(".qgs")]
        text = zf.read(qgs).decode("utf-8")
    assert re.findall(r'saveUser(?:Full)?="([^"]*)"', text) in ([], ["", ""])
    cp = ConfigParser()
    cp.read(DEMO.parent / "geophysics_workbench" / "metadata.txt", encoding="utf-8")
    assert re.findall(r"<author>([^<]*)</author>", text) == [cp["general"]["author"]]


def test_demo_profiles_open_without_a_placement_note(qgis_app, tmp_path):
    """P1 and P2 carry a typed station spacing of 5 m (built by scripts/build_demo.py), so
    their models are pinned to the stations and the section shows no note."""
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.store.gpkg_store import ProjectStore

    copy = tmp_path / "demo"
    shutil.copytree(DEMO, copy)
    st = ProjectStore.open(copy / "demo_workbench.gpkg")
    prov = SectionDataProvider(st)
    by_name = {p.name: p for p in st.profiles()}
    for name in ("P1", "P2"):
        p = by_name[name]
        assert p.metadata.get("electrode_spacing") == 5.0
        assert prov.placement_note(p.id) == ""
        [d] = st.datasets(p.id)
        assert prov.fit(p.id, d.id) is not None                  # pinned by the spacing
