"""Build the Erfurt real-data demo (demo_erfurt/) from the downloads in .cache/erfurt/
(scripts/fetch_demo_erfurt.py, or the PANGAEA files unpacked there by hand). Needs QGIS's
Python.

Run: python-qgis.bat scripts/build_demo_erfurt.py [--cache <folder>] [--out <folder>]

Writes under demo_erfurt/ (or --out):
  data/ert/ERTnn/dcinv.result.vtk     the authors' BERT inversions, byte-for-byte
  data/ert/ERTnn/ERTnn_measured.data  the authors' BERT input data (measured, with errors)
  data/stations/ERTnn_electrodes.csv  the electrode positions (number,x,y,z), checked against
                                      the BERT electrode file (guelpe_data.match_electrodes)
  context/cores.gpkg                  56 cores of Hein et al. (2026) (layer cores, table
                                      core_logs); EN-RK 40 and 46 have no published position
  context/core_logs_style.qml         the cores' style by stratigraphic unit
  erfurt_workbench.gpkg               workbench store: ERT02-ERT12, model + measured data each
  erfurt_project.qgz                  QGIS project (EPSG:32632), every path relative
  ATTRIBUTION.md                      sources and licences
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import numpy as np

import demo_extra
import erfurt_data
import guelpe_data

ROOT = Path(__file__).resolve().parent.parent
DEMO_ERFURT = ROOT / "demo_erfurt"
CACHE = ROOT / ".cache" / "erfurt"
SUPPLEMENT = "pone.0337410.s001.docx"
CRS = f"EPSG:{erfurt_data.EPSG}"
STORE_NAME = "erfurt_workbench.gpkg"
PROJECT_NAME = "erfurt_project.qgz"
#: station chainage against the model's electrode x (m). The total-station positions in the
#: forest scatter (neighbours 0.26-0.67 m apart for 0.5 m spacing; up to 0.62 m off on ERT04);
#: a wrong electrode match would shift every electrode by a spacing or more
MAX_CHAINAGE_MISFIT = 1.0
MEDIAN_CHAINAGE_MISFIT = 0.25
OSM_URI = "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0"
TITLE = "Geophysics Workbench real-data demo: Erfurt (Am Zoopark)"
REFERENCE = "Silbermann et al. 2025"
#: how the electrodes were positioned (PANGAEA abstract)
POSITIONING = {**{t: "electrode positions: total station (Leica TPS1200+)"
                  for t in ("ERT02", "ERT03", "ERT04", "ERT06", "ERT07")},
               **{t: "electrode positions: differential GPS (Leica GPS1200)"
                  for t in ("ERT11", "ERT12")}}
#: the plate shows the transect passing closest to the mass-grave cores EN-RK 55 and 56
PLATE_CORES = ("EN-RK 55", "EN-RK 56")
#: core log colours by stratigraphic unit, after the descriptions in Hein et al. (2026),
#: Suppl. Section 3 (a combined unit such as "SU2-SU5" takes its first unit's colour)
UNIT_COLOURS = {"SU1": "150,60,50", "SU2": "225,170,90", "SU3": "160,110,70",
                "SU4": "200,160,110", "SU5.1": "235,210,140", "SU5.2": "70,55,40",
                "SU6": "240,200,110", "SU7": "35,30,30"}

ATTRIBUTION = """# Sources and licences

This demo uses only open data. Files marked *derived* were converted from the source
without changing its values.

