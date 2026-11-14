"""Offline, deterministic generator for the demo data (seed 42).

Reads demo/context/powerline.geojson (fetch_demo_context.py) and writes, under demo/data/:
  ert/P1/f001_res.dat       R2/ResIPy centroids, elevation z
  ert/P2/P2_model.dat       ZondRes2D model, depth header
  ert/P2/P2_model_it2.dat   second "iteration" of P2 (other noise seed, sharper edges)
  ert/P3/f001_res.vtk       legacy ASCII VTK quads
  stations/P{1,2,3,4}_electrodes.csv number,x,y,z (P4: station file only, see demo_extra.py)
under demo/context/ the synthetic context (pylons, boreholes, geology, DEM: demo_context.py),
and, under demo/ (with the plugin's own code, so it needs QGIS's Python):
  demo_workbench.gpkg       workbench store: P1-P3, station sets, one model each (P1, P2 with
                            a typed station spacing of 5 m); model source paths are relative
                            to the store's folder
  demo_project.qgz          QGIS project (EPSG:25832): OSM tiles, powerline, context layers and
                            settings, workbench group; every path relative, so the demo works
                            wherever it is unpacked
The clay bodies and the earthing artefact are defined in map coordinates (demo_context.py).

Small functions (geometry, topography, model, writers, main) that later milestones can extend.
Re-running reproduces byte-identical text files, context/boreholes.gpkg and context/dem.tif
(demo_workbench.gpkg / .qgz carry fresh ids and timestamps).
"""
from __future__ import annotations

import json
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import demo_context
import demo_extra

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
CONTEXT = DEMO / "context"
POWERLINE = CONTEXT / "powerline.geojson"
DATA = DEMO / "data"
CRS = "EPSG:25832"
STORE_NAME, PROJECT_NAME = "demo_workbench.gpkg", "demo_project.qgz"
#: profile -> (model path relative to demo/, reader, z_kind)
DEMO_MODELS = {"P1": ("data/ert/P1/f001_res.dat", "r2_res_dat", "elevation"),
               "P2": ("data/ert/P2/P2_model.dat", "zondres_xyz", "depth"),
               "P3": ("data/ert/P3/f001_res.vtk", "vtk_legacy", "elevation")}
OSM_URI = "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0"
SEED = 42
SPACING = 5.0                        # electrode spacing (m)
#: profiles stored with a typed station spacing: their row models are pinned to the stations
#: by it (the guess from the model's 2.5 m cells would not fit and is not used)
TYPED_SPACING = ("P1", "P2")
ANCHOR = (437791.67, 5850874.70)     # near a straight stretch of the fetched powerline (EPSG:25832)
BASE_ELEVATION = 60.0                # m a.s.l.
LAYER_RHO = {"topsoil": 80.0, "till": 30.0, "sandstone": 450.0}
TOPSOIL_THICKNESS = 1.5


@dataclass(frozen=True)
class Profile:
    name: str
    x0: float
    y0: float
    azimuth: float          # direction of increasing s, radians, math convention (from +x, ccw)
    length: float

    @property
    def n_electrodes(self) -> int:
        return int(round(self.length / SPACING)) + 1

    @property
    def depth(self) -> float:
        return self.length / 5.0

    def xy(self, s):
        s = np.asarray(s, dtype=float)
        return self.x0 + s * math.cos(self.azimuth), self.y0 + s * math.sin(self.azimuth)


# ---------------------------------------------------------------- geometry
def load_powerline_frame(path: Path = POWERLINE):
    """Point on the powerline nearest ANCHOR plus the unit tangent there (local direction)."""
    gj = json.loads(Path(path).read_text(encoding="utf-8"))
    pts = np.array([c[:2] for f in gj["features"] for c in f["geometry"]["coordinates"]], float)
    dist = np.hypot(pts[:, 0] - ANCHOR[0], pts[:, 1] - ANCHOR[1])
    i = int(np.argmin(dist))
    if dist[i] > 50.0:
        raise ValueError(f"ANCHOR is {dist[i]:.0f} m from the nearest powerline vertex in {path} "
                         "(max 50 m); the powerline was probably re-fetched - update ANCHOR in build_demo.py")
    a, b = pts[max(i - 1, 0)], pts[min(i + 1, len(pts) - 1)]
    d = (b - a) / np.hypot(*(b - a))
    return pts[i], d


