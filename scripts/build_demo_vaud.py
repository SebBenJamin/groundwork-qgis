"""Build the Vaud reflection demo (demo_vaud/) from the raw downloads in
.cache/demo_seismic/swisstopo/ (scripts/fetch_demo_vaud.py). Needs QGIS's Python and segyio
(looked for in .testlibs/ as the tests do).

Run: python-qgis.bat scripts/build_demo_vaud.py [--cache <folder>] [--out <folder>]

Writes under demo_vaud/ (or --out):
  data/VD-P760057_stack.sgy, data/VD-P760068_stack.sgy   the two stacks as swisstopo ships
                                                        them, renamed
  context/dem_swissalti3d_10m.tif   swissALTI3D resampled to 10 m, cut to 500 m each side of
                                    the lines (the ground line of both sections)
  vaud_groundwork.gpkg              store: one profile per line, made by Add Data from the
                                    file's own positions, with its section
  vaud_project.qgz                  QGIS project (EPSG:2056), every path relative
  ATTRIBUTION.md                    sources and licences

The build stops with a plain message unless both files read, both have positions in the
source fields that change, the two lines cross exactly once and both sections draw.
"""
from __future__ import annotations

import os
import shutil
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

import demo_extra
import vaud_data
from fetch_demo_vaud import CACHE, stack_path

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo_vaud"
CRS = vaud_data.CRS
STORE_NAME, PROJECT_NAME = "vaud_groundwork.gpkg", "vaud_project.qgz"
DEM_NAME = "dem_swissalti3d_10m.tif"
MAX_DEM_BYTES = 3_000_000
NODATA = -9999.0
VIEW_MARGIN = 1000.0            # m around both lines: the project's first map view
OSM_URI = "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0"
TITLE = "Groundwork real-data demo: Vaud (seismic reflection)"
LINK = "https://opendata.swiss/en/dataset/2d-und-3d-reflexionsseismik-in-der-schweiz"
VELOCITY_NOTE = ("The datum of 500 m and the average velocities come from the original section "
                 "sheet of VD-P760057 shipped by swisstopo (it also names the replacement "
                 "velocity of 4000 m/s that processing used to bring the data to the datum); "
                 "they are applied to VD-P760068 as an assumption. One velocity function, the "
                 "median of the sheet's five columns, is used for the whole line; the columns "
                 "differ by up to 12.5 % in the first 0.4 s and by less than 5 % below 1 s.")
DATUM_NOTE = ("The top of each section is at 500 m, so where the ground is higher the "
              "uppermost part of the ground is not in the data. Where the ground lies below "
              "500 m (the east end of VD-P760068), the section starts above the ground line.")
ATTRIBUTION = f"""# Sources and licences

This demo uses only open data. Files marked *derived* were made from the source.

## Seismic reflection (swisstopo, free use with source)
- **Stacks** (`data/VD-P760057_stack.sgy`, `data/VD-P760068_stack.sgy`): lines VD-P760057 and
  VD-P760068 from the dataset "2D and 3D reflection seismic in Switzerland",
  {LINK}
  Source: Federal Office of Topography swisstopo. The files are swisstopo's `*_stk-p.sgy`
  stacks, unchanged and renamed.
- The datum of 500 m and the average velocities come from the original section sheet of
  VD-P760057 (CGG, 1976), a scan that swisstopo ships with the line. The sheet also names a
  replacement velocity of 4000 m/s, which processing used to bring the data to the datum.
  VD-P760068 has no such sheet; it is from the same 1976 survey, and the demo applies the
  same values to it as an assumption.
- The sheet gives five velocity columns for different stretches of the line. The demo
  uses one function for the whole line: at each time the median of the five columns. The
  columns differ by up to 12.5 % in the first 0.4 s and by less than 5 % below 1 s.
- The top of each section is at 500 m, so where the ground is higher the uppermost part
  of the ground is not in the data. Where the ground lies below 500 m (the east end of
  VD-P760068), the section starts above the ground line: that strip is the processing's
  fill between ground and datum, not earth.

## Elevation (swisstopo, free use with source)
- `context/{DEM_NAME}` (*derived*: resampled to 10 m and cut to 500 m each side
  of the lines): swissALTI3D, 2 m tiles. Source: Federal Office of Topography swisstopo.

## OpenStreetMap (ODbL)
- The background map: © OpenStreetMap contributors, ODbL,
  https://www.openstreetmap.org/copyright
"""


