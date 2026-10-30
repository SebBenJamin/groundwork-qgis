import time

import numpy as np
import pytest
from pytest import approx

AUTH = "EPSG:25832"


@pytest.fixture
def project(qgis_app):
    from qgis.core import QgsProject
    # QgsProject() kept alive in a fixture cache crashes QgsApplication.exitQgis
    proj = QgsProject.instance()
    proj.clear()
    yield proj
    proj.removeAllMapLayers()
    proj.clear()


@pytest.fixture
def profile():
    from geophysics_workbench.core.model import Profile
    return Profile("p1", "P1", np.array([[0.0, 0.0], [100.0, 0.0]]), AUTH)


def _layer(project, kind, name, fields="", crs=AUTH):
    from qgis.core import QgsVectorLayer
    uri = f"{kind}?crs={crs}" + (f"&field={fields}" if fields else "")
    layer = QgsVectorLayer(uri, name, "memory")
    assert layer.isValid()
    project.addMapLayer(layer)
    return layer


def _add(layer, wkt, attrs=()):
    from qgis.core import QgsFeature, QgsGeometry
    f = QgsFeature(layer.fields())
    if wkt:
        f.setGeometry(QgsGeometry.fromWkt(wkt))
    f.setAttributes(list(attrs))
    assert layer.dataProvider().addFeatures([f])[0]
    layer.updateExtents()


def _gatherer(project, settings, on_change=lambda: None):
    from geophysics_workbench.section.context_layers import ContextGatherer
    from geophysics_workbench.ui.context_dialog import write_settings
    write_settings(project, settings)
    return ContextGatherer(project, AUTH, on_change)


def test_powerline_crossing_with_voltage_label(project, profile):
    from geophysics_workbench.core.context_settings import ContextSettings, LineLayerSetting
    lines = _layer(project, "LineString", "Lines", "voltage:string")
    _add(lines, "LINESTRING(30 -50, 30 50)", ["380000"])
    _add(lines, "LINESTRING(500 -50, 500 50)", ["110000"])
    g = _gatherer(project, ContextSettings(line_layers=[
        LineLayerSetting(lines.id(), "voltage", True)]))
    try:
        items = g.items_for(profile)
    finally:
        g.close()
    assert len(items.crossings) == 1
    c = items.crossings[0]
    assert (c.label, c.kind) == ("380 kV", "powerline")
    assert c.s == approx(30) and c.angle_deg == approx(90)
    assert items.ties == [] and items.dem is None


def test_voltage_labels(project, profile):
    from geophysics_workbench.section.context_layers import voltage_label
    assert voltage_label("380000;110000") == "380 kV"
    assert voltage_label("110000") == "110 kV"
    assert voltage_label("20") == "20 kV"
    assert voltage_label("62500") == "62.5 kV"
    assert voltage_label("high") == "high"
    assert voltage_label("UW Nord 2") == "UW Nord 2"
    assert voltage_label(" 380000 ") == "380 kV"
    assert voltage_label("110000; 20000") == "110 kV"


def test_voltage_label_leaves_names_with_numbers_alone(project, profile):
    """R19c: only a plain number (or a ';' list of them) is a voltage, unless the field's
    name says it holds one."""
    from geophysics_workbench.section.context_layers import voltage_label
    assert voltage_label("4711 Nord") == "4711 Nord"
    assert voltage_label("4711 Nord", "name") == "4711 Nord"
    assert voltage_label("Leitung 380000") == "Leitung 380000"
    assert voltage_label("380 kV", "voltage") == "380 kV"
    assert voltage_label("110000 V", "Spannung_V") == "110 kV"
    assert voltage_label("high", "voltage") == "high"


def test_line_without_label_field_uses_layer_name(project, profile):
    from geophysics_workbench.core.context_settings import ContextSettings, LineLayerSetting
    lines = _layer(project, "LineString", "Road")
    _add(lines, "LINESTRING(10 -5, 10 5)")
    g = _gatherer(project, ContextSettings(line_layers=[LineLayerSetting(lines.id())]))
    items = g.items_for(profile)
    g.close()
    assert [(c.label, c.kind) for c in items.crossings] == [("Road", "line")]