def _rot(v, deg):
    t = math.radians(deg)
    return np.array([v[0] * math.cos(t) - v[1] * math.sin(t), v[0] * math.sin(t) + v[1] * math.cos(t)])


def make_profiles(path: Path = POWERLINE) -> list[Profile]:
    """P1/P2: parallel, 150 m apart along the powerline, crossing it at 75 deg.
    P3 crosses both, 70 m to one side of the powerline."""
    anchor, d = load_powerline_frame(path)
    u = _rot(d, 75.0)                         # P1/P2 direction
    v = _rot(d, -15.0)                        # P3 direction
    out = []
    for name, off, length in (("P1", -75.0, 235.0), ("P2", 75.0, 355.0)):
        cross = anchor + d * off              # where the profile meets the powerline
        start = cross - u * (0.4 * length)
        out.append(Profile(name, start[0], start[1], math.atan2(u[1], u[0]), length))
    m = anchor + u * 70.0
    length3 = 295.0
    start = m - v * (0.5 * length3)
    out.append(Profile("P3", start[0], start[1], math.atan2(v[1], v[0]), length3))
    return out


def intersection(p: Profile, q: Profile):
    """(s_p, s_q) where the two profile lines cross, or None if they do not cross."""
    a = np.array([math.cos(p.azimuth), math.sin(p.azimuth)])
    b = np.array([math.cos(q.azimuth), math.sin(q.azimuth)])
    rhs = np.array([q.x0 - p.x0, q.y0 - p.y0])
    mat = np.array([[a[0], -b[0]], [a[1], -b[1]]])
    if abs(np.linalg.det(mat)) < 1e-9:
        return None
    sp, sq = np.linalg.solve(mat, rhs)
    if 0 <= sp <= p.length and 0 <= sq <= q.length:
        return float(sp), float(sq)
    return None


# ---------------------------------------------------------------- topography
def ground_elevation(x, y):
    """Smooth synthetic terrain, a function of world x,y: within +-6 m of BASE_ELEVATION."""
    xr, yr = np.asarray(x, float) - ANCHOR[0], np.asarray(y, float) - ANCHOR[1]
    return (BASE_ELEVATION
            + 3.5 * np.sin(2 * np.pi * (0.8 * xr + 0.6 * yr) / 420.0 + 0.7)
            + 2.5 * np.sin(2 * np.pi * (-0.5 * xr + 0.87 * yr) / 260.0 + 2.1))


# ---------------------------------------------------------------- model
def bedrock_depth(x, y):
    """Undulating bedrock top below the surface, 8-16 m, a function of world x,y."""
    xr, yr = np.asarray(x, float) - ANCHOR[0], np.asarray(y, float) - ANCHOR[1]
    return (12.0 + 3.0 * np.sin(2 * np.pi * (0.9 * xr + 0.4 * yr) / 190.0 + 0.3)
            + 1.0 * np.sin(2 * np.pi * (-0.3 * xr + 0.95 * yr) / 85.0 + 1.4))


