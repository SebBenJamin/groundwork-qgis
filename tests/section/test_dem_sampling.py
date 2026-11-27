"""The ground from an elevation model: interpolated between pixel centres (bilinear), the
nearest valid pixel where a neighbour has no data."""
import numpy as np
import pytest


def _dem(path, values, nodata=-9999.0):
    """A north-up GeoTIFF of 1 m pixels, its top-left corner at (0, 2): pixel centres at
    x 0.5, 1.5 and y 1.5, 0.5 for a 2 × 2 grid."""
    from osgeo import gdal, osr
    values = np.asarray(values, dtype="float32")
    with gdal.ExceptionMgr(useExceptions=True), osr.ExceptionMgr(useExceptions=True):
        ds = gdal.GetDriverByName("GTiff").Create(str(path), values.shape[1], values.shape[0],
                                                  1, gdal.GDT_Float32)
        ds.SetGeoTransform((0.0, 1.0, 0, 2.0, 0, -1.0))
        srs = osr.SpatialReference()
        srs.ImportFromEPSG(25832)
        ds.SetProjection(srs.ExportToWkt())
        band = ds.GetRasterBand(1)
        band.SetNoDataValue(nodata)
        band.WriteArray(values)
        ds.FlushCache()
        ds = None
    from qgis.core import QgsRasterLayer
    layer = QgsRasterLayer(str(path), "DEM")
    assert layer.isValid()
    return layer


def test_heights_between_pixel_centres_are_interpolated(qgis_app, tmp_path):
    from groundwork_geophysics.section.dem_sampling import sample_point
    layer = _dem(tmp_path / "dem.tif", [[0.0, 10.0], [20.0, 30.0]])
    at = lambda x, y: sample_point(layer, x, y, "EPSG:25832")      # noqa: E731
    assert at(1.0, 1.0) == pytest.approx(15.0)
    assert at(1.25, 1.5) == pytest.approx(7.5)
    assert at(0.5, 1.0) == pytest.approx(10.0)
    assert at(0.5, 1.5) == pytest.approx(0.0)                       # a pixel centre: its value
    assert at(1.5, 0.5) == pytest.approx(30.0)
    assert at(0.2, 1.8) == pytest.approx(0.0)                       # outside the centres
    assert at(5.0, 5.0) is None


def test_a_neighbour_without_data_gives_the_nearest_pixel(qgis_app, tmp_path):
    from groundwork_geophysics.section.dem_sampling import sample_point
    layer = _dem(tmp_path / "dem.tif", [[0.0, 10.0], [20.0, -9999.0]])
    at = lambda x, y: sample_point(layer, x, y, "EPSG:25832")      # noqa: E731
    assert at(0.9, 1.1) == pytest.approx(0.0)
    assert at(1.25, 1.5) == pytest.approx(7.5)                      # the gap weighs nothing
    assert at(1.4, 0.6) is None                                     # the nearest has no data


def test_a_profile_is_sampled_smoothly(qgis_app, tmp_path):
    from groundwork_geophysics.core.model import Profile
    from groundwork_geophysics.section.dem_sampling import sample_profile
    layer = _dem(tmp_path / "dem.tif", [[0.0, 10.0, 20.0, 30.0]] * 2)
    p = Profile("p", "P", np.array([[0.75, 1.0], [3.25, 1.0]]), "EPSG:25832")
    s, z = sample_profile(layer, p.chainage, "EPSG:25832")
    assert len(s) == 4 and s[1] == pytest.approx(2.5 / 3)          # between pixel centres
    np.testing.assert_allclose(z, 10.0 * (s + 0.25), atol=1e-5)    # no stair steps
