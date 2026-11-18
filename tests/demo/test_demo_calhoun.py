"""Calhoun real-data demo: the committed demo_calhoun/ folder (offline checks only, on a copy:
the suite never writes to a committed demo store)."""
import shutil
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
CALHOUN = REPO / "demo_calhoun"
LINES = ["Line 10", "Line 11", "Line 12", "Line 6"]


@pytest.fixture
def opened(qgis_app, tmp_path):
    """(project, store, provider) of a copy of the demo."""
    from qgis.core import QgsProject

    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.ui.project_actions import attach_store

    copy = tmp_path / "demo_calhoun"
    shutil.copytree(CALHOUN, copy, ignore=shutil.ignore_patterns("*-wal", "*-shm"))
    prj = QgsProject()
    assert prj.read(str(copy / "calhoun_project.qgz"))
    st = attach_store(prj)
    assert st.path.parent == copy
    yield prj, st, SectionDataProvider(st)
    prj.clear()


def test_calhoun_demo_opens_offline(opened):
    prj, st, prov = opened
    assert sorted(p.name for p in st.profiles()) == sorted(LINES)
    for p in st.profiles():
        [d] = st.datasets(p.id)
        assert d.kind == "srt_model" and d.reader == "refrapy_xzv"
        assert all(lyr.error is None for lyr in prov.layers(p.id))
        assert prov.ties(p.id), f"{p.name} crosses no other demo line"
    offline = [lyr for lyr in prj.mapLayers().values() if lyr.providerType() in ("ogr", "gdal")]
    assert offline and all(lyr.isValid() for lyr in offline)


def test_calhoun_models_are_velocity(opened):
    from groundwork_geophysics.section.readout import unit_label
    _prj, st, prov = opened
    for p in st.profiles():
        [layer] = prov.layers(p.id)
        assert layer.mesh.quantity == "p_velocity" and unit_label(layer.mesh.unit) == "m/s"
        assert layer.style.scale is None or not layer.style.scale.log
        assert layer.mesh.coverage is not None and layer.mesh.coverage_cut is not None


def test_calhoun_attribution_names_sources():
    text = (CALHOUN / "ATTRIBUTION.md").read_text(encoding="utf-8")
    for needed in ("CC BY 4.0", "340773feb3b341d884f6742b55966609", "3DEP", "Flinchum",
                   "OpenStreetMap"):
        assert needed in text


def test_calhoun_project_has_no_personal_traces():
    with zipfile.ZipFile(CALHOUN / "calhoun_project.qgz") as zf:
        qgs = next(zf.read(n) for n in zf.namelist() if n.endswith(".qgs")).decode("utf-8")
    assert "D:/" not in qgs and "C:/" not in qgs and "D:\\" not in qgs
    assert "saveUser=" not in qgs or 'saveUser=""' in qgs