def synthetic_resistivity(s, depth, seed=42, xy=None, bodies=(), edge=0.5, noise=0.10):
    """Resistivity (ohm.m) at profile distance ``s`` and depth below the surface ``depth``.

    ``xy`` = (x, y) world coordinates of the points (same shape as ``s``); the layers and the
    ``bodies`` (demo_context.Body, in map coordinates) depend on them, so crossing profiles
    agree. Without ``xy`` the profile is taken along +x.
    ``edge`` is the width (m) of the smooth transitions; ``noise`` the log-normal sigma.
    """
    s = np.asarray(s, float)
    depth = np.asarray(depth, float)
    x, y = (s + ANCHOR[0], np.full_like(s, ANCHOR[1])) if xy is None else (np.asarray(xy[0], float),
                                                                           np.asarray(xy[1], float))
    w1 = 0.5 * (1 + np.tanh((depth - TOPSOIL_THICKNESS) / edge))        # 0 topsoil, 1 below
    w2 = 0.5 * (1 + np.tanh((depth - bedrock_depth(x, y)) / edge))      # 0 till, 1 sandstone
    lg = ((1 - w1) * np.log10(LAYER_RHO["topsoil"])
          + w1 * ((1 - w2) * np.log10(LAYER_RHO["till"]) + w2 * np.log10(LAYER_RHO["sandstone"])))
    lg = demo_context.blend(lg, x, y, depth, bodies, edge)
    rng = np.random.default_rng(seed)
    lg = lg + rng.normal(0.0, noise, size=s.shape) / math.log(10)       # 10 % log-normal noise
    return 10.0 ** lg


def layer_edges(total_depth: float, first=0.5, growth=1.1) -> np.ndarray:
    """Layer boundaries below the surface, thickness growing x1.1 from 0.5 m, ending at total_depth."""
    edges, t = [0.0], first
    while edges[-1] + t < total_depth - 0.5 * t:
        edges.append(edges[-1] + t)
        t *= growth
    edges.append(total_depth)
    return np.array(edges)


@dataclass
class Grid:
    s_edges: np.ndarray
    d_edges: np.ndarray
    s_c: np.ndarray      # (nl, nc) cell centre s
    d_c: np.ndarray      # (nl, nc) cell centre depth
    rho: np.ndarray      # (nl, nc)


def build_model(p: Profile, bodies=(), seed=SEED, edge=0.5, col_width=2.5) -> Grid:
    s_edges = np.linspace(0.0, p.length, int(round(p.length / col_width)) + 1)
    d_edges = layer_edges(p.depth)
    s_mid = 0.5 * (s_edges[:-1] + s_edges[1:])
    d_mid = 0.5 * (d_edges[:-1] + d_edges[1:])
    s_c, d_c = np.meshgrid(s_mid, d_mid)
    rho = synthetic_resistivity(s_c, d_c, seed=seed, xy=p.xy(s_c), bodies=bodies, edge=edge)
    return Grid(s_edges, d_edges, s_c, d_c, rho)


# ---------------------------------------------------------------- writers
def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(text.encode("utf-8"))


def _elev(p: Profile, s):
    return ground_elevation(*p.xy(s))


def write_r2(path: Path, p: Profile, g: Grid) -> None:
    z = _elev(p, g.s_c) - g.d_c
    rows = [f"{a:.3f}\t{b:.3f}\t{c:.2f}\t{math.log10(c):.4f}"
            for a, b, c in zip(g.s_c.ravel(), z.ravel(), g.rho.ravel())]
    _write(path, "\n".join(rows) + "\n")


def write_zond(path: Path, p: Profile, g: Grid) -> None:
    rows = ["#X\tDepth\tlog_Rho\tRho"]
    rows += [f"{a:.3f}\t{b:.3f}\t{math.log10(c):.4f}\t{c:.2f}"
             for a, b, c in zip(g.s_c.ravel(), g.d_c.ravel(), g.rho.ravel())]
    _write(path, "\n".join(rows) + "\n")