class BuildStop(Exception):
    """A check failed: the build stops with this message."""


def _segy_ready() -> None:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / ".testlibs"))
    try:
        import segyio  # noqa: F401
    except ImportError:
        raise BuildStop("segyio is missing; see scripts/test.ps1 for putting it into "
                        ".testlibs/") from None


# ---------------------------------------------------------------- data files
def line_of(path: Path) -> np.ndarray:
    """The line through the file's trace positions (LV95), as Add Data makes it; BuildStop
    when the file does not read or its source positions do not change."""
    from groundwork_geophysics.core.lines import line_from_cloud
    from groundwork_geophysics.readers import segy
    try:
        segy.inspect(path)
        xy = segy.map_positions(path, vaud_data.OPTIONS)
    except (OSError, ValueError, RuntimeError) as exc:
        raise BuildStop(f"{path.name} does not read: {exc}") from None
    if len(np.unique(np.round(xy, 2), axis=0)) < 2:
        raise BuildStop(f"{path.name} has no positions in the source fields that change")
    try:
        return line_from_cloud(xy)[0]
    except ValueError as exc:
        raise BuildStop(f"{path.name}: {exc}") from None


def check_crossing(lines: dict[str, np.ndarray]) -> None:
    from groundwork_geophysics.core.context import line_crossings
    (a, xa), (b, xb) = lines.items()
    n = len(line_crossings(xa, xb, b))
    if n != 1:
        raise BuildStop(f"{a} and {b} cross {n} times (the demo needs exactly one crossing)")


def build_dem(lines: list[np.ndarray], target: Path, cache: Path) -> Path:
    """swissALTI3D at 10 m (average of the 2 m cells) in the corridor of ``lines``, no data
    outside it; BuildStop when a tile is missing or the file grows over 3 MB."""
    from osgeo import gdal
    gdal.UseExceptions()
    tiles = [cache / "swissalti3d" / f"{e}-{n}.tif" for e, n in vaud_data.tiles_near(lines)]
    missing = [t.name for t in tiles if not t.is_file()]
    if missing:
        raise BuildStop(f"swissALTI3D tiles missing in {cache}: {', '.join(missing[:5])}; "
                        f"run scripts/fetch_demo_vaud.py")
    x0, y0, x1, y1 = vaud_data.corridor_box(lines)
    vrt = gdal.BuildVRT("/vsimem/vaud_dem.vrt", [str(t) for t in tiles])
    mem = gdal.Warp("", vrt, format="MEM", outputBounds=(x0, y0, x1, y1),
                    xRes=vaud_data.PIXEL, yRes=vaud_data.PIXEL, resampleAlg="average",
                    outputType=gdal.GDT_Float32, dstNodata=NODATA)
    vrt = None
    gdal.Unlink("/vsimem/vaud_dem.vrt")
    band = mem.GetRasterBand(1)
    z = band.ReadAsArray().astype(np.float32)
    z[vaud_data.outside_corridor(mem.GetGeoTransform(), z.shape, lines)] = NODATA
    z = np.where(z == NODATA, NODATA, np.round(z, 2)).astype(np.float32)   # centimetres
    target.parent.mkdir(parents=True, exist_ok=True)
    out = gdal.GetDriverByName("GTiff").Create(
        str(target), z.shape[1], z.shape[0], 1, gdal.GDT_Float32,
        ["COMPRESS=DEFLATE", "PREDICTOR=3", "ZLEVEL=9", "TILED=YES"])
    out.SetGeoTransform(mem.GetGeoTransform())
    out.SetProjection(mem.GetProjection())
    ob = out.GetRasterBand(1)
    ob.SetNoDataValue(NODATA)
    ob.WriteArray(z)
    ob, out, mem = None, None, None
    size = target.stat().st_size
    if size > MAX_DEM_BYTES:
        raise BuildStop(f"{target.name} is {size:,} bytes (at most {MAX_DEM_BYTES:,})")
    return target


