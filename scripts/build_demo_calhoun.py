"""Build the Calhoun refraction demo (demo_calhoun/) from the raw downloads in .cache/calhoun/
(scripts/fetch_demo_calhoun.py) and the inversion results in scripts/data/calhoun/
(scripts/invert_calhoun.py). Needs QGIS's Python.

Run: python-qgis.bat scripts/build_demo_calhoun.py [--out <folder>]

Writes under demo_calhoun/:
  data/refraction/L<n>/L<n>_xzv.txt, L<n>_topography.txt   Vp models in Refrainv's layout
  data/stations/L<n>_geophones.csv     geophones (number,x,y,z) placed along the authors'
                                       UTM points (calhoun_data.stations_xy)
  context/dem_3dep.tif                 USGS 3DEP 1 m elevation
  calhoun_groundwork.gpkg              store: Line 6, 10, 11, 12, one Vp model each
  calhoun_project.qgz                  QGIS project (EPSG:32617), every path relative
  ATTRIBUTION.md                       sources and licences
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np

import calhoun_data
import demo_extra
from fetch_demo_calhoun import CACHE, RESOURCE

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo_calhoun"
RESULTS = ROOT / "scripts" / "data" / "calhoun"
CRS = "EPSG:32617"
STORE_NAME, PROJECT_NAME = "calhoun_groundwork.gpkg", "calhoun_project.qgz"
MAX_CHAINAGE_MISFIT = 0.5       # m, station chainage against the model file's metres
OSM_URI = "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0"
TITLE = "Groundwork real-data demo: Calhoun CZO (seismic refraction)"
PLATE_LINE = "L10"
ATTRIBUTION = f"""# Sources and licences

This demo uses only open data. Files marked *derived* were made from the source.

## Seismic refraction (CC BY 4.0)
- **Picks, line positions**: Flinchum, B. A.: Supporting Data Repository: Landscape Curvature
  and Deep Critical Zone Structure. HydroShare,
  http://www.hydroshare.org/resource/{RESOURCE}. Calhoun Critical Zone Observatory, South
  Carolina, USA. Licence: CC BY 4.0, https://creativecommons.org/licenses/by/4.0/
- **Vp models** (`data/refraction/`, *derived*): re-inverted from the authors' expert first-
  arrival picks of lines 6, 10, 11 and 12 with pyGIMLi 1.2.6 as Refrapy's Refrainv runs it
  (scripts/invert_calhoun.py: every 2nd geophone, 60 m deep, lambda 100, z weight 0.1),
  saved in Refrainv's file layout. They are not the authors' published models.
- **Geophones** (`data/stations/`, *derived*): the geophone positions of the pick files,
  placed along the authors' UTM points of each line (allBR.txt), whose surface matches the
  line's elevation file.

## USGS 3DEP (public domain)
- `context/dem_3dep.tif` (*derived*: cut to the lines + 150 m): U.S. Geological Survey, 3D
  Elevation Program 1 m DEM, from the 3DEP elevation image service.

## OpenStreetMap (ODbL)
- The background map: © OpenStreetMap contributors, ODbL,
  https://www.openstreetmap.org/copyright
"""


# ---------------------------------------------------------------- data files
def _line_name(code: str) -> str:
    return f"Line {code[1:]}"


def build_data(out: Path = DEMO) -> dict[str, tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """Models, stations and DEM; returns each line's ``(xyz, numbers, inline)`` (no QGIS)."""
    for sub in ("data", "context/dem_3dep.tif"):
        p = out / sub
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
    pieces = calhoun_data.read_pieces(CACHE / "allBR.txt")
    stations = {}
    for code, (piece, _picks, _elev) in calhoun_data.LINES.items():
        line = calhoun_data.read_line(*calhoun_data.line_files(CACHE, code))
        k, offset, rms = calhoun_data.match_piece(line, pieces)
        if k != piece or rms > calhoun_data.MAX_RMS:
            raise RuntimeError(f"{code}: matches piece {k} with {rms:.2f} m RMS "
                               f"(expected piece {piece}, at most {calhoun_data.MAX_RMS} m)")
        xyz, numbers, inline = calhoun_data.stations_xy(line, pieces[k], offset)
        stations[code] = (xyz, numbers, inline)
        folder = out / "data" / "refraction" / code
        folder.mkdir(parents=True, exist_ok=True)
        for suffix in ("_xzv.txt", "_topography.txt"):
            shutil.copy(RESULTS / f"{code}{suffix}", folder / f"{code}{suffix}")
        csv = out / "data" / "stations" / f"{code}_geophones.csv"
        csv.parent.mkdir(parents=True, exist_ok=True)
        np.savetxt(csv, np.column_stack([numbers, xyz]), delimiter=",",
                   fmt=["%d", "%.3f", "%.3f", "%.2f"], header="number,x,y,z", comments="")
    (out / "context").mkdir(parents=True, exist_ok=True)
    shutil.copy(CACHE / "dem_3dep.tif", out / "context" / "dem_3dep.tif")
    return stations