def write_vtk(path: Path, p: Profile, g: Grid) -> None:
    ns, nd = len(g.s_edges), len(g.d_edges)
    zs = _elev(p, g.s_edges)
    lines = ["# vtk DataFile Version 3.0", f"{p.name} synthetic ERT model", "ASCII",
             "DATASET UNSTRUCTURED_GRID", f"POINTS {ns * nd} float"]
    for k in range(nd):
        for i in range(ns):
            lines.append(f"{g.s_edges[i]:.4f}\t0.0000\t{zs[i] - g.d_edges[k]:.4f}")
    nc = (ns - 1) * (nd - 1)
    lines.append(f"CELLS {nc} {5 * nc}")
    for k in range(nd - 1):
        for i in range(ns - 1):
            a = k * ns + i
            lines.append(f"4 {a} {a + 1} {a + 1 + ns} {a + ns}")
    lines.append(f"CELL_TYPES {nc}")
    lines += ["9"] * nc
    lines += [f"CELL_DATA {nc}", "SCALARS Resistivity(ohm.m) float", "LOOKUP_TABLE default"]
    lines += [f"{v:.4f}" for v in g.rho.ravel()]
    _write(path, "\n".join(lines) + "\n")


def station_table(p: Profile):
    s = np.arange(p.n_electrodes) * SPACING
    x, y = p.xy(s)
    return s, x, y, ground_elevation(x, y)


def write_stations(path: Path, p: Profile) -> None:
    _, x, y, z = station_table(p)
    rows = ["number,x,y,z"] + [f"{i + 1},{a:.2f},{b:.2f},{c:.2f}"
                               for i, (a, b, c) in enumerate(zip(x, y, z))]
    _write(path, "\n".join(rows) + "\n")


# ---------------------------------------------------------------- workbench project
def read_stations(path: Path):
    """(numbers, xyz) from a station CSV written by write_stations."""
    arr = np.loadtxt(path, delimiter=",", skiprows=1, ndmin=2)
    return arr[:, 0].astype(int), arr[:, 1:4]


def _remove(path: Path) -> None:
    for p in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        p.unlink(missing_ok=True)


def build_workbench(demo_dir: Path = DEMO) -> Path:
    """demo_workbench.gpkg: one profile per station file, one model dataset per profile."""
    sys.path.insert(0, str(ROOT))
    from geophysics_workbench import readers
    from geophysics_workbench.core.model import Dataset, file_fingerprint, profile_from_stations
    from geophysics_workbench.store.gpkg_store import ProjectStore

    path = demo_dir / STORE_NAME
    _remove(path)
    store = ProjectStore.create(path, CRS)
    for name, (rel, reader, z_kind) in DEMO_MODELS.items():
        numbers, xyz = read_stations(demo_dir / f"data/stations/{name}_electrodes.csv")
        profile, stations = profile_from_stations(name, CRS, xyz, numbers)
        if name in TYPED_SPACING:               # as typed in Profile Properties
            profile.metadata["electrode_spacing"] = SPACING
        store.save_profile(profile)
        store.save_station_set(stations)
        src = demo_dir / rel
        result = readers.read(src, reader=reader)
        mtime, sha1 = file_fingerprint(str(src))
        store.save_dataset(Dataset(f"{name}_model", profile.id, stations.id, "ert_model", rel,
                                   mtime, sha1, reader,
                                   {"z_kind": z_kind, "chainage_offset": 0.0},
                                   result.provenance, name=f"{name} {Path(rel).name}"))
    return path


