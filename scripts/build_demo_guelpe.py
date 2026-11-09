"""Build the Gülpe real-data demo (demo_guelpe/) from the raw downloads in .cache/guelpe/
(scripts/fetch_demo_guelpe.py). Needs QGIS's Python; online, because the live Brandenburg
layers are checked while the project is written.

Run: python-qgis.bat scripts/build_demo_guelpe.py

Writes under demo_guelpe/:
  data/ert/T{1..4}/dcinv.result.vtk   the authors' BERT inversions, byte-for-byte
  data/stations/T{1..4}_electrodes.csv all DGPS points (number,x,y,z), checked against the
                                      BERT electrode file (guelpe_data.match_electrodes)
  context/cores.gpkg                  the 24 cores (layer cores, table core_logs)
  context/synthetic_logs.gpkg         SYNTHETIC log curves for the cores (NOT measured;
                                      scripts/make_synthetic_curves.py)
  context/dgm1.tif                    DGM1 cropped to the transects + 100 m
  guelpe_workbench.gpkg               workbench store: Transect 1-4, one model each
  guelpe_project.qgz                  QGIS project (EPSG:25833), every path relative
  ATTRIBUTION.md                      sources and licences
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np

import demo_extra
import guelpe_data
import make_synthetic_curves
from fetch_demo_guelpe import CACHE, ERT_FILES, TRANSECTS_BBOX, dgm_tiles

ROOT = Path(__file__).resolve().parent.parent
DEMO_GUELPE = ROOT / "demo_guelpe"
#: our pyGIMLi response for transect 3 (not in the raw cache: made once by invert_guelpe.py)
MISFIT_INPUTS = ROOT / "scripts" / "data" / "guelpe"
CRS = "EPSG:25833"
STORE_NAME, PROJECT_NAME = "guelpe_workbench.gpkg", "guelpe_project.qgz"
SPACING = {1: 0.5, 2: 1.0, 3: 1.0, 4: 1.0}
MAX_CHAINAGE_MISFIT = 0.5             # m, station chainage against the model's electrode x
OSM_URI = "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0"
BPK_WFS = "https://inspire.brandenburg.de/services/bpk_wfs"
GUEK_WFS = "https://inspire.brandenburg.de/services/ge-core_guek300_wfs"
GUEK_WMS = "https://inspire.brandenburg.de/services/ge-core_guek300_wms"
DOP_WMS = "https://isk.geobasis-bb.de/mapproxy/dop20c/service/wms"
TITLE = "Geophysics Workbench real-data demo: Gülpe (Havel)"
ATTRIBUTION = """# Sources and licences

This demo uses only open data. Files marked *derived* were converted from the source
without changing its values.

## Research data (CC BY 4.0)
- **ERT**: Pohle, M.; Birnstengel, S.; Werban, U. (2025): 2D-ERT data measured in June 2023 and
  June 2024 in the Lower Havel Inner Delta near Lake Gülpe, Brandenburg (Germany). PANGAEA,
  https://doi.org/10.1594/PANGAEA.983478. `data/ert/T*/dcinv.result.vtk` are the authors' BERT
  inversion results, unchanged; `data/stations/*.csv` are their DGPS electrode positions
  (*derived*: reformatted).
- **Cores**: Köhler, A.; Kaniecki, M.; Schneider, B.; Zielhofer, C. (2025): Field based and
  laboratory data of sediment cores from the Lower Havel Inner Delta near Lake Gülpe. PANGAEA,
  https://doi.org/10.1594/PANGAEA.983887. `context/cores.gpkg` (*derived*: layer label =
  grain-size class and texture code; core-loss rows marked "offset" left out).
- **Synthetic curves** (`context/synthetic_logs.gpkg`, layer "Synthetic curves (NOT measured)"):
  made up for the demo, **not measured**. The cores have no geophysical logs; these seeded
  random values only show how log curves look in the borehole viewer
  (scripts/make_synthetic_curves.py).
- Both are part of: Köhler, A. et al. (2025): Geophysical, Sedimentological and Geochemical Data
  from the Lower Havel Inner Delta (Gülpe Island), Brandenburg (Germany). PANGAEA,
  https://doi.org/10.1594/PANGAEA.983208; data paper: Data in Brief 112372,
  https://doi.org/10.1016/j.dib.2025.112372.
- Licence: https://creativecommons.org/licenses/by/4.0/