# ---------------------------------------------------------------- workbench store
def build_workbench(stations: dict, out: Path = DEMO) -> Path:
    sys.path.insert(0, str(ROOT))
    from groundwork_geophysics import readers
    from groundwork_geophysics.core.dataset_info import with_info
    from groundwork_geophysics.core.model import (Dataset, file_fingerprint,
                                                 profile_from_positions, x_to_chainage)
    from groundwork_geophysics.core.placement import Positions
    from groundwork_geophysics.store.gpkg_store import ProjectStore

    path = out / STORE_NAME
    path.unlink(missing_ok=True)
    store = ProjectStore.create(path, CRS)
    for code, (xyz, numbers, inline) in stations.items():
        name = _line_name(code)
        profile, st = profile_from_positions(name, CRS, Positions(xyz, numbers, inline),
                                             method="srt")
        # the section pins the model by the stations' in-line metres: their spacing along the
        # line must be the file's (station 1 need not be at file metre 0)
        s_station = profile.chainage.project(xyz[:, :2])[0]
        misfit = np.abs((s_station - s_station[0])
                        - (x_to_chainage(inline, st) - x_to_chainage(inline[:1], st)))
        if misfit.max() > MAX_CHAINAGE_MISFIT:
            raise RuntimeError(f"{name}: chainage misfit {misfit.max():.2f} m")
        store.save_profile(profile)
        store.save_station_set(st)
        rel = f"data/refraction/{code}/{code}_xzv.txt"
        result = readers.read(out / rel, reader="refrapy_xzv")
        run = json.loads((RESULTS / f"{code}_pygimli.json").read_text())
        provenance = dict(result.provenance, rms_percent=run["relrms_percent"])
        mtime, sha1 = file_fingerprint(str(out / rel))
        d = Dataset(f"{code}_model", profile.id, st.id, "srt_model", rel, mtime, sha1,
                    "refrapy_xzv", {"z_kind": "elevation", "chainage_offset": 0.0},
                    provenance, name=f"{name} Vp (Flinchum et al. picks, pyGIMLi as Refrainv)",
                    quantity=result.mesh.quantity, unit=result.mesh.unit)
        store.save_dataset(with_info(d, {
            "method": "Seismic refraction", "spacing": "2 m",
            "software": "pyGIMLi as Refrapy's Refrainv",
            "reference": "picks: Flinchum, HydroShare"}))
    return path


# ---------------------------------------------------------------- QGIS project
def demo_plate(profile_id: str, dataset_id: str):
    """A3 landscape: Line 10's Vp model, faded where Refrainv counts it unresolved."""
    from groundwork_geophysics.core.plates import FrameLook, FrameSpec, ModelLook, PlateSpec
    look = FrameLook([ModelLook(dataset_id, fade_coverage=True)], None, boreholes=False,
                     field_notes=False, context=False)
    return PlateSpec("demo_plate_l10", "1", "Line 10", "A3_landscape",
                     [FrameSpec("demo_l10_model", profile_id, look)])


def add_demo_plate(project, store) -> None:
    from groundwork_geophysics.plates.build import create_or_update_plate, set_plate_details
    from groundwork_geophysics.plates.sources import detach_frame_items, unregister_frame_sources
    from groundwork_geophysics.section.data import SectionDataProvider
    [p] = [p for p in store.profiles() if p.name == _line_name(PLATE_LINE)]
    set_plate_details(project, project="Calhoun demo", client="(example)", job="(example)",
                      date="(example)", author="(example)", revision="–")
    try:
        create_or_update_plate(project, store, SectionDataProvider(store),
                               demo_plate(p.id, f"{PLATE_LINE}_model"))
    finally:
        detach_frame_items(project)
        unregister_frame_sources()


def build_qgis_project(out: Path = DEMO) -> Path:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT))
    from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsHillshadeRenderer,
                           QgsProject, QgsRasterLayer, QgsRectangle, QgsReferencedRectangle)

    app = None
    if QgsApplication.instance() is None:
        app = QgsApplication([], False)
        app.initQgis()
    from groundwork_geophysics.core.context_settings import ContextSettings
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
        md.setAbstract("Real, openly published seismic refraction data from the Calhoun "
                       "Critical Zone Observatory (South Carolina, USA). Sources and "
                       "licences: ATTRIBUTION.md next to this project.")
        project.setMetadata(md)
        crs = QgsCoordinateReferenceSystem(CRS)
        project.setCrs(crs)
        project.writeEntryBool("Paths", "/Absolute", False)
        dem = QgsRasterLayer(str(out / "context" / "dem_3dep.tif"), "Elevation 3DEP 1 m (USGS)",
                             "gdal")
        osm = QgsRasterLayer(OSM_URI, "OpenStreetMap", "wms")
        for layer in (dem, osm):
            if not layer.isValid():
                raise RuntimeError(f"demo layer {layer.name()} is not valid")
        dem.setRenderer(QgsHillshadeRenderer(dem.dataProvider(), 1, 315.0, 45.0))
        dem.setOpacity(0.6)
        root = project.layerTreeRoot()
        for layer in (dem, osm):
            project.addMapLayer(layer, False)
            root.addLayer(layer)
        write_settings(project, ContextSettings(dem_layer_id=dem.id(), buffer=5.0,
                                                near_miss=10.0, dem_tolerance=0.5))
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
    (out / "context" / "dem_3dep.tif.aux.xml").unlink(missing_ok=True)
    return path


def main() -> int:
    """``--out <folder>`` builds there instead of demo_calhoun/ (e.g. for a release zip)."""
    out = DEMO
    if "--out" in sys.argv:
        out = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stations = build_data(out=out)
    build_workbench(stations, out=out)
    build_qgis_project(out=out)
    (out / "ATTRIBUTION.md").write_text(ATTRIBUTION, encoding="utf-8", newline="\n")
    print(f"{out} built")
    return 0


if __name__ == "__main__":
    sys.exit(main())