def test_empty_multipoint_skips_only_that_feature(project, profile, monkeypatch):
    """R19e: an empty multipoint has no first point; that feature is skipped, the rest of
    the layer is kept. (QGIS' own providers mostly drop empty geometries at the bbox
    filter, so the features are fed in directly.)"""
    from qgis.core import QgsFeature, QgsGeometry
    from geophysics_workbench.core.context_settings import ContextSettings
    g = _gatherer(project, ContextSettings())
    try:
        empty, good, single = QgsFeature(), QgsFeature(), QgsFeature()
        feed = [(empty, QgsGeometry.fromWkt("MultiPoint EMPTY")),
                (good, QgsGeometry.fromWkt("MultiPoint((40 5), (41 5))")),
                (single, QgsGeometry.fromWkt("Point(60 -3)"))]
        monkeypatch.setattr(g, "_features", lambda layer, box, fields: iter(feed))
        found = g._point_features(None, None, ())
    finally:
        g.close()
    assert [(f is good or f is single, xy) for f, xy in found] == [(True, (40.0, 5.0)),
                                                                    (True, (60.0, -3.0))]


def test_points_in_other_crs_are_transformed(project, profile):
    from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsPointXY
    from geophysics_workbench.core.context_settings import ContextSettings, PointLayerSetting
    pts = _layer(project, "Point", "Pts", "name:string", crs="EPSG:4326")
    to_wgs = QgsCoordinateTransform(QgsCoordinateReferenceSystem(AUTH),
                                    QgsCoordinateReferenceSystem("EPSG:4326"), project)
    lon_lat = to_wgs.transform(QgsPointXY(500000.0 + 40, 5400000.0 + 5))
    _add(pts, f"POINT({lon_lat.x()} {lon_lat.y()})", ["tree"])
    from geophysics_workbench.core.model import Profile
    prof = Profile("p", "P", np.array([[500000.0, 5400000.0], [500100.0, 5400000.0]]), AUTH)
    g = _gatherer(project, ContextSettings(point_layers=[PointLayerSetting(pts.id(), "name")]))
    items = g.items_for(prof)
    g.close()
    assert len(items.points) == 1
    p = items.points[0]
    assert p.s == approx(40, abs=0.5) and p.offset == approx(5, abs=0.5)
    assert (p.label, p.kind) == ("tree", "point")


def test_borehole_with_log_table(project, profile):
    from geophysics_workbench.core.context_settings import BoreholeSetting, ContextSettings
    bh = _layer(project, "Point", "BH", "bid:string&field=elev:double")
    _add(bh, "POINT(40 3)", ["B1", 101.5])
    _add(bh, "POINT(40 300)", ["FAR", 99.0])
    log = _layer(project, "NoGeometry", "Log",
                 "bid:string&field=top:double&field=bot:double&field=lith:string")
    _add(log, None, ["B1", 4.0, 9.0, "clay"])
    _add(log, None, ["B1", 0.0, 4.0, "sand"])
    _add(log, None, ["B1", 9.0, 12.0, "gravel"])
    _add(log, None, ["OTHER", 0.0, 3.0, "peat"])
    g = _gatherer(project, ContextSettings(borehole=BoreholeSetting(
        bh.id(), "bid", "elev", log.id(), "bid", "top", "bot", "lith")))
    items = g.items_for(profile)
    g.close()
    assert len(items.points) == 1
    p = items.points[0]
    assert (p.kind, p.label, p.z_top) == ("borehole", "B1", approx(101.5))
    assert [(i.top, i.bottom, i.lithology) for i in p.log] == [
        (0.0, 4.0, "sand"), (4.0, 9.0, "clay"), (9.0, 12.0, "gravel")]
    assert p.s == approx(40) and p.offset == approx(3)


def test_band_from_polygon_layer(project, profile):
    from geophysics_workbench.core.context_settings import BandSetting, ContextSettings
    geo = _layer(project, "Polygon", "Geo", "unit:string")
    _add(geo, "POLYGON((60 -10, 100 -10, 100 10, 60 10, 60 -10))", ["Loess"])
    _add(geo, "POLYGON((0 -10, 60 -10, 60 10, 0 10, 0 -10))", ["Sand"])
    g = _gatherer(project, ContextSettings(band=BandSetting(geo.id(), "unit")))
    items = g.items_for(profile)
    g.close()
    assert [(b.label, round(b.s0), round(b.s1)) for b in items.band] == [
        ("Sand", 0, 60), ("Loess", 60, 100)]


