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


def _project(folder=GUELPE):
    from qgis.core import QgsProject
    prj = QgsProject()
    assert prj.read(str(folder / "guelpe_project.qgz"))
    return prj


def test_guelpe_demo_opens_offline(qgis_app, tmp_path):
    """On a copy: opening a store may update it (0.8: schema 1 -> 2), and the committed
    demo folder holds the user's drawings - the suite must never write to it."""
    import hashlib
    import shutil

    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.ui.project_actions import attach_store

    store_file = GUELPE / "guelpe_workbench.gpkg"
    before = hashlib.sha1(store_file.read_bytes()).hexdigest()
    copy = tmp_path / "demo_guelpe"
    shutil.copytree(GUELPE, copy, ignore=shutil.ignore_patterns("*-wal", "*-shm"))
    prj = _project(copy)
    st = attach_store(prj)
    assert st.path.parent == copy
    prov = SectionDataProvider(st)
    assert sorted(p.name for p in st.profiles()) == [f"Transect {i}" for i in range(1, 5)]
    assert all(lyr.error is None for p in st.profiles() for lyr in prov.layers(p.id))
    offline = [lyr for lyr in prj.mapLayers().values() if lyr.providerType() in ("ogr", "gdal")]
    assert len(offline) >= 4 and all(lyr.isValid() for lyr in offline)
    prj.clear()
    assert hashlib.sha1(store_file.read_bytes()).hexdigest() == before


def test_guelpe_live_layers_point_at_brandenburg(qgis_app):
    prj = _project()
    sources = [lyr.source() for lyr in prj.mapLayers().values()]
    assert any("inspire.brandenburg.de/services/bpk_wfs" in s for s in sources)
    assert any("ge-core_guek300" in s for s in sources)
    assert any("inspire.brandenburg.de/services/gk_wfs" in s or
               "inspire.brandenburg.de/services/gk_wms" in s for s in sources)
    prj.clear()


def test_guelpe_geology_is_the_gk25_with_guek300_switched_off(qgis_app):
    """The band and the visible geology are the 1:25 000 map; the GÜK300 stays as a layer
    that is switched off (at 1:300 000 the whole demo area is one polygon)."""
    from geophysics_workbench.ui.context_dialog import read_settings

    prj = _project()
    by_name = {lyr.name(): lyr for lyr in prj.mapLayers().values()}
    gk25, guek = by_name["Geology GK 25 (LBGR, live)"], by_name["Geology GÜK300 (LBGR, live)"]
    root = prj.layerTreeRoot()
    assert root.findLayer(gk25.id()).isVisible()
    assert not root.findLayer(guek.id()).isVisible()
    band = read_settings(prj).band
    assert band is None or band.layer_id == gk25.id()
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


def test_demo_build_styles_the_core_logs(qgis_app):
    """The build stores the cores' style for the core log table, by FGDC pattern name."""
    from qgis.core import QgsProject

    import build_demo_guelpe
    from geophysics_workbench.section.borehole_style import load_renderer
    prj = QgsProject()
    build_demo_guelpe.apply_core_style(prj, "logs_id",
                                       REPO / "demo_guelpe" / "context" / "core_logs_style.qml")
    r = load_renderer(prj, "logs_id")
    assert r is not None and r.type() == "categorizedSymbol"
    assert {c.value() for c in r.categories()} == {"sand", "loam", "clay", "peat", "Oh"}
    text = prj.readEntry("geophysics_workbench", "borehole_style/logs_id", "")[0]
    assert "fgdc/607" in text and ":/" not in text.replace("qrc:/", "")


def test_demo_plate_spec():
    """One A3 landscape plate of Transect 3: the model with interpretation and boreholes."""
    import build_demo_guelpe
    plate = build_demo_guelpe.demo_plate("p3", "T3_model")
    assert (plate.number, plate.title, plate.template) == ("1", "Transect 3", "A3_landscape")
    [frame] = plate.frames
    assert frame.profile_id == "p3" and [m.dataset_id for m in frame.look.models] == ["T3_model"]
    assert frame.look.boreholes and frame.look.field_notes and frame.look.interp_version is None
    assert not frame.look.context                       # dense at plate scale; user's choice
    assert build_demo_guelpe.DEMO_DETAILS["project"] == "Gülpe demo"


def test_demo_build_adds_one_plate_and_no_field_notes(tmp_path, qgis_app):
    if not (CACHE / "ert").exists():
        pytest.skip("raw cache missing: run scripts/fetch_demo_guelpe.py")
    from qgis.core import QgsExpressionContextUtils, QgsProject

    import build_demo_guelpe
    from geophysics_workbench.plates.sources import read_plates
    from geophysics_workbench.store.gpkg_store import ProjectStore
    from geophysics_workbench.ui.project_actions import use_store
    build_demo_guelpe.build_data(out=tmp_path)
    st = ProjectStore.open(build_demo_guelpe.build_workbench(out=tmp_path))
    prj = QgsProject()
    use_store(st, prj)
    build_demo_guelpe.add_demo_plate(prj, st)
    [plate] = read_plates(prj)
    assert plate.title == "Transect 3"
    assert prj.layoutManager().layoutByName("Plate 1 – Transect 3") is not None
    assert QgsExpressionContextUtils.projectScope(prj).variable("wb_project") == "Gülpe demo"
    assert st.field_notes() == []                        # no invented field observations
    prj.clear()
