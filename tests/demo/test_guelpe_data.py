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


def test_lab_samples_keep_the_authors_values():
    """The cores' lab values (C/N/S and grain sizes) per sample, from the same table."""
    from guelpe_data import LAB_FIELDS, parse_samples
    samples = parse_samples(FIXTURE("cores_lab_snippet.tab"))
    assert [s[:4] for s in samples] == [("RK1", 0.30, 0.41, "G_RK1_1"),
                                        ("RK1", 0.41, 0.60, "G_RK1_2")]
    first = samples[0][4]
    assert (first["tn"], first["tc"], first["tic"], first["toc"], first["ts"]) == (
        0.6066, 9.209, 0.0, 9.209, 0.4352)
    assert first["fc_lt0_2um"] == 18.6                  # the finest fraction, as given
    # sand, silt and clay are the sums of their fractions (derived)
    assert first["sand"] == pytest.approx(0.2 + 1.6 + 3.5 + 12.6)
    assert first["silt"] == pytest.approx(9.9 + 8.2 + 12.4)
    assert first["clay"] == pytest.approx(16.7 + 14.6 + 18.6)
    assert set(first) == {f for f, _u, _d in LAB_FIELDS}


def test_lab_table_written_beside_the_cores(tmp_path):
    from osgeo import ogr

    from guelpe_data import LAB_TABLE, parse_samples, write_cores_gpkg, write_lab_table
    sites, logs = parse_cores(FIXTURE("cores_snippet.tab"))
    path = tmp_path / "cores.gpkg"
    write_cores_gpkg(path, sites, logs)
    write_lab_table(path, parse_samples(FIXTURE("cores_lab_snippet.tab")))
    with ogr.ExceptionMgr():
        ds = ogr.Open(str(path))
        assert ds.GetLayerByName("cores").GetFeatureCount() == 3     # the cores stay
        table = ds.GetLayerByName(LAB_TABLE)
        rows = [(f["core_id"], f["depth"], f["top"], f["bottom"], f["sample_id"], f["toc"])
                for f in table]
    # depth: the sample's middle, to the centimetre; top and bottom as the authors give them
    assert rows == [("RK1", 0.36, 0.30, 0.41, "G_RK1_1", 9.209),
                    ("RK1", 0.51, 0.41, 0.60, "G_RK1_2", 4.9604)]


def test_a_value_below_the_detection_limit_is_a_gap():
    """"<0.0020" (sulfur below detection in RK15) stays empty: no number is made up for it,
    and the grain sizes of that sample still add up."""
    from guelpe_data import parse_samples
    lines = FIXTURE("cores_lab_snippet.tab").splitlines()
    cols = lines[-1].split("\t")
    cols[20] = "<0.0020"
    [_, sample] = parse_samples("\n".join(lines[:-1] + ["\t".join(cols)]) + "\n")
    assert "ts" not in sample[4] and sample[4]["toc"] == 4.9604
    assert sample[4]["clay"] > 0


def test_reversed_positions_keep_the_heights_in_electrode_order():
    """Transect 4's published DGPS file lists E/N from the far end (its heights, the field
    notes and the authors' sketch put electrode 1 in the south-west): the positions are turned
    round, the heights and numbers stay."""
    from guelpe_data import reversed_positions
    xyz = np.array([[0.0, 0.0, 24.1], [1.0, 0.5, 24.2], [2.0, 1.0, 24.9]])
    out = reversed_positions(xyz)
    assert out[:, :2].tolist() == [[2.0, 1.0], [1.0, 0.5], [0.0, 0.0]]
    assert out[:, 2].tolist() == [24.1, 24.2, 24.9]