## Research data (CC BY 4.0, https://creativecommons.org/licenses/by/4.0/)
- **ERT**: Silbermann, M.; Pohle, M.; Jung, P.; Werban, U. (2025): 2D-ERT data for localizing
  a Black Death mass grave in Erfurt, Thuringia (Germany). PANGAEA,
  https://doi.org/10.1594/PANGAEA.974818.
  - `data/ert/ERT*/dcinv.result.vtk`: the authors' BERT 2.2.9 inversion results, unchanged;
  - `data/ert/ERT*/ERT*_measured.data`: the authors' BERT input data, unchanged;
  - `data/stations/*.csv`: their electrode positions (*derived*: reformatted).
  - Electrode positions: total station for ERT02-ERT07, differential GPS for ERT11 and ERT12
    (UTM zone 32N, as stated in the authors' explanation files).
- **Cores**: Hein, M. et al. (2026): What the landscape can tell: An integrative stratigraphic
  prospection approach to localize a Black Death mass grave in Erfurt/Central Germany.
  PLoS ONE 21(1): e0337410, https://doi.org/10.1371/journal.pone.0337410, Supporting
  Information S1 File, Suppl. Table 3. `context/cores.gpkg` (*derived*: depths converted from
  cm to m; stratigraphic units and properties in the authors' words). Cores EN-RK 40 and 46
  are listed there without coordinates and are left out. The cores have no published surface
  heights: on the sections they hang from the ERT topography.
- **Core colours** (`context/core_logs_style.qml`): chosen for this demo after the authors'
  unit descriptions; restyle them in Borehole style….

## OpenStreetMap (ODbL)
- The background map: © OpenStreetMap contributors, ODbL, https://www.openstreetmap.org/copyright
"""


# ---------------------------------------------------------------- data files
def build_data(cache: Path = CACHE, out: Path = DEMO_ERFURT) -> None:
    """Models, measured data, stations and cores from the cache (no QGIS)."""
    for sub in ("data", "context/cores.gpkg"):
        p = out / sub
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
    for name in erfurt_data.TRANSECTS:
        files = erfurt_data.transect_files(cache, name)
        target = out / "data" / "ert" / name
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy(files["model"], target / "dcinv.result.vtk")
        shutil.copy(files["topo"], target / f"{name}_measured.data")
        numbers, xyz = guelpe_data.read_dgps(files["dgps"])
        guelpe_data.match_electrodes(guelpe_data.read_topo_electrodes(files["topo"]), numbers,
                                     xyz, erfurt_data.SPACING)
        guelpe_data.write_stations_csv(out / f"data/stations/{name}_electrodes.csv",
                                       numbers, xyz)
    sites, logs = erfurt_data.parse_core_logs(erfurt_data.docx_paragraphs(cache / SUPPLEMENT))
    erfurt_data.write_cores_gpkg(out / "context/cores.gpkg", sites, logs)


def read_stations(path: Path) -> tuple[np.ndarray, np.ndarray]:
    a = np.loadtxt(path, delimiter=",", skiprows=1)
    return a[:, 0].astype(int), a[:, 1:4]


def dataset_infos(name: str, cache: Path = CACHE) -> dict[str, str]:
    """Dataset info of a transect's model, from the raw file and the published metadata."""
    files = erfurt_data.transect_files(cache, name)
    info = {"method": "ERT", "spacing": f"{erfurt_data.SPACING:g} m",
            "software": "BERT 2.2.9", "reference": REFERENCE, "note": POSITIONING[name]}
    info.update(erfurt_data.survey_info(files["raw"]))
    return info


def build_workbench(out: Path = DEMO_ERFURT, cache: Path = CACHE) -> Path:
    sys.path.insert(0, str(ROOT))
    from groundwork_geophysics import readers
    from groundwork_geophysics.core.dataset_info import with_info
    from groundwork_geophysics.core.model import (Dataset, file_fingerprint,
                                                 profile_from_stations, x_to_chainage)
    from groundwork_geophysics.store.gpkg_store import ProjectStore

    path = out / STORE_NAME
    path.unlink(missing_ok=True)
    store = ProjectStore.create(path, CRS)
    for name in erfurt_data.TRANSECTS:
        numbers, xyz = read_stations(out / f"data/stations/{name}_electrodes.csv")
        profile, stations = profile_from_stations(name, CRS, xyz, numbers)
        measured_rel = f"data/ert/{name}/{name}_measured.data"
        el = guelpe_data.read_topo_electrodes(out / measured_rel)
        matched = guelpe_data.match_electrodes(el, numbers, xyz, erfurt_data.SPACING)
        by_number = dict(zip(numbers, profile.chainage.project(xyz[:, :2])[0]))
        misfit = np.abs(np.array([by_number[n] for n in matched])
                        - x_to_chainage(el[:, 0], stations))
        if misfit.max() > MAX_CHAINAGE_MISFIT or np.median(misfit) > MEDIAN_CHAINAGE_MISFIT:
            raise RuntimeError(f"{name}: chainage misfit {misfit.max():.2f} m "
                               f"(median {np.median(misfit):.2f} m)")
        store.save_profile(profile)
        store.save_station_set(stations)
        info = dataset_infos(name, cache)
        rel = f"data/ert/{name}/dcinv.result.vtk"
        result = readers.read(out / rel, reader="vtk_legacy")
        mtime, sha1 = file_fingerprint(str(out / rel))
        store.save_dataset(with_info(Dataset(
            f"{name}_model", profile.id, stations.id, "ert_model", rel, mtime, sha1,
            "vtk_legacy", {"z_kind": "elevation", "chainage_offset": 0.0}, result.provenance,
            name=f"{name} model ({REFERENCE}, BERT)"), info))
        result = readers.read(out / measured_rel, reader="bert_data")
        mtime, sha1 = file_fingerprint(str(out / measured_rel))
        measured_info = {k: v for k, v in info.items() if k != "software"}
        store.save_dataset(with_info(Dataset(
            f"{name}_measured", profile.id, stations.id, "ert_measured", measured_rel, mtime,
            sha1, "bert_data", {"z_kind": "depth", "chainage_offset": 0.0}, result.provenance,
            name=f"{name} measured data"), measured_info))
    return path


# ---------------------------------------------------------------- QGIS project
def core_renderer(units: list[str]):
    """Categorised fill style of the core logs by stratigraphic unit (QGIS style)."""
    from qgis.core import QgsCategorizedSymbolRenderer, QgsFillSymbol, QgsRendererCategory
    cats = []
    for unit in sorted(units):
        first = unit.replace("/", "-").split("-")[0].strip()
        colour = UNIT_COLOURS.get(first, "200,200,200")
        cats.append(QgsRendererCategory(unit, QgsFillSymbol.createSimple(
            {"color": colour, "outline_color": "40,40,40", "outline_width": "0.1"}), unit))
    return QgsCategorizedSymbolRenderer("unit", cats)


def demo_context_settings(cores: str, logs: str):
    from groundwork_geophysics.core.context_settings import BoreholeSetting, ContextSettings
    return ContextSettings(
        line_layers=[], point_layers=[],
        boreholes=[BoreholeSetting(cores, "id", "", logs, "core_id", "top", "bottom", "unit",
                                   total_depth_field="depth", layer_text=True)],
        bands=[], dem_layer_id="", buffer=5.0, near_miss=10.0, dem_tolerance=0.5)


DEMO_DETAILS = {"project": "Erfurt demo", "client": "(example)", "job": "(example)",
                "date": "(example)", "author": "(example)", "revision": "–"}


def plate_profile(store, cores_gpkg: Path) -> str:
    """Id of the transect closest to the mass-grave cores."""
    from osgeo import ogr
    ds = ogr.Open(str(cores_gpkg))
    pts = [(f.GetGeometryRef().GetX(), f.GetGeometryRef().GetY())
           for f in ds.GetLayerByName("cores") if f.GetField("id") in PLATE_CORES]
    ds = None

    def distance(p):
        return min(abs(p.chainage.project(np.array([xy]))[1][0]) for xy in pts)
    return min(store.profiles(), key=distance).id


def demo_plate(profile_id: str, name: str):
    """A3 landscape: the transect's model, the cores and the interpretation."""
    from groundwork_geophysics.core.plates import FrameLook, FrameSpec, ModelLook, PlateSpec
    look = FrameLook([ModelLook(f"{name}_model")], None, boreholes=True, field_notes=True,
                     context=False)
    return PlateSpec("demo_plate_erfurt", "1", name, "A3_landscape",
                     [FrameSpec("demo_erfurt_model", profile_id, look)])


def add_demo_plate(project, store, cores_gpkg: Path) -> None:
    from groundwork_geophysics.plates.build import create_or_update_plate, set_plate_details
    from groundwork_geophysics.plates.sources import detach_frame_items, unregister_frame_sources
    from groundwork_geophysics.section.data import SectionDataProvider
    pid = plate_profile(store, cores_gpkg)
    set_plate_details(project, **DEMO_DETAILS)
    try:
        create_or_update_plate(project, store, SectionDataProvider(store),
                               demo_plate(pid, store.profile(pid).name))
    finally:
        detach_frame_items(project)
        unregister_frame_sources()


def build_qgis_project(out: Path = DEMO_ERFURT) -> Path:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT))
    from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsProject,
                           QgsRasterLayer, QgsRectangle, QgsReferencedRectangle, QgsVectorLayer)

    app = None
    if QgsApplication.instance() is None:
        app = QgsApplication([], False)
        app.initQgis()
    from build_demo_guelpe import _symbol
    from groundwork_geophysics.section.borehole_style import save_renderer
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
        md.setAbstract("Real, openly published data from Erfurt (Thuringia): seven ERT "
                       "transects and 56 sediment cores. Sources and licences: ATTRIBUTION.md "
                       "next to this project.")
        project.setMetadata(md)
        crs = QgsCoordinateReferenceSystem(CRS)
        project.setCrs(crs)
        project.writeEntryBool("Paths", "/Absolute", False)
        ctx = out / "context"
        cores = QgsVectorLayer(f"{ctx / 'cores.gpkg'}|layername=cores",
                               "Cores (Hein et al. 2026)", "ogr")
        _symbol(cores, "marker", {"name": "circle", "color": "255,255,255",
                                  "outline_color": "20,20,20", "size": "2.2"})
        demo_extra._labels(cores, '"id"', 7.0, (20, 20, 20))
        logs = QgsVectorLayer(f"{ctx / 'cores.gpkg'}|layername=core_logs", "Core logs", "ogr")
        osm = QgsRasterLayer(OSM_URI, "OpenStreetMap", "wms")
        for layer in (cores, logs, osm):
            if not layer.isValid():
                raise RuntimeError(f"demo layer {layer.name()} is not valid")
            project.addMapLayer(layer, False)
            project.layerTreeRoot().addLayer(layer)
        write_settings(project, demo_context_settings(cores.id(), logs.id()))
        units = sorted({f["unit"] for f in logs.getFeatures()})
        renderer = core_renderer(units)
        save_renderer(project, logs.id(), renderer)
        logs.setRenderer(renderer.clone())
        logs.saveNamedStyle(str(ctx / "core_logs_style.qml"))
        store = use_store(ProjectStore.open(out / STORE_NAME), project)
        add_demo_plate(project, store, ctx / "cores.gpkg")
        xy = np.vstack([p.xy for p in store.profiles()])
        (x0, y0), (x1, y1) = xy.min(axis=0) - 60.0, xy.max(axis=0) + 60.0
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
    return path


def main() -> int:
    """``--cache <folder>``: the downloads (default .cache/erfurt); ``--out <folder>``: build
    there instead of demo_erfurt/ (e.g. for a release zip)."""
    cache, out = CACHE, DEMO_ERFURT
    if "--cache" in sys.argv:
        cache = Path(sys.argv[sys.argv.index("--cache") + 1]).resolve()
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    (out / "context").mkdir(parents=True, exist_ok=True)
    build_data(cache=cache, out=out)
    build_workbench(out=out, cache=cache)
    build_qgis_project(out=out)
    (out / "ATTRIBUTION.md").write_text(ATTRIBUTION, encoding="utf-8", newline="\n")
    print(f"{out} built")
    return 0


if __name__ == "__main__":
    sys.exit(main())
