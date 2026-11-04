"""Gülpe real-data demo: the committed demo_guelpe/ folder (offline checks only)."""
import hashlib
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
GUELPE = REPO / "demo_guelpe"
CACHE = REPO / ".cache" / "guelpe"
sys.path.insert(0, str(REPO / "scripts"))


def _project():
    from qgis.core import QgsProject
    prj = QgsProject()
    assert prj.read(str(GUELPE / "guelpe_project.qgz"))
    return prj


def test_guelpe_demo_opens_offline(qgis_app):
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.ui.project_actions import attach_store

    prj = _project()
    st = attach_store(prj)
    prov = SectionDataProvider(st)
    assert sorted(p.name for p in st.profiles()) == [f"Transect {i}" for i in range(1, 5)]
    assert all(lyr.error is None for p in st.profiles() for lyr in prov.layers(p.id))
    offline = [lyr for lyr in prj.mapLayers().values() if lyr.providerType() in ("ogr", "gdal")]
    assert len(offline) >= 4 and all(lyr.isValid() for lyr in offline)
    prj.clear()


def test_guelpe_live_layers_point_at_brandenburg(qgis_app):
    prj = _project()
    sources = [lyr.source() for lyr in prj.mapLayers().values()]
    assert any("inspire.brandenburg.de/services/bpk_wfs" in s for s in sources)
    assert any("ge-core_guek300" in s for s in sources)
    prj.clear()


def test_guelpe_settings_reference_project_layers(qgis_app):
    from geophysics_workbench.ui.context_dialog import read_settings

    prj = _project()
    s = read_settings(prj)
    layer = prj.mapLayer
    assert layer(s.borehole.layer_id).name().startswith("Cores")
    assert layer(s.borehole.log_layer_id).name() == "Core logs"
    assert s.band is None or "Geology" in layer(s.band.layer_id).name()
    assert layer(s.dem_layer_id).name() == "DGM1 (LGB)"
    assert any(ls.checked for ls in s.line_layers)
    assert [(p.label_field, p.depth_field) for p in s.point_layers] == [("Bohrungsname", "Teufe_in_m")]
    assert "bpk_m_sch" in layer(s.point_layers[0].layer_id).source()
    assert s.buffer == 5.0
    prj.clear()


def test_guelpe_demo_paths_relative_and_models_unchanged():
    with zipfile.ZipFile(GUELPE / "guelpe_project.qgz") as zf:
        qgs = next(zf.read(n) for n in zf.namelist() if n.endswith(".qgs")).decode("utf-8")
    assert "D:/" not in qgs and "C:/" not in qgs and "D:\\" not in qgs
    if not (CACHE / "ert").exists():
        pytest.skip("raw cache missing: run scripts/fetch_demo_guelpe.py")
    from fetch_demo_guelpe import ERT_FILES
    for i, name in ERT_FILES.items():
        with zipfile.ZipFile(CACHE / "ert" / name) as zf:
            member = next(n for n in zf.namelist() if n.endswith("dcinv.result.vtk"))
            original = hashlib.sha1(zf.read(member)).hexdigest()
        copy = hashlib.sha1((GUELPE / f"data/ert/T{i}/dcinv.result.vtk").read_bytes()).hexdigest()
        assert copy == original


def test_build_twice_same_content(tmp_path):
    if not (CACHE / "ert").exists():
        pytest.skip("raw cache missing: run scripts/fetch_demo_guelpe.py")
    import build_demo_guelpe

    a, b = tmp_path / "a", tmp_path / "b"
    build_demo_guelpe.build_data(out=a)
    (a / "data" / "stray.txt").write_text("old")          # a rebuild must clear old outputs
    build_demo_guelpe.build_data(out=a)
    build_demo_guelpe.build_data(out=b)
    files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    assert not (a / "data" / "stray.txt").exists()
    for rel in files:
        if rel.suffix in (".csv", ".gpkg", ".vtk"):
            assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel


def test_live_layers_send_no_renderer_filter(qgis_app):
    """A categorised WFS layer without a catch-all category makes QGIS send every category
    as a server-side filter; Brandenburg rejects that URL with HTTP 400."""
    prj = _project()
    for lyr in prj.mapLayers().values():
        if lyr.providerType() == "WFS":
            assert lyr.renderer().filter(lyr.fields()) == "", lyr.name()
            assert "pageSize='500'" in lyr.source() or "pageSize=500" in lyr.source()
    prj.clear()
