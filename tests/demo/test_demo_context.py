"""Demo context (0.2.0): pylons, boreholes, geology, DEM and clay bodies in map coordinates.

The demo story: one clay body (A) under the P1 x P3 tie that both profiles see, a second one
(B) on P2, an earthing artefact by the powerline on P1, boreholes that agree with the model,
and a road embankment on P2 that the GPS station heights missed."""
import json
import sys
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent.parent
DEMO = REPO / "demo"
CONTEXT = DEMO / "context"
sys.path.insert(0, str(REPO / "scripts"))

UNITS = {"Geschiebelehm (Grundmoräne)", "Talsand", "Niedermoortorf", "Flugsand"}
CLAY_MAX = 15.0               # ohm.m: a clay body or the earthing artefact
DEM_EXACT = 0.1               # m: DEM - station height away from the embankment


@pytest.fixture(scope="module")
def demo():
    import build_demo
    return build_demo


@pytest.fixture(scope="module")
def profiles(demo):
    import demo_extra
    out = {p.name: p for p in demo.make_profiles()}
    out["P4"] = demo_extra.make_p4(out["P1"], out["P3"])
    return out


def _line(p) -> np.ndarray:
    return np.column_stack(p.xy(np.array([0.0, p.length])))


def _model(name):
    from geophysics_workbench import readers
    rel = {"P1": "ert/P1/f001_res.dat", "P2": "ert/P2/P2_model.dat", "P3": "ert/P3/f001_res.vtk"}
    return readers.read(DEMO / "data" / rel[name])


def _rho_at(demo, p, mesh, s, depth) -> float:
    """Model value at chainage ``s`` and ``depth`` below the surface (elevation or depth mesh)."""
    z_top = float(demo.ground_elevation(*p.xy(s)))
    return mesh.value_at(s, z_top - depth)


def _powerline() -> np.ndarray:
    gj = json.loads((CONTEXT / "powerline.geojson").read_text(encoding="utf-8"))
    return np.array(gj["features"][0]["geometry"]["coordinates"], float)[:, :2]


def _boreholes():
    from osgeo import ogr
    with ogr.ExceptionMgr(useExceptions=True):          # scoped: no global GDAL state
        return _boreholes_raw(ogr)


def _boreholes_raw(ogr):
    ds = ogr.Open(str(CONTEXT / "boreholes.gpkg"))
    points = {f.GetField("id"): (f.GetField("name"), f.GetGeometryRef().GetX(),
                                 f.GetGeometryRef().GetY(), f.GetField("elevation"))
              for f in ds.GetLayerByName("boreholes")}
    logs = {}
    for f in ds.GetLayerByName("borehole_logs"):
        logs.setdefault(f.GetField("borehole_id"), []).append(
            (f.GetField("top"), f.GetField("bottom"), f.GetField("lithology")))
    assert ds.GetLayerByName("borehole_logs").GetGeomType() == ogr.wkbNone
    return points, {k: sorted(v) for k, v in logs.items()}


# -- clay bodies and the earthing artefact ----------------------------------------------------
def test_body_a_seen_on_both_profiles_at_tie(demo, profiles):
    from geophysics_workbench.core.context import profile_ties

    [(s1, s3, dist)] = profile_ties(_line(profiles["P1"]), _line(profiles["P3"]), 10.0)
    assert dist == 0.0
    p1 = _rho_at(demo, profiles["P1"], _model("P1").mesh, s1, 5.0)
    p3 = _rho_at(demo, profiles["P3"], _model("P3").mesh, s3, 5.0)
    assert p1 < CLAY_MAX and p3 < CLAY_MAX
    assert abs(np.log10(p1) - np.log10(p3)) < 0.2           # the same body, within the noise
    # and it is a body, not a layer: 40 m along P3 the till is back
    assert _rho_at(demo, profiles["P3"], _model("P3").mesh, s3 + 40.0, 5.0) > 20.0


def test_body_b_on_p2_where_the_lens_was(demo, profiles):
    mesh = _model("P2").mesh                                 # depth model: z = depth
    assert mesh.value_at(71.0, 5.0) < 10.0
    assert mesh.value_at(140.0, 5.0) > 20.0