def _write_dem(path, nodata_cols=range(40, 50)):
    from osgeo import gdal, osr
    with gdal.ExceptionMgr(useExceptions=True), osr.ExceptionMgr(useExceptions=True):
        return _write_dem_raw(path, nodata_cols, gdal, osr)


def _write_dem_raw(path, nodata_cols, gdal, osr):
    ds = gdal.GetDriverByName("GTiff").Create(str(path), 101, 3, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((-0.5, 1.0, 0, 1.5, 0, -1.0))     # pixel centres at integer x, y = 1, 0, -1
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(25832)
    ds.SetProjection(srs.ExportToWkt())
    arr = np.tile(100.0 + 0.1 * np.arange(101, dtype="float32"), (3, 1))
    arr[:, list(nodata_cols)] = -9999
    band = ds.GetRasterBand(1)
    band.SetNoDataValue(-9999)
    band.WriteArray(arr)
    ds.FlushCache()
    ds = None
    return arr


def test_dem_sampling_with_nodata(project, profile, tmp_path):
    from qgis.core import QgsRasterLayer
    from geophysics_workbench.core.context_settings import ContextSettings
    arr = _write_dem(tmp_path / "dem.tif")
    dem = QgsRasterLayer(str(tmp_path / "dem.tif"), "DEM")
    assert dem.isValid()
    project.addMapLayer(dem)
    g = _gatherer(project, ContextSettings(dem_layer_id=dem.id(), dem_tolerance=2.5))
    items = g.items_for(profile)
    g.close()
    s, z = items.dem
    assert s[0] == 0 and s[-1] == approx(100) and np.all(np.diff(s) > 0)
    assert len(s) == 101
    nodata = (s >= 40) & (s < 50)
    assert np.isnan(z[nodata]).all()
    np.testing.assert_allclose(z[~nodata], arr[1, np.round(s[~nodata]).astype(int)], atol=1e-6)
    assert items.dem_tolerance == 2.5


def test_dem_all_nodata_gives_none(project, profile, tmp_path):
    from qgis.core import QgsRasterLayer
    from geophysics_workbench.core.context_settings import ContextSettings
    _write_dem(tmp_path / "dem.tif", nodata_cols=range(101))
    dem = QgsRasterLayer(str(tmp_path / "dem.tif"), "DEM")
    project.addMapLayer(dem)
    g = _gatherer(project, ContextSettings(dem_layer_id=dem.id()))
    items = g.items_for(profile)
    g.close()
    assert items.dem is None


def test_borehole_without_elevation_uses_dem(project, profile, tmp_path):
    from qgis.core import QgsRasterLayer
    from geophysics_workbench.core.context_settings import BoreholeSetting, ContextSettings
    arr = _write_dem(tmp_path / "dem.tif")
    dem = QgsRasterLayer(str(tmp_path / "dem.tif"), "DEM")
    project.addMapLayer(dem)
    bh = _layer(project, "Point", "BH", "bid:string")
    _add(bh, "POINT(20 1)", ["B1"])
    g = _gatherer(project, ContextSettings(borehole=BoreholeSetting(bh.id(), "bid"),
                                           dem_layer_id=dem.id()))
    items = g.items_for(profile)
    g.close()
    assert items.points[0].z_top == approx(float(arr[0, 20]), abs=1e-4)
    assert items.points[0].log == []


def test_borehole_without_elevation_or_dem_has_no_z_top(project, profile):
    from geophysics_workbench.core.context_settings import BoreholeSetting, ContextSettings
    bh = _layer(project, "Point", "BH", "bid:string")
    _add(bh, "POINT(20 1)", ["B1"])
    g = _gatherer(project, ContextSettings(borehole=BoreholeSetting(bh.id(), "bid")))
    items = g.items_for(profile)
    g.close()
    assert items.points[0].z_top is None


def _capture_log(qgis_app):
    from qgis.core import QgsApplication
    got = []
    slot = lambda message, tag, level: got.append((message, tag, level))
    QgsApplication.messageLog().messageReceivedWithFormat.connect(slot)
    return got, lambda: QgsApplication.messageLog().messageReceivedWithFormat.disconnect(slot)


def test_missing_layer_and_field_are_skipped_with_log(project, profile, qgis_app):
    from qgis.core import Qgis
    from geophysics_workbench.core.context_settings import (BandSetting, ContextSettings,
                                                            LineLayerSetting)
    lines = _layer(project, "LineString", "Lines", "voltage:string")
    _add(lines, "LINESTRING(30 -50, 30 50)", ["380000"])
    good = _layer(project, "LineString", "Good")
    _add(good, "LINESTRING(60 -50, 60 50)")
    renamed = _layer(project, "Polygon", "Geo", "unit2:string")
    _add(renamed, "POLYGON((0 -10, 60 -10, 60 10, 0 10, 0 -10))", ["x"])
    got, stop = _capture_log(qgis_app)
    g = _gatherer(project, ContextSettings(
        line_layers=[LineLayerSetting("gone-id", "voltage", True),
                     LineLayerSetting(lines.id(), "voltage_old", True),
                     LineLayerSetting(good.id())],
        band=BandSetting(renamed.id(), "unit")))
    try:
        items = g.items_for(profile)
        n_first = len(got)
        g.items_for(profile)                      # the same problems are not logged again
    finally:
        stop()
        g.close()
    assert [(c.label, c.s) for c in items.crossings] == [("Good", approx(60))]
    assert items.band == []
    warnings = [m for m, tag, level in got if tag == "Geophysics Workbench"
                and level == Qgis.MessageLevel.Warning]
    assert len(warnings) == 3
    for needle in ("gone-id", "voltage_old", "'unit'"):
        assert sum(needle in w for w in warnings) == 1
    assert n_first == len(got)


def test_large_layer_uses_rect_filter_and_is_fast(project, profile, qgis_app):
    from geophysics_workbench.core.context import line_crossings
    from geophysics_workbench.core.context_settings import ContextSettings, LineLayerSetting
    rng = np.random.default_rng(7)
    layer = _layer(project, "LineString", "Many")
    from qgis.core import QgsFeature, QgsGeometry, QgsPointXY
    feats = []
    segs = []
    for k in range(20000):
        if k < 30:
            x, y = rng.uniform(0, 100), rng.uniform(-8, 8)
        else:
            x, y = rng.uniform(-5000, 5000), rng.uniform(-5000, 5000)
            if abs(y) < 200 and -100 < x < 200:
                y += 500
        a = rng.uniform(0, 2 * np.pi)
        p0, p1 = (x, y), (x + 20 * np.cos(a), y + 20 * np.sin(a))
        segs.append(np.array([p0, p1]))
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPolylineXY([QgsPointXY(*p0), QgsPointXY(*p1)]))
        feats.append(f)
    layer.dataProvider().addFeatures(feats)
    layer.updateExtents()
    expected = sorted(round(c.s, 6) for seg in segs
                      for c in line_crossings(profile.xy, seg, "Many", "line"))
    assert expected
    g = _gatherer(project, ContextSettings(line_layers=[LineLayerSetting(layer.id())]))
    t0 = time.perf_counter()
    items = g.items_for(profile)
    dt = time.perf_counter() - t0
    g.close()
    print(f"items_for on 20k lines: {dt:.3f} s")
    assert dt < 0.5
    assert sorted(round(c.s, 6) for c in items.crossings) == expected


