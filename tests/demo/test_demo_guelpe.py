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
    assert layer(s.boreholes[0].layer_id).name().startswith("Cores")
    assert layer(s.boreholes[0].log_layer_id).name() == "Core logs"
    assert s.band is None or "Geology" in layer(s.band.layer_id).name()
    assert layer(s.dem_layer_id).name() == "DGM1 (LGB)"
    assert any(ls.checked for ls in s.line_layers)
    # 0.5: the LBGR boreholes are a borehole entry (total depth); older builds: a point layer
    state = [(p.layer_id, p.depth_field) for p in s.point_layers] + [
        (b.layer_id, b.total_depth_field) for b in s.boreholes[1:]]
    assert [d for _i, d in state] == ["Teufe_in_m"]
    assert "bpk_m_sch" in layer(state[0][0]).source()
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


def test_build_adds_transect3_misfit(tmp_path, qgis_app):
    """The demo build adds T3's measured data with our pyGIMLi response as a misfit layer
    (built here into a temporary folder; the committed demo is rebuilt by the user)."""
    if not (CACHE / "ert").exists():
        pytest.skip("raw cache missing: run scripts/fetch_demo_guelpe.py")
    import json

    import build_demo_guelpe

    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.store.gpkg_store import ProjectStore
    build_demo_guelpe.build_data(out=tmp_path)
    path = build_demo_guelpe.build_workbench(out=tmp_path)
    st = ProjectStore.open(path)
    [p3] = [p for p in st.profiles() if p.name == "Transect 3"]
    ds = {d.id: d for d in st.datasets(p3.id)}
    assert ds["T3_misfit"].kind == "ert_misfit"
    layer = next(la for la in SectionDataProvider(st).layers(p3.id) if la.dataset.id == "T3_misfit")
    assert layer.error is None, layer.error
    info = json.loads((tmp_path / "data/ert/T3/T3_pygimli.json").read_text())
    assert layer.mesh.readings.rms_percent() == pytest.approx(info["rms_percent"], rel=1e-6)


def test_synthetic_curves_are_labelled_and_deterministic(tmp_path):
    """The demo's log curves are made up (the real cores have none): the table name, its
    description, its field names and units all say so, and two builds are identical."""
    from osgeo import ogr

    import make_synthetic_curves
    a, b = tmp_path / "a.gpkg", tmp_path / "b.gpkg"
    logs = {"RK1": [(0.0, 0.5, "topsoil"), (0.5, 2.0, "sand")], "RK2": [(0.0, 1.0, "clay")]}
    make_synthetic_curves.write(a, logs)
    make_synthetic_curves.write(b, logs)
    with ogr.ExceptionMgr():
        ds = ogr.Open(str(a))
        layer = ds.GetLayerByName(make_synthetic_curves.LAYER)
        assert "NOT_MEASURED" in make_synthetic_curves.LAYER
        assert "synthetic" in (layer.GetMetadataItem("DESCRIPTION") or "").lower()
        names = [layer.GetLayerDefn().GetFieldDefn(i).GetName()
                 for i in range(layer.GetLayerDefn().GetFieldCount())]
        assert names == ["core_id", "depth", "gamma_synthetic", "cond_synthetic"]
        rows = [(f["core_id"], f["depth"], f["gamma_synthetic"]) for f in layer]
    assert {r[0] for r in rows} == {"RK1", "RK2"}
    assert max(r[1] for r in rows if r[0] == "RK1") == pytest.approx(2.0)
    assert a.read_bytes() == b.read_bytes()


def test_demo_context_settings_two_borehole_entries():
    import build_demo_guelpe

    from geophysics_workbench.core.context_settings import curve_key
    s = build_demo_guelpe.demo_context_settings(
        water="w", bpk="b", cores="c", logs="l", curves="k", geology="g", geology_field="u",
        dem="d")
    cores, state = s.boreholes
    assert (cores.layer_id, cores.log_layer_id) == ("c", "l")
    [table] = cores.curve_tables
    assert table.layer_id == "k" and [(c.field, c.unit) for c in table.curves] == [
        ("gamma_synthetic", "API (synthetic)"), ("cond_synthetic", "mS/m (synthetic)")]
    assert cores.section_curves == []                     # curves on the section: user's choice
    assert (state.layer_id, state.id_field, state.total_depth_field) == (
        "b", "Bohrungsname", "Teufe_in_m")
    assert s.point_layers == [] and curve_key("k", "gamma_synthetic") == "k:gamma_synthetic"