def test_earthing_artefact_near_powerline_on_p1(demo, profiles):
    from geophysics_workbench.core.context import line_crossings, project_points

    p1 = profiles["P1"]
    [crossing] = line_crossings(_line(p1), _powerline(), "380 kV", "powerline")
    pylons = json.loads((CONTEXT / "pylons.geojson").read_text(encoding="utf-8"))
    near = project_points(_line(p1), np.array([f["geometry"]["coordinates"]
                                               for f in pylons["features"]]), 20.0)
    s_expected = min(near, key=lambda h: abs(h[2]))[1] if near else crossing.s
    mesh = _model("P1").mesh
    assert _rho_at(demo, p1, mesh, s_expected, 1.5) < CLAY_MAX      # radius 4 m, 0-3 m deep
    assert _rho_at(demo, p1, mesh, s_expected, 0.25) < 40.0
    for ds in (-15.0, 15.0):                                        # small: topsoil around it
        assert _rho_at(demo, p1, mesh, s_expected + ds, 1.0) > 40.0
    assert _rho_at(demo, p1, mesh, s_expected, 6.0) > 15.0          # nothing deep below it


# -- pylons -----------------------------------------------------------------------------------
def test_pylons_are_powerline_vertices_ordered_along_the_line():
    gj = json.loads((CONTEXT / "pylons.geojson").read_text(encoding="utf-8"))
    assert gj["crs"]["properties"]["name"] == "urn:ogc:def:crs:EPSG::25832"
    vertices = [tuple(v) for v in _powerline()]
    pts = [tuple(f["geometry"]["coordinates"]) for f in gj["features"]]
    assert pts and all(p in vertices for p in pts)
    assert [vertices.index(p) for p in pts] == sorted(vertices.index(p) for p in pts)
    assert [f["properties"]["name"] for f in gj["features"]] == [
        f"Mast {i}" for i in range(1, len(pts) + 1)]


# -- boreholes --------------------------------------------------------------------------------
def test_boreholes_and_logs_consistent_with_model(demo, profiles):
    points, logs = _boreholes()
    assert sorted(points) == ["B1", "B2", "B3", "B4"] and sorted(logs) == sorted(points)
    for bid, (name, x, y, elevation) in points.items():
        assert name and elevation == pytest.approx(float(demo.ground_elevation(x, y)), abs=0.01)
        log = logs[bid]
        assert log[0] == (0.0, 0.3, "Mutterboden") and log[1][2] == "Sand"
        assert log[-1][1] == 25.0 and log[-1][2] == "Fels (verwittert)"
        assert all(a[1] == b[0] for a, b in zip(log, log[1:]))          # no gaps
        assert {r[2] for r in log} <= {"Mutterboden", "Sand", "Ton", "Geschiebelehm",
                                       "Fels (verwittert)"}
    assert any(r[2] == "Ton" for r in logs["B1"])                     # through Body A
    assert any(r[2] == "Ton" for r in logs["B3"])                     # 8 m off P1, in Body A
    assert not any(r[2] == "Ton" for r in logs["B2"])
    # B1 stands on the P1 x P3 tie: every interval of its log matches P1's model there
    p1 = profiles["P1"]
    s, off = _project(p1, points["B1"][1:3])
    assert abs(off) < 0.01
    mesh = _model("P1").mesh
    expect = {"Sand": (40, 200), "Ton": (0, CLAY_MAX), "Geschiebelehm": (15, 60),
              "Fels (verwittert)": (150, 2000)}
    for top, bottom, lith in logs["B1"]:
        if lith in expect and bottom - top >= 1.0:
            lo, hi = expect[lith]
            assert lo < _rho_at(demo, p1, mesh, s, 0.5 * (top + bottom)) < hi, (top, bottom, lith)


def _project(p, xy):
    from geophysics_workbench.core.context import project_points
    [(_i, s, off)] = project_points(_line(p), np.array([xy]), 1e6)
    return s, off


def test_borehole_placement(profiles):
    points, _logs = _boreholes()
    for bid, name, near_s, offset in (("B2", "P2", 200.0, 12.0), ("B3", "P1", 180.0, 8.0),
                                      ("B4", "P3", None, 30.0)):
        s, off = _project(profiles[name], points[bid][1:3])
        assert abs(off) == pytest.approx(offset, abs=0.01), bid
        if near_s is not None:
            assert s == pytest.approx(near_s, abs=1.0), bid