def _wait(qgis_app, ms):
    end = time.perf_counter() + ms / 1000
    while time.perf_counter() < end:
        qgis_app.processEvents()
        time.sleep(0.01)


def test_change_triggers_on_change_once(project, profile, qgis_app):
    from geophysics_workbench.core.context_settings import ContextSettings, LineLayerSetting
    lines = _layer(project, "LineString", "Lines")
    calls = []
    g = _gatherer(project, ContextSettings(line_layers=[LineLayerSetting(lines.id())]),
                  lambda: calls.append(1))
    try:
        g.items_for(profile)
        lines.startEditing()
        for x in (10, 20, 30):
            _add_edit(lines, f"LINESTRING({x} -5, {x} 5)")
        _wait(qgis_app, 100)
        assert calls == []                        # debounced
        _wait(qgis_app, 500)
        assert calls == [1]
        _wait(qgis_app, 400)
        assert calls == [1]
    finally:
        g.close()
        lines.rollBack()


def _add_edit(layer, wkt):
    from qgis.core import QgsFeature, QgsGeometry
    f = QgsFeature(layer.fields())
    f.setGeometry(QgsGeometry.fromWkt(wkt))
    assert layer.addFeature(f)


def test_close_stops_notifications(project, profile, qgis_app):
    from geophysics_workbench.core.context_settings import ContextSettings, LineLayerSetting
    lines = _layer(project, "LineString", "Lines")
    calls = []
    g = _gatherer(project, ContextSettings(line_layers=[LineLayerSetting(lines.id())]),
                  lambda: calls.append(1))
    g.items_for(profile)
    g.close()
    lines.startEditing()
    _add_edit(lines, "LINESTRING(10 -5, 10 5)")
    _wait(qgis_app, 500)
    lines.rollBack()
    assert calls == []