## State data (Datenlizenz Deutschland Namensnennung 2.0, https://www.govdata.de/dl-de/by-2-0)
- **Boreholes** (live WFS Bohrpunktkarte): © LBGR, dl-de/by-2-0
- **Geology** GÜK300 (live {geology_kind}): © LBGR, dl-de/by-2-0
- **DGM1** `context/dgm1.tif` (*derived*: tiles merged and cropped): © GeoBasis-DE/LGB, dl-de/by-2-0
- **Aerial images** DOP20 (live WMS): © GeoBasis-DE/LGB, dl-de/by-2-0

## OpenStreetMap (ODbL)
- `context/waterways.geojson` (*derived*: reprojected) and the background map:
  © OpenStreetMap contributors, ODbL, https://www.openstreetmap.org/copyright
"""


# ---------------------------------------------------------------- data files
def _unzip_member(zf: zipfile.ZipFile, suffix: str, target: Path) -> Path:
    name = next(n for n in zf.namelist() if n.endswith(suffix))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(zf.read(name))
    return target


def build_data(cache: Path = CACHE, out: Path = DEMO_GUELPE) -> None:
    """Models, stations, cores and DGM1 from the cache (no QGIS)."""
    for sub in ("data", "context/cores.gpkg", "context/synthetic_logs.gpkg", "context/dgm1.tif"):
        p = out / sub
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for i, name in ERT_FILES.items():
            with zipfile.ZipFile(cache / "ert" / name) as zf:
                _unzip_member(zf, "dcinv.result.vtk", out / f"data/ert/T{i}/dcinv.result.vtk")
                dgps = _unzip_member(zf, f"DGPS_Transect{i}.txt", Path(tmp) / f"dgps{i}.txt")
                topo = _unzip_member(zf, "_topo.data", Path(tmp) / f"topo{i}.data")
            numbers, xyz = guelpe_data.read_dgps(dgps)
            guelpe_data.match_electrodes(guelpe_data.read_topo_electrodes(topo), numbers, xyz,
                                         SPACING[i])
            guelpe_data.write_stations_csv(out / f"data/stations/T{i}_electrodes.csv",
                                           numbers, xyz)
        # transect 3: the authors' measured data, and the response of our one-off pyGIMLi
        # inversion of it (scripts/invert_guelpe.py; committed under scripts/data/guelpe)
        with zipfile.ZipFile(cache / "ert" / ERT_FILES[3]) as zf:
            _unzip_member(zf, "_topo.data", out / "data/ert/T3/T3_measured.data")
        for name in ("T3_response.vector", "T3_pygimli.json"):
            shutil.copy(MISFIT_INPUTS / name, out / "data/ert/T3" / name)
    sites, logs = guelpe_data.parse_cores((cache / "cores.tab").read_text(encoding="utf-8"))
    guelpe_data.write_cores_gpkg(out / "context/cores.gpkg", sites, logs)
    make_synthetic_curves.write(out / "context/synthetic_logs.gpkg",
                                make_synthetic_curves.read_logs(out / "context/cores.gpkg"))
    guelpe_data.mosaic_dgm([cache / "dgm" / f"{t}.zip" for t in dgm_tiles(TRANSECTS_BBOX)],
                           TRANSECTS_BBOX, out / "context/dgm1.tif")


def read_stations(path: Path) -> tuple[np.ndarray, np.ndarray]:
    a = np.loadtxt(path, delimiter=",", skiprows=1)
    return a[:, 0].astype(int), a[:, 1:4]


# ---------------------------------------------------------------- workbench store
def build_workbench(out: Path = DEMO_GUELPE) -> Path:
    sys.path.insert(0, str(ROOT))
    from geophysics_workbench import readers
    from geophysics_workbench.core.model import (Dataset, file_fingerprint,
                                                 profile_from_stations, x_to_chainage)
    from geophysics_workbench.store.gpkg_store import ProjectStore

    path = out / STORE_NAME
    path.unlink(missing_ok=True)
    store = ProjectStore.create(path, CRS)
    with tempfile.TemporaryDirectory() as tmp:
        for i, name in ERT_FILES.items():
            numbers, xyz = read_stations(out / f"data/stations/T{i}_electrodes.csv")
            profile, stations = profile_from_stations(f"Transect {i}", CRS, xyz, numbers)
            with zipfile.ZipFile(CACHE / "ert" / name) as zf:
                topo = _unzip_member(zf, "_topo.data", Path(tmp) / f"topo{i}.data")
            el = guelpe_data.read_topo_electrodes(topo)
            matched = guelpe_data.match_electrodes(el, numbers, xyz, SPACING[i])
            s_station = profile.chainage.project(xyz[:, :2])[0]
            by_number = dict(zip(numbers, s_station))
            misfit = np.abs(np.array([by_number[n] for n in matched])
                            - x_to_chainage(el[:, 0], stations))
            if misfit.max() > MAX_CHAINAGE_MISFIT:
                raise RuntimeError(f"Transect {i}: chainage misfit {misfit.max():.2f} m")
            store.save_profile(profile)
            store.save_station_set(stations)
            rel = f"data/ert/T{i}/dcinv.result.vtk"
            result = readers.read(out / rel, reader="vtk_legacy")
            mtime, sha1 = file_fingerprint(str(out / rel))
            store.save_dataset(Dataset(f"T{i}_model", profile.id, stations.id, "ert_model", rel,
                                       mtime, sha1, "vtk_legacy",
                                       {"z_kind": "elevation", "chainage_offset": 0.0},
                                       result.provenance,
                                       name=f"Transect {i} (Pohle et al. 2025, BERT)"))
            if i == 3:
                rel = "data/ert/T3/T3_measured.data"
                opts = {"response": "T3_response.vector", "z_kind": "depth",
                        "chainage_offset": 0.0}
                result = readers.read(out / rel, reader="bert_data", response=opts["response"])
                mtime, sha1 = file_fingerprint(str(out / rel))
                store.save_dataset(Dataset("T3_misfit", profile.id, stations.id, "ert_misfit",
                                           rel, mtime, sha1, "bert_data", opts,
                                           result.provenance, quantity="misfit", unit="%",
                                           name="Transect 3 misfit (pyGIMLi re-inversion)"))
    return path


# ---------------------------------------------------------------- QGIS project
def _wfs(typename: str, url: str, name: str):
    from qgis.core import QgsVectorLayer
    uri = (f"pagingEnabled='true' pageSize='500' restrictToRequestBBOX='1' srsname='{CRS}' "
           f"typename='{typename}' url='{url}' version='auto'")
    return QgsVectorLayer(uri, name, "WFS")


def _wms(url: str, layer: str, name: str):
    from qgis.core import QgsRasterLayer
    uri = f"contextualWMSLegend=0&crs={CRS}&format=image/png&layers={layer}&styles=&url={url}"
    return QgsRasterLayer(uri, name, "wms")


def _symbol(layer, kind: str, props: dict) -> None:
    from qgis.core import (QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol,
                           QgsSingleSymbolRenderer)
    cls = {"marker": QgsMarkerSymbol, "line": QgsLineSymbol, "fill": QgsFillSymbol}[kind]
    layer.setRenderer(QgsSingleSymbolRenderer(cls.createSimple(props)))


def _log_action(layer) -> None:
    from qgis.core import QgsAction
    action = QgsAction(QgsAction.ActionType.OpenUrl, "Open layer log",
                       '[% "Schichtenverzeichnis_grafisch" %]', "", False, "Open layer log",
                       {"Field", "Canvas", "Feature"})
    layer.actions().addAction(action)


def _geology(project):
    """Live GÜK300 WFS with a usable unit-name field, else the WMS (map only)."""
    from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsSymbol

    layer = _wfs("ge:MappedFeature", GUEK_WFS, "Geology GÜK300 (LBGR, live)")
    field = None
    if layer.isValid():
        names = [f.name() for f in layer.fields()]
        field = next((n for n in ("name", "gml_name", "gml:name") if n in names), None)
    if field is None:
        return _wms(GUEK_WMS, "GE.GeologicUnit", "Geology GÜK300 (LBGR, live)"), None
    values = sorted({str(v) for v in layer.uniqueValues(layer.fields().indexOf(field))})
    cats = []
    for k, v in enumerate(values):
        sym = QgsSymbol.defaultSymbol(layer.geometryType())
        sym.setColor(__import__("qgis.PyQt.QtGui", fromlist=["QColor"]).QColor.fromHsv(
            (k * 67) % 360, 90, 230))
        cats.append(QgsRendererCategory(v, sym, v))
    other = QgsSymbol.defaultSymbol(layer.geometryType())
    other.setColor(other.color().fromRgb(200, 200, 200))
    cats.append(QgsRendererCategory(None, other, "other"))   # catch-all: else QGIS sends every
    layer.setRenderer(QgsCategorizedSymbolRenderer(field, cats))   # unit name as a WFS filter (HTTP 400)
    layer.setOpacity(0.4)
    return layer, field


def demo_context_settings(water: str, bpk: str, cores: str, logs: str, curves: str,
                          geology: str, geology_field: str | None, dem: str):
    """The demo's Context layers settings (layer ids in): the cores with their logs and the
    synthetic curves, and the LBGR boreholes as a second entry drawn to their total depth."""
    from geophysics_workbench.core.context_settings import (BandSetting, BoreholeSetting,
                                                            ContextSettings, CurveField,
                                                            CurveTableSetting, LineLayerSetting)
    synthetic = CurveTableSetting(curves, "core_id", "depth",
                                  [CurveField("gamma_synthetic", "API (synthetic)"),
                                   CurveField("cond_synthetic", "mS/m (synthetic)")])
    return ContextSettings(
        line_layers=[LineLayerSetting(water, "name", checked=True)],
        point_layers=[],
        boreholes=[BoreholeSetting(cores, "id", "elevation", logs, "core_id", "top", "bottom",
                                   "lithology", curve_tables=[synthetic]),
                   BoreholeSetting(bpk, "Bohrungsname", total_depth_field="Teufe_in_m")],
        band=BandSetting(geology, geology_field) if geology_field else None,
        dem_layer_id=dem, buffer=5.0, near_miss=10.0, dem_tolerance=0.5)


def apply_core_style(project, logs_id: str, style: Path) -> None:
    """Store the cores' borehole style (``context/core_logs_style.qml``) for the core log
    table, as Borehole style… would. FGDC patterns are kept by name (the plugin's pattern
    folder is registered while reading and writing)."""
    from qgis.core import QgsMapLayer, QgsVectorLayer

    from geophysics_workbench.patterns import register_svg_path, unregister_svg_path
    from geophysics_workbench.section.borehole_style import save_renderer
    register_svg_path()
    try:
        copy = QgsVectorLayer("Polygon?field=lithology:string", "style", "memory")
        msg, ok = copy.loadNamedStyle(str(style), QgsMapLayer.StyleCategory.Symbology)
        if not ok:
            raise RuntimeError(f"cannot read {style}: {msg}")
        save_renderer(project, logs_id, copy.renderer().clone())
    finally:
        unregister_svg_path()


#: title block values of the demo's plate (Plate details… in the Plates dialog)
DEMO_DETAILS = {"project": "Gülpe demo", "client": "(example)", "job": "(example)",
                "date": "(example)", "author": "(example)", "revision": "–"}


def demo_plate(profile_id: str, dataset_id: str):
    """The demo's report plate: A3 landscape, Transect 3's model with the interpretation and
    the boreholes. No field notes are added: the published data has none, and invented field
    observations do not belong in a real-data demo."""
    from geophysics_workbench.core.plates import FrameLook, FrameSpec, ModelLook, PlateSpec
    look = FrameLook([ModelLook(dataset_id)], None, boreholes=True, field_notes=True,
                     context=False)
    return PlateSpec("demo_plate_t3", "1", "Transect 3", "A3_landscape",
                     [FrameSpec("demo_t3_model", profile_id, look)])


def add_demo_plate(project, store) -> None:
    """Make the demo plate's layout (its section is drawn live when the project is open)."""
    from geophysics_workbench.plates.build import create_or_update_plate, set_plate_details
    from geophysics_workbench.plates.sources import detach_frame_items, unregister_frame_sources
    from geophysics_workbench.section.data import SectionDataProvider
    [p3] = [p for p in store.profiles() if p.name == "Transect 3"]
    set_plate_details(project, **DEMO_DETAILS)
    try:
        create_or_update_plate(project, store, SectionDataProvider(store),
                               demo_plate(p3.id, "T3_model"))
    finally:
        detach_frame_items(project)              # the sources go with this process
        unregister_frame_sources()


