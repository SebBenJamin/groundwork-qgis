"""LAS logs written as one curve table (id, depth, one column per curve) in a GeoPackage,
in the form Context Layers' curve tables read."""
from pathlib import Path

import numpy as np
import pytest

LAS = Path(__file__).resolve().parent.parent / "fixtures" / "las"


def _rows(gpkg, table):
    from osgeo import ogr
    ds = ogr.Open(str(gpkg))
    lyr = ds.GetLayerByName(table)
    names = [lyr.GetLayerDefn().GetFieldDefn(i).GetName()
             for i in range(lyr.GetLayerDefn().GetFieldCount())]
    rows = [{n: f.GetField(n) for n in names} for f in lyr]
    return names, rows


def test_two_wells_in_one_table(qgis_app, tmp_path):
    from groundwork_geophysics.core.las_log import read_las_log
    from groundwork_geophysics.store.las_table import write_las_table
    gpkg = tmp_path / "p.gpkg"
    feet, wrapped = read_las_log(LAS / "bh1_feet.las"), read_las_log(LAS / "wrapped_metres.las")
    table, curves = write_las_table(gpkg, [("JW11", feet, 0.6096), ("B7", wrapped, 0.0)])
    assert table == "las_curves"
    assert curves == [("gr", "GAPI"), ("res", "OHMM"), ("sp", "MV"), ("cali", "IN"),
                      ("cond", "MS/M")]
    names, rows = _rows(gpkg, table)
    assert names[:2] == ["id", "depth"]
    jw = [r for r in rows if r["id"] == "JW11"]
    # 10 ft = 3.048 m in the file, the ground 2 ft (0.6096 m) below its zero
    assert jw[0]["depth"] == pytest.approx(3.048 - 0.6096)
    assert jw[0]["gr"] == 45.0 and jw[1]["res"] is None and jw[0]["sp"] is None
    assert [r["cond"] for r in rows if r["id"] == "B7"] == [30.0, 31.0]


def test_a_second_import_makes_a_second_table(qgis_app, tmp_path):
    from groundwork_geophysics.core.las_log import read_las_log
    from groundwork_geophysics.store.las_table import write_las_table
    gpkg = tmp_path / "p.gpkg"
    log = read_las_log(LAS / "no_name.las")
    assert write_las_table(gpkg, [("A", log, 0.0)])[0] == "las_curves"
    assert write_las_table(gpkg, [("B", log, 0.0)])[0] == "las_curves_2"


def test_the_same_curve_in_another_unit_gets_its_own_column(qgis_app, tmp_path):
    from groundwork_geophysics.core.las_log import LasCurve, LasLog
    from groundwork_geophysics.store.las_table import write_las_table
    a = LasLog(depth=np.array([1.0]), curves=[LasCurve("GR", "GAPI", "", np.array([5.0]))])
    b = LasLog(depth=np.array([1.0]), curves=[LasCurve("GR", "CPS", "", np.array([90.0]))])
    _t, curves = write_las_table(tmp_path / "p.gpkg", [("A", a, 0), ("B", b, 0)])
    assert curves == [("gr", "GAPI"), ("gr_cps", "CPS")]


def test_reserved_and_odd_mnemonics_become_plain_field_names(qgis_app, tmp_path):
    from groundwork_geophysics.core.las_log import LasCurve, LasLog
    from groundwork_geophysics.store.las_table import write_las_table
    log = LasLog(depth=np.array([1.0]),
                 curves=[LasCurve("ID", "", "", np.array([1.0])),
                         LasCurve("RES-DEEP:1", "OHMM", "", np.array([2.0]))])
    _t, curves = write_las_table(tmp_path / "p.gpkg", [("A", log, 0)])
    assert [c for c, _u in curves] == ["id_log", "res_deep_1"]


def test_two_files_of_one_well_share_rows_at_the_same_depth(qgis_app, tmp_path):
    """A well logged in two runs (e.g. caliper, then gamma + resistivity) on the same depth
    grid: one row per depth with both curves, so neither curve breaks into dots."""
    from groundwork_geophysics.core.las_log import LasCurve, LasLog
    from groundwork_geophysics.store.las_table import write_las_table
    cal = LasLog(well="W", depth=np.array([1.0, 1.5, 2.0]),
                 curves=[LasCurve("CALI", "IN", "", np.array([6.0, 6.1, 6.2]))])
    gam = LasLog(well="W", depth=np.array([1.5, 2.0, 2.5]),
                 curves=[LasCurve("GR", "API", "", np.array([50.0, np.nan, 70.0]))])
    gpkg = tmp_path / "p.gpkg"
    table, _curves = write_las_table(gpkg, [("W1", cal, 0.0), ("W1", gam, 0.0)])
    _names, rows = _rows(gpkg, table)
    got = [(r["depth"], r["cali"], r["gr"]) for r in rows]
    assert got == [(1.0, 6.0, None), (1.5, 6.1, 50.0), (2.0, 6.2, None), (2.5, None, 70.0)]
