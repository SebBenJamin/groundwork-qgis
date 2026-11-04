"""Gülpe raw-data converters (no QGIS)."""
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
FIX = REPO / "tests" / "fixtures" / "guelpe"

from guelpe_data import (lithology, match_electrodes, mosaic_dgm, parse_cores,  # noqa: E402
                         read_dgps, read_topo_electrodes, write_cores_gpkg)


def FIXTURE(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_lithology_rules():
    assert lithology("St2", "sand", "", "") == "sand · St2"
    assert lithology("Ss (mS)", "sand", "", "") == "sand · Ss (mS)"
    assert lithology("Lt3", "", "", "") == "Lt3"
    assert lithology("", "", "offset", "") is None
    assert lithology("", "", "highly decomposed peat", "H") == "peat"
    assert lithology("", "", "", "Hn") == "peat"
    assert lithology("", "", "", "Oh") == "Oh"


def test_parse_cores_sparse_rows():
    sites, logs = parse_cores(FIXTURE("cores_snippet.tab"))
    assert [s.id for s in sites] == ["RK1", "RK5", "RK10"]
    rk1 = next(s for s in sites if s.id == "RK1")
    assert rk1.transect == "Guelpe_2023_transect-1" and rk1.elevation == 24.4
    assert 311000 < rk1.x < 313000 and 5845000 < rk1.y < 5847000
    assert all(b > t for rows in logs.values() for t, b, _ in rows)
    assert len(logs["RK10"]) == 3                        # the depth-less row is skipped


def test_offset_rows_dropped_depths_kept():
    _, logs = parse_cores(FIXTURE("cores_snippet.tab"))
    assert logs["RK1"][0] == (0.22, 0.30, "Oh")          # 0.00-0.22 offset dropped, not shifted
    assert logs["RK1"][1] == (0.30, 0.41, "clay · Tu3")
    assert "peat" in [lith for _, _, lith in logs["RK5"]]


def test_match_electrodes_with_gaps():
    numbers, xyz = read_dgps(FIX / "dgps_gap.txt")
    el = read_topo_electrodes(FIX / "topo_gap.data")
    assert list(match_electrodes(el, numbers, xyz, 0.5)) == [1, 2, 4, 5, 6]


def test_match_electrodes_rejects_height_mismatch():
    numbers, xyz = read_dgps(FIX / "dgps_gap.txt")
    el = read_topo_electrodes(FIX / "topo_gap.data")
    el[0, 1] += 0.1
    with pytest.raises(ValueError):
        match_electrodes(el, numbers, xyz, 0.5)


def test_cores_gpkg_roundtrip(tmp_path):
    from osgeo import ogr
    sites, logs = parse_cores(FIXTURE("cores_snippet.tab"))
    path = tmp_path / "cores.gpkg"
    write_cores_gpkg(path, sites, logs)
    ds = ogr.Open(str(path))
    pts, table = ds.GetLayerByName("cores"), ds.GetLayerByName("core_logs")
    assert pts.GetFeatureCount() == 3
    assert pts.GetSpatialRef().GetAuthorityCode(None) == "25833"
    assert table.GetFeatureCount() == sum(len(v) for v in logs.values())


def _tile(path: Path, x0: float, y0: float) -> None:
    from osgeo import gdal, osr
    tif = path.with_suffix(".tif")
    ds = gdal.GetDriverByName("GTiff").Create(str(tif), 20, 20, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((x0, 1.0, 0, y0 + 20, 0, -1.0))
    srs = osr.SpatialReference(); srs.ImportFromEPSG(25833)
    ds.SetProjection(srs.ExportToWkt())
    ds.GetRasterBand(1).Fill(25.0)
    ds = None
    with zipfile.ZipFile(path, "w") as zf:
        zf.write(tif, tif.name)
    tif.unlink()


def test_mosaic_dgm_crops_and_keeps_1m(tmp_path):
    from osgeo import gdal
    a, b = tmp_path / "dgm_a.zip", tmp_path / "dgm_b.zip"
    _tile(a, 0, 0)
    _tile(b, 20, 0)
    out = tmp_path / "dgm1.tif"
    mosaic_dgm([a, b], (10, 5, 30, 15), out, margin=2.0)
    ds = gdal.Open(str(out))
    gt = ds.GetGeoTransform()
    assert gt[1] == 1.0 and gt[0] == 8.0 and ds.RasterXSize == 24 and ds.RasterYSize == 14
    ds = None
    assert not list(tmp_path.glob("*.aux.xml"))