def build_data(cache: Path = CACHE, out: Path = DEMO) -> dict[str, np.ndarray]:
    """The stacks and the DEM under ``out``; returns each line's map line (no QGIS)."""
    for sub in ("data", f"context/{DEM_NAME}"):
        p = out / sub
        shutil.rmtree(p) if p.is_dir() else p.unlink(missing_ok=True)
    lines = {}
    for line in vaud_data.LINES:
        src = stack_path(line, cache)
        if src is None:
            raise BuildStop(f"no stack of {line} in {cache}; run scripts/fetch_demo_vaud.py")
        target = out / "data" / vaud_data.shipped_name(line)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, target)
        lines[line] = line_of(target)
    check_crossing(lines)
    build_dem(list(lines.values()), out / "context" / DEM_NAME, cache)
    return lines


# ---------------------------------------------------------------- store and QGIS project
def add_sections(store, project) -> None:
    """Each line as a user adds it: Add Data with a new profile through the file's own
    positions; the dataset is then named "<line> stack" and given its info, and the profile
    takes its ground from the DEM."""
    from groundwork_geophysics.core.dataset_info import with_info
    from groundwork_geophysics.core.lines import line_from_cloud
    from groundwork_geophysics.core.placement import Placement
    from groundwork_geophysics.readers import segy
    from groundwork_geophysics.ui.positions_source import xy_to_store
    from groundwork_geophysics.ui.project_actions import add_data

    for line in vaud_data.LINES:
        path = Path(store.path).parent / "data" / vaud_data.shipped_name(line)
        options = dict(vaud_data.OPTIONS)
        xy = xy_to_store(segy.map_positions(path, options), options["crs"], store.crs_authid,
                         project)
        placement = Placement(line_xy=line_from_cloud(xy)[0])
        try:
            profile, dataset = add_data(store, placement, path, "segy", options, line, "refl",
                                         project)
        except ValueError as exc:
            raise BuildStop(f"{path.name} does not read: {exc}") from None
        store.save_dataset(with_info(replace(dataset, name=f"{line} stack"), {
            "method": "Seismic reflection",
            "reference": "swisstopo, 2D and 3D reflection seismic in Switzerland",
            "note": f"{VELOCITY_NOTE} {DATUM_NOTE}"}))
        # the section's Topography choice set to the DEM, as a user picks it (no stations)
        profile = store.profile(profile.id)
        profile.metadata["topography"] = "dem"
        store.save_profile(profile)


def check_sections(store, project) -> None:
    """Both sections draw and each profile has its one crossing (with the project's DEM as
    the ground, as the plugin gathers it: a profile without heights shows no crossing)."""
    from groundwork_geophysics.section.context_layers import ContextGatherer
    from groundwork_geophysics.section.data import SectionDataProvider
    provider = SectionDataProvider(store)
    provider.context_source = ContextGatherer(project, store.crs_authid, lambda: None).items_for
    for p in store.profiles():
        surface = provider.surface(p.id)
        if surface is None or surface.kind != "dem":
            raise BuildStop(f"{p.name}: the DEM gives no ground line")
        layers = provider.layers(p.id)
        bad = [lyr.error for lyr in layers if lyr.error is not None]
        if len(layers) != 1 or bad:
            raise BuildStop(f"{p.name}: the section does not draw ({'; '.join(bad)})")
        n = len(provider.ties(p.id))
        if n != 1:
            raise BuildStop(f"{p.name} shows {n} crossings (the demo needs exactly one)")