def test_changed_settings_reconnect(project, profile, qgis_app):
    from geophysics_workbench.core.context_settings import ContextSettings, LineLayerSetting
    from geophysics_workbench.ui.context_dialog import write_settings
    a = _layer(project, "LineString", "A")
    b = _layer(project, "LineString", "B")
    calls = []
    g = _gatherer(project, ContextSettings(line_layers=[LineLayerSetting(a.id())]),
                  lambda: calls.append(1))
    try:
        g.items_for(profile)
        write_settings(project, ContextSettings(line_layers=[LineLayerSetting(b.id())]))
        g.items_for(profile)
        a.startEditing()
        _add_edit(a, "LINESTRING(10 -5, 10 5)")
        _wait(qgis_app, 500)
        assert calls == []                        # A is no longer watched
        b.startEditing()
        _add_edit(b, "LINESTRING(10 -5, 10 5)")
        _wait(qgis_app, 500)
        assert calls == [1]
    finally:
        g.close()
        a.rollBack()
        b.rollBack()


def test_removed_watched_layer_does_not_break_gatherer(project, profile, qgis_app):
    from geophysics_workbench.core.context_settings import ContextSettings, LineLayerSetting
    lines = _layer(project, "LineString", "Lines")
    calls = []
    g = _gatherer(project, ContextSettings(line_layers=[LineLayerSetting(lines.id())]),
                  lambda: calls.append(1))
    g.items_for(profile)
    project.removeMapLayer(lines.id())
    items = g.items_for(profile)
    assert items.crossings == []
    _wait(qgis_app, 500)
    assert calls == [1]                           # one refresh for the removal
    g.close()
    g.close()


def test_close_after_layer_removed_twice(project, profile, qgis_app):
    from geophysics_workbench.core.context_settings import ContextSettings, LineLayerSetting
    lines = _layer(project, "LineString", "Lines")
    g = _gatherer(project, ContextSettings(line_layers=[LineLayerSetting(lines.id())]))
    g.items_for(profile)
    project.removeMapLayer(lines.id())
    g.close()
    g.close()


def test_dem_outside_profile_logs_one_warning(project, profile, tmp_path, qgis_app):
    from osgeo import gdal
    from qgis.core import QgsRasterLayer
    from geophysics_workbench.core.context_settings import ContextSettings
    from geophysics_workbench.core.model import Profile
    _write_dem(tmp_path / "dem.tif")
    dem = QgsRasterLayer(str(tmp_path / "dem.tif"), "DEM")
    project.addMapLayer(dem)
    far = Profile("f", "F", np.array([[5000.0, 5000.0], [5100.0, 5000.0]]), AUTH)
    got, stop = _capture_log(qgis_app)
    g = _gatherer(project, ContextSettings(dem_layer_id=dem.id()))
    try:
        assert g.items_for(far).dem is None
        g.items_for(far)
    finally:
        stop()
        g.close()
    dem_warnings = [m for m, tag, _l in got if tag == "Geophysics Workbench" and "DEM" in m]
    assert len(dem_warnings) == 1


def test_null_elevation_falls_back_to_dem(project, profile, tmp_path):
    from qgis.core import QgsRasterLayer
    from geophysics_workbench.core.context_settings import BoreholeSetting, ContextSettings
    arr = _write_dem(tmp_path / "dem.tif")
    dem = QgsRasterLayer(str(tmp_path / "dem.tif"), "DEM")
    project.addMapLayer(dem)
    bh = _layer(project, "Point", "BH", "bid:string&field=elev:double")
    _add(bh, "POINT(20 1)", ["B1", None])
    g = _gatherer(project, ContextSettings(borehole=BoreholeSetting(bh.id(), "bid", "elev"),
                                           dem_layer_id=dem.id()))
    items = g.items_for(profile)
    g.close()
    assert items.points[0].z_top == approx(float(arr[0, 20]), abs=1e-4)