def test_b4_outside_default_buffer(profiles):
    from geophysics_workbench.core.context import project_points

    points, _logs = _boreholes()
    b4 = np.array([points["B4"][1:3]])
    for name in ("P1", "P2", "P3"):
        assert project_points(_line(profiles[name]), b4, 25.0) == [], name
    assert len(project_points(_line(profiles["P3"]), b4, 35.0)) == 1   # raise the buffer: there
    for bid, names in (("B1", ("P1", "P3")), ("B2", ("P2",)), ("B3", ("P1",))):
        for name in names:
            assert project_points(_line(profiles[name]), np.array([points[bid][1:3]]), 25.0), \
                (bid, name)


# -- geology ----------------------------------------------------------------------------------
def test_geology_crossed_by_every_profile(profiles):
    from geophysics_workbench.core.context import polygon_intervals

    gj = json.loads((CONTEXT / "geology.geojson").read_text(encoding="utf-8"))
    assert {f["properties"]["unit"] for f in gj["features"]} == UNITS
    polygons, labels = [], []
    for f in gj["features"]:
        assert f["geometry"]["type"] == "MultiPolygon"
        for poly in f["geometry"]["coordinates"]:
            polygons.append((np.array(poly[0]), [np.array(h) for h in poly[1:]]))
            labels.append(f["properties"]["unit"])
    for name in ("P1", "P2", "P3"):
        band = polygon_intervals(_line(profiles[name]), polygons, labels)
        assert len({b.label for b in band}) >= 2, name
        covered = sum(b.s1 - b.s0 for b in band)                    # no gaps, no overlaps
        assert covered == pytest.approx(profiles[name].length, abs=0.05), name


# -- DEM --------------------------------------------------------------------------------------
def _stations(name):
    arr = np.loadtxt(DEMO / "data" / "stations" / f"{name}_electrodes.csv", delimiter=",",
                     skiprows=1, ndmin=2)
    return arr[:, 1:4]


def test_dem_embankment_on_p2(qgis_app, profiles):
    from qgis.core import QgsRasterLayer

    from geophysics_workbench.section.dem_sampling import sample_point

    layer = QgsRasterLayer(str(CONTEXT / "dem.tif"), "dem", "gdal")
    assert layer.isValid() and layer.crs().authid() == "EPSG:25832"
    assert layer.rasterUnitsPerPixelX() == 2.0 and layer.rasterUnitsPerPixelY() == 2.0
    ext = layer.extent()
    xy = np.vstack([_line(p) for n, p in profiles.items() if n != "P4"])
    assert ext.xMinimum() <= xy[:, 0].min() - 100 and ext.xMaximum() >= xy[:, 0].max() + 100
    assert ext.yMinimum() <= xy[:, 1].min() - 100 and ext.yMaximum() >= xy[:, 1].max() + 100

    def diff(name):
        st = _stations(name)
        return np.array([sample_point(layer, x, y, "EPSG:25832") - z for x, y, z in st])

    d2 = diff("P2")
    s2 = np.arange(len(d2)) * 5.0
    on = np.abs(s2 - 252.5) < 6.0
    assert on.sum() >= 2 and np.allclose(d2[on], 2.0, atol=0.3)       # missed by the GPS
    assert np.abs(d2[~on]).max() <= DEM_EXACT
    for name in ("P1", "P3", "P4"):                                   # the road misses them
        assert np.abs(diff(name)).max() <= DEM_EXACT, name


# -- QGIS project -----------------------------------------------------------------------------
def _qgs_text() -> str:
    with zipfile.ZipFile(DEMO / "demo_project.qgz") as zf:
        [qgs] = [n for n in zf.namelist() if n.endswith(".qgs")]
        return zf.read(qgs).decode("utf-8")


