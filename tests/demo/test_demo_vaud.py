"""Vaud reflection demo: the committed demo_vaud/ folder (offline checks only, on a copy: the
suite never writes to a committed demo store). Reading SEG-Y needs segyio."""
import shutil
import zipfile
from configparser import ConfigParser
from pathlib import Path

import pytest

from segy_files import require_segyio

require_segyio()

REPO = Path(__file__).resolve().parent.parent.parent
VAUD = REPO / "demo_vaud"
LINES = ["VD-P760057", "VD-P760068"]
MAX_BYTES = 6_000_000           # the whole demo folder


@pytest.fixture
def opened(qgis_app, tmp_path):
    """(project, store, provider) of a copy of the demo."""
    from qgis.core import QgsProject

    from groundwork_geophysics.section.context_layers import ContextGatherer
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.ui.project_actions import attach_store

    copy = tmp_path / "demo_vaud"
    shutil.copytree(VAUD, copy, ignore=shutil.ignore_patterns("*-wal", "*-shm",
                                                              "*_groundwork_3d",
                                                              "*_groundwork_cache"))
    prj = QgsProject()
    assert prj.read(str(copy / "vaud_project.qgz"))
    st = attach_store(prj)
    assert st.path.parent == copy
    prov = SectionDataProvider(st)
    # the section's ground line is the project's DEM, as the plugin gathers it
    prov.context_source = ContextGatherer(prj, st.crs_authid, lambda: None).items_for
    yield prj, st, prov
    prj.clear()


def test_vaud_demo_opens_offline(opened):
    prj, st, prov = opened
    assert sorted(p.name for p in st.profiles()) == LINES
    for p in st.profiles():
        [d] = st.datasets(p.id)
        assert d.kind == "refl_section" and d.reader == "segy"
        assert d.name == f"{p.name} stack"
        assert d.source_path == f"data/{p.name}_stack.sgy"
        layers = prov.layers(p.id)
        assert len(layers) == 1 and all(lyr.error is None for lyr in layers)
        assert len(prov.ties(p.id)) == 1, f"{p.name} should cross the other line once"
    offline = [lyr for lyr in prj.mapLayers().values() if lyr.providerType() in ("ogr", "gdal")]
    assert offline and all(lyr.isValid() for lyr in offline)


def test_vaud_sections_use_the_datum_and_velocities_of_the_sheet(opened):
    _prj, st, prov = opened
    for p in st.profiles():
        [d] = st.datasets(p.id)
        o = d.reader_options
        assert (o["position"], o["xy_field"], o["crs"]) == ("map", "source", "EPSG:2056")
        assert o["domain"] == "time" and "velocity" not in o
        assert (o["zero"], o["datum"]) == ("datum", 500.0) and "replacement_velocity" not in o
        assert o["velocity_kind"] == "average"
        times = [t for t, _v in o["velocity_table"]]
        assert len(times) > 2 and all(b > a for a, b in zip(times, times[1:]))
        [layer] = prov.layers(p.id)
        assert layer.error is None
        assert layer.traces.z_top.min() == pytest.approx(500.0, abs=0.01)   # at the datum
        assert layer.traces.z_top.max() == pytest.approx(500.0, abs=0.01)
        assert layer.style.clip_percent == pytest.approx(98.0)
        assert layer.style.gain is None or not layer.style.gain.active()   # already balanced
        assert layer.style.scale is None or layer.style.scale.cmap == "gray"


def test_vaud_deepest_sample_lies_near_ten_km(opened):
    _prj, st, prov = opened
    [p] = [p for p in st.profiles() if p.name == "VD-P760057"]
    [layer] = prov.layers(p.id)
    assert layer.traces.bounds()[2] < 500.0 - 8000.0      # 3.8 s at about 5,300 m/s


def test_vaud_ground_line_comes_from_the_dem(opened):
    import numpy as np
    _prj, st, prov = opened
    for p in st.profiles():
        assert p.metadata.get("topography") == "dem"
        surface = prov.surface(p.id)
        assert surface.kind == "dem"
        _s, z = surface.line
        z = np.asarray(z, float)
        z = z[np.isfinite(z)]
        assert 350.0 < z.min() and z.max() < 650.0           # 517-603 m and 378-613 m


def test_vaud_folder_is_small_and_complete():
    for need in ("vaud_project.qgz", "vaud_groundwork.gpkg", "ATTRIBUTION.md",
                 "data/VD-P760057_stack.sgy", "data/VD-P760068_stack.sgy",
                 "context/dem_swissalti3d_10m.tif"):
        assert (VAUD / need).is_file(), need
    assert (VAUD / "context/dem_swissalti3d_10m.tif").stat().st_size < 3_000_000
    # what the demo zip ships: not the 3D view's pictures or the remembered reads that QGIS
    # makes beside the store on a user's machine (git-ignored, made again where needed)
    from scripts.package import files_under
    total = sum(f.stat().st_size for f in files_under(VAUD))
    assert total < MAX_BYTES
    # only the stacks: not swisstopo's picture, report or catalogue
    assert sorted(p.name for p in (VAUD / "data").iterdir()) == [
        "VD-P760057_stack.sgy", "VD-P760068_stack.sgy"]
    assert sorted(p.name for p in (VAUD / "context").iterdir()) == ["dem_swissalti3d_10m.tif"]
    assert not list(VAUD.rglob("*.pdf"))


def test_vaud_attribution_names_sources():
    text = (VAUD / "ATTRIBUTION.md").read_text(encoding="utf-8")
    for needed in ("Source: Federal Office of Topography swisstopo",
                   "2D and 3D reflection seismic in Switzerland",
                   "https://opendata.swiss/en/dataset/2d-und-3d-reflexionsseismik-in-der-schweiz",
                   "VD-P760057", "VD-P760068", "500 m", "4000 m/s", "original section sheet",
                   "swissALTI3D", "OpenStreetMap"):
        assert needed in text, needed
    assert "3000 m/s" not in text


def test_vaud_project_has_no_personal_traces():
    import re
    with zipfile.ZipFile(VAUD / "vaud_project.qgz") as zf:
        qgs = next(zf.read(n) for n in zf.namelist() if n.endswith(".qgs")).decode("utf-8")
    assert "D:/" not in qgs and "C:/" not in qgs and "D:\\" not in qgs and "C:\\" not in qgs
    assert re.findall(r'saveUser(?:Full)?="([^"]*)"', qgs) in ([], ["", ""])
    cp = ConfigParser()
    cp.read(REPO / "groundwork_geophysics" / "metadata.txt", encoding="utf-8")
    assert re.findall(r"<author>([^<]*)</author>", qgs) == [cp["general"]["author"]]