def build_qgis_project(out: Path = DEMO_GUELPE) -> tuple[Path, str]:
    """guelpe_project.qgz; returns its path and how geology was added ("WFS" or "WMS")."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT))
    from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsProject,
                           QgsRasterLayer, QgsRectangle, QgsReferencedRectangle, QgsVectorLayer)

    app = None
    if QgsApplication.instance() is None:
        app = QgsApplication([], False)
        app.initQgis()
    from geophysics_workbench.store.gpkg_store import ProjectStore
    from geophysics_workbench.ui.context_dialog import write_settings
    from geophysics_workbench.ui.project_actions import use_store

    path = out / PROJECT_NAME
    path.unlink(missing_ok=True)
    project = QgsProject()
    try:
        project.setFileName(str(path))
        project.setTitle(TITLE)
        demo_extra.set_author(project)
        md = project.metadata()
        md.setAbstract("Real, openly published data from Gülpe (Lower Havel, Brandenburg). "
                       "Sources and licences: ATTRIBUTION.md next to this project.")
        project.setMetadata(md)
        crs = QgsCoordinateReferenceSystem(CRS)
        project.setCrs(crs)
        project.writeEntryBool("Paths", "/Absolute", False)
        ctx = out / "context"
        cores = QgsVectorLayer(f"{ctx / 'cores.gpkg'}|layername=cores",
                               "Cores (Köhler et al. 2025)", "ogr")
        _symbol(cores, "marker", {"name": "circle", "color": "255,255,255",
                                  "outline_color": "20,20,20", "size": "2.6"})
        demo_extra._labels(cores, '"id"', 8.0, (20, 20, 20))
        logs = QgsVectorLayer(f"{ctx / 'cores.gpkg'}|layername=core_logs", "Core logs", "ogr")
        curves = QgsVectorLayer(f"{ctx / 'synthetic_logs.gpkg'}|layername="
                                f"{make_synthetic_curves.LAYER}",
                                "Synthetic curves (NOT measured)", "ogr")
        bpk = _wfs("app:bpk_m_sch", BPK_WFS, "State boreholes with log (LBGR, live)")
        _symbol(bpk, "marker", {"name": "diamond", "color": "200,30,30",
                                "outline_color": "60,0,0", "size": "2.8"})
        demo_extra._labels(bpk, '"Bohrungsname"', 8.0, (120, 0, 0))
        _log_action(bpk)
        bpk_o = _wfs("app:bpk_o_sch", BPK_WFS, "State boreholes without log (LBGR, live)")
        _symbol(bpk_o, "marker", {"name": "diamond", "color": "240,170,170",
                                  "outline_color": "120,60,60", "size": "2.2"})
        water = QgsVectorLayer(str(ctx / "waterways.geojson"), "Waterways (OSM)", "ogr")
        _symbol(water, "line", {"color": "30,110,200", "width": "0.6"})
        demo_extra._labels(water, '"name"', 8.0, (20, 70, 150), line=True)
        geology, geology_field = _geology(project)
        dem = QgsRasterLayer(str(ctx / "dgm1.tif"), "DGM1 (LGB)", "gdal")
        dop = _wms(DOP_WMS, "bebb_dop20c", "Aerial images DOP20 (LGB, live)")
        osm = QgsRasterLayer(OSM_URI, "OpenStreetMap", "wms")
        offline = (cores, logs, curves, water, dem, osm)
        for layer in offline:
            if not layer.isValid():
                raise RuntimeError(f"demo layer {layer.name()} is not valid")
        root = project.layerTreeRoot()
        for layer in (cores, logs, curves, bpk, bpk_o, water, geology, dem, dop, osm):
            if not layer.isValid() and layer not in offline:
                print(f"warning: live layer {layer.name()} is not reachable now")
            project.addMapLayer(layer, False)
            root.addLayer(layer)
        for hidden in (bpk_o, dem, dop):
            root.findLayer(hidden.id()).setItemVisibilityChecked(False)
        write_settings(project, demo_context_settings(
            water.id(), bpk.id(), cores.id(), logs.id(), curves.id(), geology.id(),
            geology_field, dem.id()))
        apply_core_style(project, logs.id(), ctx / "core_logs_style.qml")
        store = use_store(ProjectStore.open(out / STORE_NAME), project)   # group on top
        add_demo_plate(project, store)
        xy = np.vstack([p.xy for p in store.profiles()])
        (x0, y0), (x1, y1) = xy.min(axis=0) - 150.0, xy.max(axis=0) + 150.0
        project.viewSettings().setDefaultViewExtent(
            QgsReferencedRectangle(QgsRectangle(x0, y0, x1, y1), crs))
        if not project.write():
            raise RuntimeError(f"cannot write {path}: {project.error()}")
        demo_extra.strip_save_user(path)
    finally:
        project.clear()
        del project
        if app is not None:
            app.exitQgis()
    (out / "context" / "dgm1.tif.aux.xml").unlink(missing_ok=True)
    return path, "WFS" if geology_field else "WMS"


def main() -> int:
    """``--out <folder>`` builds there instead of demo_guelpe/ (e.g. for a release zip, so
    the committed demo with someone's test drawings stays as it is)."""
    out = DEMO_GUELPE
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
        (out / "context").mkdir(parents=True, exist_ok=True)
        # inputs kept in the repo, not built from the cache
        for name in ("waterways.geojson", "core_logs_style.qml"):
            shutil.copy(DEMO_GUELPE / "context" / name, out / "context" / name)
    build_data(out=out)
    build_workbench(out=out)
    _, geology_kind = build_qgis_project(out=out)
    (out / "ATTRIBUTION.md").write_text(ATTRIBUTION.format(geology_kind=geology_kind),
                                        encoding="utf-8", newline="\n")
    print(f"{out} built; geology via {geology_kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
