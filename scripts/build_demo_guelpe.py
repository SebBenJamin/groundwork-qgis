"""Build the Gülpe real-data demo (demo_guelpe/) from the raw downloads in .cache/guelpe/
(scripts/fetch_demo_guelpe.py). Needs QGIS's Python; online, because the live Brandenburg
layers are checked while the project is written.

Run: python-qgis.bat scripts/build_demo_guelpe.py

Writes under demo_guelpe/:
  data/ert/T{1..4}/dcinv.result.vtk   the authors' BERT inversions, byte-for-byte
  data/stations/T{1..4}_electrodes.csv all DGPS points (number,x,y,z), checked against the
                                      BERT electrode file (guelpe_data.match_electrodes)
  context/cores.gpkg                  the 24 cores (layer cores, table core_logs) and the
                                      lab values of their samples (table core_lab)
  context/dgm1.tif                    DGM1 cropped to the transects + 100 m
  guelpe_groundwork.gpkg              store: Transect 1-4, one model each
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
from fetch_demo_guelpe import CACHE, ERT_FILES, TRANSECTS_BBOX, dgm_tiles

ROOT = Path(__file__).resolve().parent.parent
DEMO_GUELPE = ROOT / "demo_guelpe"
#: our pyGIMLi response for transect 3 (not in the raw cache: made once by invert_guelpe.py)
MISFIT_INPUTS = ROOT / "scripts" / "data" / "guelpe"
CRS = "EPSG:25833"
STORE_NAME, PROJECT_NAME = "guelpe_groundwork.gpkg", "guelpe_project.qgz"
SPACING = {1: 0.5, 2: 1.0, 3: 1.0, 4: 1.0}
MAX_CHAINAGE_MISFIT = 0.5             # m, station chainage against the model's electrode x
OSM_URI = "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0"
BPK_WFS = "https://inspire.brandenburg.de/services/bpk_wfs"
GUEK_WFS = "https://inspire.brandenburg.de/services/ge-core_guek300_wfs"
GUEK_WMS = "https://inspire.brandenburg.de/services/ge-core_guek300_wms"
GK_WFS = "https://inspire.brandenburg.de/services/gk_wfs"      # GK 25, GÜK 100, GÜK 300
GK_WMS = "https://inspire.brandenburg.de/services/gk_wms"
GEOLOGY_MARGIN = 1500.0      # m around the transects: the GK 25 units the legend lists
DOP_WMS = "https://isk.geobasis-bb.de/mapproxy/dop20c/service/wms"
TITLE = "Groundwork real-data demo: Gülpe (Havel)"
#: the cores' lab values shown as curves (the table has all of guelpe_data.LAB_FIELDS)
LAB_CURVES = ("toc", "tic", "sand", "silt", "clay")
LAB_LAYER_NAME = "Core lab values (Köhler et al. 2025)"
LAB_LOG_CURVES = ("toc",)
#: the demo's curve looks: colour and fill per lab curve
LAB_CURVE_LOOKS = {"toc": ("#3d2b1f", "none"), "tic": ("#2f6db5", "none"),
                   "sand": ("#d4a017", "left"), "silt": ("#8f8f5a", "left"),
                   "clay": ("#a0522d", "left")}
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
  grain-size class and texture code; core-loss rows marked "offset" left out). Its table
  `core_lab` holds the lab values of the 62 core samples (C, N, S and grain-size fractions)
  unchanged, each at the middle of its sample (to the centimetre) with the sample's top and
  bottom; `sand`, `silt` and `clay` are the sums of their fractions (*derived*). Sulfur given
  as "<0.0020" (below detection, five RK15 samples) is left empty.
- Both are part of: Köhler, A. et al. (2025): Geophysical, Sedimentological and Geochemical Data
  from the Lower Havel Inner Delta (Gülpe Island), Brandenburg (Germany). PANGAEA,
  https://doi.org/10.1594/PANGAEA.983208; data paper: Data in Brief 112372,
  https://doi.org/10.1016/j.dib.2025.112372.
- Licence: https://creativecommons.org/licenses/by/4.0/

## State data (Datenlizenz Deutschland Namensnennung 2.0, https://www.govdata.de/dl-de/by-2-0)
- **Boreholes** `context/state_boreholes.gpkg` (*derived*: the Bohrpunktkarte WFS, layers
  bpk_m_sch and bpk_o_sch, within 1.5 km of the transects, saved unchanged):
  © LBGR, dl-de/by-2-0
- **Geology** GK 25, Geologische Karte 1 : 25 000 (live {geology_kind}), and GÜK300 (live, switched
  off on the map; both drawn as strips on the section): © LBGR, dl-de/by-2-0
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
    for sub in ("data", "context/cores.gpkg", "context/synthetic_logs.gpkg", "context/dgm1.tif",
                "context/state_boreholes.gpkg"):     # synthetic_logs: from builds before 0.16
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
    cores_text = (cache / "cores.tab").read_text(encoding="utf-8")
    sites, logs = guelpe_data.parse_cores(cores_text)
    guelpe_data.write_cores_gpkg(out / "context/cores.gpkg", sites, logs)
    guelpe_data.write_lab_table(out / "context/cores.gpkg", guelpe_data.parse_samples(cores_text))
    guelpe_data.mosaic_dgm([cache / "dgm" / f"{t}.zip" for t in dgm_tiles(TRANSECTS_BBOX)],
                           TRANSECTS_BBOX, out / "context/dgm1.tif")
    # a copy around the transects, not the live state-wide WFS: a QGIS 3D view asks a web
    # layer for its whole scene, which for these boreholes is half of Brandenburg
    boreholes = cache / "state_boreholes.gpkg"
    if not boreholes.exists():
        raise RuntimeError(f"{boreholes} is missing: run scripts/fetch_demo_guelpe.py")
    shutil.copy(boreholes, out / "context/state_boreholes.gpkg")


def read_stations(path: Path) -> tuple[np.ndarray, np.ndarray]:
    a = np.loadtxt(path, delimiter=",", skiprows=1)
    return a[:, 0].astype(int), a[:, 1:4]


# ---------------------------------------------------------------- workbench store
def build_workbench(out: Path = DEMO_GUELPE) -> Path:
    sys.path.insert(0, str(ROOT))
    from groundwork_geophysics import readers
    from groundwork_geophysics.core.model import (Dataset, file_fingerprint,
                                                 profile_from_stations, x_to_chainage)
    from groundwork_geophysics.store.gpkg_store import ProjectStore

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


def _unit_label(text: str) -> str:
    """Legend label of a map unit: its name before the first colon (the GK 25 descriptions
    continue with the full lithology, which stays in the data and the section band)."""
    text = text.strip().strip('"').strip()
    return text.split(":", 1)[0].strip() or text


def _categorized(layer, field: str, extent) -> None:
    """Categories for the units of ``field`` inside ``extent`` (a QgsRectangle in the layer's
    CRS), plus a catch-all. Only the area around the transects is asked for: the state-wide
    WFS layers are far too large to list every unit."""
    from qgis.core import (QgsCategorizedSymbolRenderer, QgsFeatureRequest, QgsRendererCategory,
                           QgsSymbol)
    from qgis.PyQt.QtGui import QColor

    request = QgsFeatureRequest().setFilterRect(extent).setSubsetOfAttributes([field],
                                                                               layer.fields())
    values = sorted({str(f[field]) for f in layer.getFeatures(request) if f[field] is not None})
    cats = []
    for k, v in enumerate(values):
        sym = QgsSymbol.defaultSymbol(layer.geometryType())
        sym.setColor(QColor.fromHsv((k * 67) % 360, 90, 230))
        cats.append(QgsRendererCategory(v, sym, _unit_label(v)))
    other = QgsSymbol.defaultSymbol(layer.geometryType())
    other.setColor(QColor(200, 200, 200))
    cats.append(QgsRendererCategory(None, other, "other"))   # catch-all: else QGIS sends every
    layer.setRenderer(QgsCategorizedSymbolRenderer(field, cats))   # unit name as a WFS filter (HTTP 400)
    layer.setOpacity(0.4)


def _geology(project, extent):
    """The geology layers: the live GK 25 WFS (unit description as the band field), else its
    WMS (map only); and the live GÜK300 WFS (or WMS) as a second layer. Returns
    ``(gk25 layer, its field or None, GÜK300 layer, its field or None)``."""
    gk25 = _wfs("app:gk25", GK_WFS, "Geology GK 25 (LBGR, live)")
    field = None
    if gk25.isValid():
        names = [f.name() for f in gk25.fields()]
        field = next((n for n in ("beschreibung", "kennung") if n in names), None)
    if field is None:
        gk25 = _wms(GK_WMS, "gk25", "Geology GK 25 (LBGR, live)")
    else:
        _categorized(gk25, field, extent)

    guek = _wfs("ge:MappedFeature", GUEK_WFS, "Geology GÜK300 (LBGR, live)")
    guek_field = None
    if guek.isValid():
        names = [f.name() for f in guek.fields()]
        guek_field = next((n for n in ("name", "gml_name", "gml:name") if n in names), None)
    if guek_field is None:
        guek = _wms(GUEK_WMS, "GE.GeologicUnit", "Geology GÜK300 (LBGR, live)")
    else:
        _categorized(guek, guek_field, extent)
    return gk25, field, guek, guek_field


def demo_context_settings(water: str, bpk: str, cores: str, logs: str, curves: str,
                          geology: str, geology_field: str | None, dem: str,
                          guek: str = "", guek_field: str | None = None):
    """The demo's Context layers settings (layer ids in): the cores with their logs and the
    lab values of their samples as curves, and the LBGR boreholes as a second entry drawn to
    their total depth."""
    from groundwork_geophysics.core.context_settings import (BandSetting, BoreholeSetting,
                                                            ContextSettings, CurveField,
                                                            CurveTableSetting, LineLayerSetting)
    lab = CurveTableSetting(curves, "core_id", "depth",
                            [CurveField(name, "%") for name in LAB_CURVES])
    return ContextSettings(
        line_layers=[LineLayerSetting(water, "name", checked=True)],
        point_layers=[],
        boreholes=[BoreholeSetting(cores, "id", "elevation", logs, "core_id", "top", "bottom",
                                   "lithology", curve_tables=[lab]),
                   BoreholeSetting(bpk, "Bohrungsname", total_depth_field="Teufe_in_m")],
        bands=([BandSetting(guek, guek_field, "GÜK 300")] if guek_field else [])
        + ([BandSetting(geology, geology_field, "GK 25")] if geology_field else []),
        dem_layer_id=dem, buffer=5.0, near_miss=10.0, dem_tolerance=0.5)


def demo_curve_styles(curves_id: str) -> dict:
    """The lab curves' looks by curve key (the demo's choice; restyle in Curve Style…):
    TOC (about 0.02 to 11 %) on a log scale, carbonate as a line, and sand, silt and clay
    filled from the left in colours after the material."""
    from groundwork_geophysics.core.borehole_curves import CurveStyle
    return {f"{curves_id}:{name}": CurveStyle(colour=colour, fill=fill,
                                              fill_colour=colour + "55",
                                              log=name in LAB_LOG_CURVES)
            for name, (colour, fill) in LAB_CURVE_LOOKS.items()}


def apply_core_style(project, logs_id: str, style: Path) -> None:
    """Store the cores' borehole style (``context/core_logs_style.qml``) for the core log
    table, as Borehole style… would. FGDC patterns are kept by name (the plugin's pattern
    folder is registered while reading and writing)."""
    from qgis.core import QgsMapLayer, QgsVectorLayer

    from groundwork_geophysics.patterns import register_svg_path, unregister_svg_path
    from groundwork_geophysics.section.borehole_style import save_renderer
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
    from groundwork_geophysics.core.plates import FrameLook, FrameSpec, ModelLook, PlateSpec
    look = FrameLook([ModelLook(dataset_id)], None, boreholes=True, field_notes=True,
                     context=False)
    return PlateSpec("demo_plate_t3", "1", "Transect 3", "A3_landscape",
                     [FrameSpec("demo_t3_model", profile_id, look)])


def add_demo_plate(project, store) -> None:
    """Make the demo plate's layout (its section is drawn live when the project is open)."""
    from groundwork_geophysics.plates.build import create_or_update_plate, set_plate_details
    from groundwork_geophysics.plates.sources import detach_frame_items, unregister_frame_sources
    from groundwork_geophysics.section.data import SectionDataProvider
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
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    from groundwork_geophysics.ui.context_dialog import write_settings
    from groundwork_geophysics.ui.project_actions import use_store

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
        curves = QgsVectorLayer(f"{ctx / 'cores.gpkg'}|layername={guelpe_data.LAB_TABLE}",
                                LAB_LAYER_NAME, "ogr")
        state = ctx / "state_boreholes.gpkg"
        bpk = QgsVectorLayer(f"{state}|layername=with_log", "State boreholes with log (LBGR)",
                             "ogr")
        _symbol(bpk, "marker", {"name": "diamond", "color": "200,30,30",
                                "outline_color": "60,0,0", "size": "2.8"})
        demo_extra._labels(bpk, '"Bohrungsname"', 8.0, (120, 0, 0))
        _log_action(bpk)
        bpk_o = QgsVectorLayer(f"{state}|layername=without_log",
                               "State boreholes without log (LBGR)", "ogr")
        _symbol(bpk_o, "marker", {"name": "diamond", "color": "240,170,170",
                                  "outline_color": "120,60,60", "size": "2.2"})
        water = QgsVectorLayer(str(ctx / "waterways.geojson"), "Waterways (OSM)", "ogr")
        _symbol(water, "line", {"color": "30,110,200", "width": "0.6"})
        demo_extra._labels(water, '"name"', 8.0, (20, 70, 150), line=True)
        from qgis.core import QgsRectangle as _Rect
        xy = np.vstack([p.xy for p in ProjectStore.open(out / STORE_NAME).profiles()])
        (gx0, gy0), (gx1, gy1) = xy.min(axis=0) - GEOLOGY_MARGIN, xy.max(axis=0) + GEOLOGY_MARGIN
        geology, geology_field, guek, guek_field = _geology(project, _Rect(gx0, gy0, gx1, gy1))
        dem = QgsRasterLayer(str(ctx / "dgm1.tif"), "DGM1 (LGB)", "gdal")
        dem.elevationProperties().setEnabled(True)      # "Represents elevation surface"
        dop = _wms(DOP_WMS, "bebb_dop20c", "Aerial images DOP20 (LGB, live)")
        osm = QgsRasterLayer(OSM_URI, "OpenStreetMap", "wms")
        offline = (cores, logs, curves, bpk, bpk_o, water, dem, osm)
        for layer in offline:
            if not layer.isValid():
                raise RuntimeError(f"demo layer {layer.name()} is not valid")
        root = project.layerTreeRoot()
        for layer in (cores, logs, curves, bpk, bpk_o, water, geology, guek, dem, dop, osm):
            if not layer.isValid() and layer not in offline:
                print(f"warning: live layer {layer.name()} is not reachable now")
            project.addMapLayer(layer, False)
            root.addLayer(layer)
        for hidden in (bpk_o, guek, dem, dop):
            root.findLayer(hidden.id()).setItemVisibilityChecked(False)
        write_settings(project, demo_context_settings(
            water.id(), bpk.id(), cores.id(), logs.id(), curves.id(), geology.id(),
            geology_field, dem.id(), guek.id(), guek_field))
        apply_core_style(project, logs.id(), ctx / "core_logs_style.qml")
        from groundwork_geophysics.section.borehole_style import save_curve_styles
        save_curve_styles(project, demo_curve_styles(curves.id()))
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