def build_qgis_project(demo_dir: Path = DEMO) -> Path:
    """demo_project.qgz next to the store; needs QGIS (creates a QgsApplication if none)."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT))
    from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem, QgsProject,
                           QgsRasterLayer, QgsRectangle, QgsReferencedRectangle)

    app = None
    if QgsApplication.instance() is None:
        app = QgsApplication([], False)
        app.initQgis()
    from geophysics_workbench.store.gpkg_store import ProjectStore
    from geophysics_workbench.ui.project_actions import use_store

    path = demo_dir / PROJECT_NAME
    path.unlink(missing_ok=True)
    project = QgsProject()
    try:
        project.setFileName(str(path))           # before use_store: store path goes relative
        project.setTitle("Geophysics Workbench demo")
        demo_extra.set_author(project)            # not the account running the build
        crs = QgsCoordinateReferenceSystem(CRS)
        project.setCrs(crs)
        project.writeEntryBool("Paths", "/Absolute", False)
        root = project.layerTreeRoot()
        osm = QgsRasterLayer(OSM_URI, "OpenStreetMap", "wms")
        powerline = demo_extra.powerline_layer(demo_dir / "context" / "powerline.geojson")
        for layer in (osm, powerline):
            if not layer.isValid():
                raise RuntimeError(f"demo layer {layer.name()} is not valid")
            project.addMapLayer(layer, False)
        root.addLayer(osm)                        # bottom
        root.insertLayer(0, powerline)
        demo_extra.add_context(project, demo_dir / "context", powerline)   # layers + settings
        store = use_store(ProjectStore.open(demo_dir / STORE_NAME), project)   # group on top
        xy = np.vstack([p.xy for p in store.profiles()])
        (x0, y0), (x1, y1) = xy.min(axis=0) - 120.0, xy.max(axis=0) + 120.0
        project.viewSettings().setDefaultViewExtent(
            QgsReferencedRectangle(QgsRectangle(x0, y0, x1, y1), crs))
        if not project.write():
            raise RuntimeError(f"cannot write {path}: {project.error()}")
        demo_extra.strip_save_user(path)          # QGIS writes the OS account and full name
    finally:
        project.clear()
        del project
        if app is not None:
            app.exitQgis()
    (demo_dir / "context" / "dem.tif.aux.xml").unlink(missing_ok=True)   # QGIS's DEM statistics
    return path


# ---------------------------------------------------------------- main
def build_all(data_dir: Path = DATA, context_dir: Path = CONTEXT):
    """Models, station files and the synthetic context; returns (profiles, bodies, where the
    earthing artefact went)."""
    profiles = {p.name: p for p in make_profiles()}
    p1, p2, p3 = profiles["P1"], profiles["P2"], profiles["P3"]
    profiles["P4"] = p4 = demo_extra.make_p4(p1, p3)     # station file only (walkthrough)
    for a, b in ((p1, p3), (p2, p3), (p1, p4), (p2, p4)):
        if intersection(a, b) is None:
            raise RuntimeError(f"{a.name} and {b.name} do not cross")
    powerline = demo_context.load_line(POWERLINE)
    extent = demo_context.demo_extent(profiles.values())
    masts = demo_context.pylons(powerline, extent)
    bodies, where = demo_context.make_bodies(profiles, powerline, masts)
    write_r2(data_dir / "ert/P1/f001_res.dat", p1, build_model(p1, bodies))
    write_zond(data_dir / "ert/P2/P2_model.dat", p2, build_model(p2, bodies))
    write_zond(data_dir / "ert/P2/P2_model_it2.dat", p2,
               build_model(p2, bodies, seed=SEED + 1, edge=0.25))
    write_vtk(data_dir / "ert/P3/f001_res.vtk", p3, build_model(p3, bodies))
    for p in profiles.values():
        write_stations(data_dir / f"stations/{p.name}_electrodes.csv", p)
    demo_context.write_context(context_dir, profiles, bodies, masts, extent, ground_elevation,
                               bedrock_depth, TOPSOIL_THICKNESS, ANCHOR)
    return profiles, bodies, where


def main() -> int:
    profiles, bodies, where = build_all()
    for p in profiles.values():
        print(p.name, f"start=({p.x0:.2f}, {p.y0:.2f}) azimuth={math.degrees(p.azimuth):.1f} deg "
                      f"length={p.length:.0f} m electrodes={p.n_electrodes}")
    for a, b in (("P1", "P3"), ("P2", "P3"), ("P1", "P4"), ("P2", "P4")):
        print(f"{a}x{b}: s=", intersection(profiles[a], profiles[b]))
    for body in bodies:
        print(f"body {body.name}: ({body.x:.2f}, {body.y:.2f}) depth {body.depth} m, "
              f"{body.rho} ohm.m")
    print("earthing artefact:", where)
    print("wrote", build_workbench().relative_to(ROOT).as_posix())
    print("wrote", build_qgis_project().relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())