def test_project_has_context_settings_and_relative_paths(qgis_app):
    from qgis.core import QgsProject

    from geophysics_workbench.core.context_settings import ContextSettings

    root = ET.fromstring(_qgs_text())
    assert root.get("saveUser", "") == "" and root.get("saveUserFull", "") == ""
    layers = {ml.findtext("id"): (ml.findtext("layername"), ml.findtext("datasource"))
              for ml in root.iter("maplayer")}
    for name, source in layers.values():
        if name != "OpenStreetMap":
            assert source.startswith("./"), (name, source)
    entry = root.find("properties/properties[@name='geophysics_workbench']"
                      "/properties[@name='context']")         # QGIS 4 project XML
    assert entry is not None
    s = ContextSettings.from_json(entry.text)
    by_name = {name: lid for lid, (name, _src) in layers.items()}
    assert [(x.layer_id, x.label_field, x.powerline) for x in s.line_layers] == [
        (by_name["Powerline (OSM)"], "voltage", True)]
    assert [(x.layer_id, x.label_field) for x in s.point_layers] == [
        (by_name["Pylons (from OSM)"], "name")]
    b = s.borehole
    assert (b.layer_id, b.id_field, b.elevation_field) == (by_name["Boreholes"], "id",
                                                           "elevation")
    assert (b.log_layer_id, b.log_id_field, b.top_field, b.bottom_field, b.lithology_field) == (
        by_name["Borehole logs"], "borehole_id", "top", "bottom", "lithology")
    assert (s.band.layer_id, s.band.label_field) == (by_name["Surface geology (synthetic)"],
                                                     "unit")
    assert s.dem_layer_id == by_name["DEM (synthetic)"]
    assert (s.buffer, s.near_miss, s.dem_tolerance) == (25.0, 10.0, 1.0)

    prj = QgsProject()
    assert prj.read(str(DEMO / "demo_project.qgz"))
    geology = prj.mapLayer(by_name["Surface geology (synthetic)"])
    assert geology.opacity() == pytest.approx(0.4)
    renderer = geology.renderer()
    assert renderer.type() == "categorizedSymbol" and renderer.classAttribute() == "unit"
    from geophysics_workbench.core.lithology import lithology_colour
    assert {c.value(): c.symbol().color().getRgb()[:3] for c in renderer.categories()} == {
        u: lithology_colour(u) for u in UNITS}
    tree = prj.layerTreeRoot()
    assert not tree.findLayer(by_name["DEM (synthetic)"]).isVisible()
    assert prj.mapLayer(by_name["Borehole logs"]).isSpatial() is False
    assert all(prj.mapLayer(lid).isValid() for lid in by_name.values())


# -- determinism ------------------------------------------------------------------------------
def test_rebuild_is_deterministic(demo, tmp_path):
    """Rebuilding reproduces the committed text files byte for byte, the DEM pixel for pixel
    and the borehole tables row for row."""
    from osgeo import gdal

    data, context = tmp_path / "data", tmp_path / "context"
    demo.build_all(data, context)
    for rel in ("ert/P1/f001_res.dat", "ert/P2/P2_model.dat", "ert/P2/P2_model_it2.dat",
                "ert/P3/f001_res.vtk", *(f"stations/P{i}_electrodes.csv" for i in range(1, 5))):
        assert (data / rel).read_bytes() == (DEMO / "data" / rel).read_bytes(), rel
    for rel in ("pylons.geojson", "geology.geojson"):
        assert (context / rel).read_bytes() == (CONTEXT / rel).read_bytes(), rel
    from osgeo import ogr
    with gdal.ExceptionMgr(useExceptions=True), ogr.ExceptionMgr(useExceptions=True):
        new, old = gdal.Open(str(context / "dem.tif")), gdal.Open(str(CONTEXT / "dem.tif"))
        assert new.GetGeoTransform() == old.GetGeoTransform()
        np.testing.assert_array_equal(new.ReadAsArray(), old.ReadAsArray())
        new = old = None

        def rows(path):
            ds = ogr.Open(str(path))
            out = {name: [(f.items(), f.GetGeometryRef().ExportToWkt() if f.GetGeometryRef()
                           else None) for f in ds.GetLayerByName(name)]
                   for name in ("boreholes", "borehole_logs")}
            return out
        assert rows(context / "boreholes.gpkg") == rows(CONTEXT / "boreholes.gpkg")