def build_project(out: Path = DEMO) -> Path:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsHillshadeRenderer,
                           QgsProject, QgsRasterLayer, QgsRectangle, QgsReferencedRectangle)

    app = None
    if QgsApplication.instance() is None:
        app = QgsApplication([], False)
        app.initQgis()
    from groundwork_geophysics.core.context_settings import ContextSettings
    from groundwork_geophysics.ui.context_dialog import write_settings
    from groundwork_geophysics.ui.project_actions import new_store

    path = out / PROJECT_NAME
    path.unlink(missing_ok=True)
    (out / STORE_NAME).unlink(missing_ok=True)
    project = QgsProject()
    try:
        project.setFileName(str(path))
        project.setTitle(TITLE)
        demo_extra.set_author(project)
        md = project.metadata()
        md.setAbstract("Real, openly published seismic reflection stacks of two crossing lines "
                       "in the canton of Vaud (Switzerland), from swisstopo. "
                       f"{DATUM_NOTE} {VELOCITY_NOTE} Sources and licences: ATTRIBUTION.md "
                       "next to this project.")
        project.setMetadata(md)
        crs = QgsCoordinateReferenceSystem(CRS)
        project.setCrs(crs)
        project.writeEntryBool("Paths", "/Absolute", False)
        dem = QgsRasterLayer(str(out / "context" / DEM_NAME),
                             "Elevation swissALTI3D 10 m (swisstopo)", "gdal")
        osm = QgsRasterLayer(OSM_URI, "OpenStreetMap", "wms")
        for layer in (dem, osm):
            if not layer.isValid():
                raise BuildStop(f"demo layer {layer.name()} is not valid")
        dem.setRenderer(QgsHillshadeRenderer(dem.dataProvider(), 1, 315.0, 45.0))
        dem.elevationProperties().setEnabled(True)      # "Represents elevation surface"
        dem.setOpacity(0.6)
        root = project.layerTreeRoot()
        for layer in (dem, osm):
            project.addMapLayer(layer, False)
            root.addLayer(layer)
        write_settings(project, ContextSettings(dem_layer_id=dem.id(), buffer=25.0,
                                                near_miss=10.0, dem_tolerance=1.0))
        store = new_store(out / STORE_NAME, CRS, project)       # group on top
        add_sections(store, project)
        check_sections(store, project)
        xy = np.vstack([p.xy for p in store.profiles()])
        (x0, y0), (x1, y1) = xy.min(axis=0) - VIEW_MARGIN, xy.max(axis=0) + VIEW_MARGIN
        project.viewSettings().setDefaultViewExtent(
            QgsReferencedRectangle(QgsRectangle(x0, y0, x1, y1), crs))
        if not project.write():
            raise BuildStop(f"cannot write {path}: {project.error()}")
        demo_extra.strip_save_user(path)
    finally:
        project.clear()
        del project
        if app is not None:
            app.exitQgis()
    (out / "context" / f"{DEM_NAME}.aux.xml").unlink(missing_ok=True)
    for made in ("vaud_groundwork_3d", "vaud_groundwork_cache"):     # remade where needed
        shutil.rmtree(out / made, ignore_errors=True)
    return path


def _arg(name: str, default: Path) -> Path:
    if name in sys.argv:
        return Path(sys.argv[sys.argv.index(name) + 1]).resolve()
    return default


def main() -> int:
    """``--cache <folder>``: the downloads (default .cache/demo_seismic/swisstopo/);
    ``--out <folder>``: build there instead of demo_vaud/ (e.g. for a release zip)."""
    cache, out = _arg("--cache", CACHE), _arg("--out", DEMO)
    try:
        _segy_ready()
        out.mkdir(parents=True, exist_ok=True)
        build_data(cache=cache, out=out)
        build_project(out=out)
    except BuildStop as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    (out / "ATTRIBUTION.md").write_text(ATTRIBUTION, encoding="utf-8", newline="\n")
    print(f"{out} built")
    return 0


if __name__ == "__main__":
    # os._exit: QGIS/Qt teardown at interpreter shutdown can crash after a good build (as
    # scripts/test.ps1 notes), which would hide the build's own exit code
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
