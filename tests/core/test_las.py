"""The LAS 1.4 writer for point-cloud curtains, read back through QGIS's own reader (PDAL)."""
import numpy as np
import pytest

N = 1000


@pytest.fixture
def cloud(tmp_path):
    from qgis.core import Qgis, QgsCoordinateReferenceSystem

    from groundwork_geophysics.core.las import write_las
    rng = np.random.default_rng(1)
    xyz = np.column_stack([642000.0 + rng.uniform(0, 50, N), 5654000.0 + rng.uniform(0, 5, N),
                           170.0 + rng.uniform(0, 10, N)])
    rgb = rng.integers(0, 256, (N, 3)).astype(np.uint8)
    value = 10 ** rng.uniform(1, 3, N)
    wkt = QgsCoordinateReferenceSystem("EPSG:25832").toWkt(Qgis.CrsWktVariant.Wkt1Gdal)
    path = tmp_path / "curtain.las"
    write_las(path, xyz, rgb, {"Value": value, "Log10Value": np.log10(value)}, wkt)
    return path, xyz, rgb, value


def _layer(path):
    from qgis.core import QgsPointCloudLayer
    layer = QgsPointCloudLayer(str(path), "t", "pdal")
    assert layer.isValid(), layer.error().summary()
    return layer


def test_qgis_reads_the_points_back(qgis_app, cloud):
    path, xyz, _rgb, _v = cloud
    layer = _layer(path)
    assert layer.pointCount() == N
    ext = layer.extent()
    assert ext.xMinimum() == pytest.approx(xyz[:, 0].min(), abs=1e-3)
    assert ext.yMaximum() == pytest.approx(xyz[:, 1].max(), abs=1e-3)
    assert layer.crs().authid() == "EPSG:25832"
    assert not path.with_name(path.name + ".part").exists()


def test_the_extra_values_are_attributes(qgis_app, cloud):
    names = {a.name() for a in _layer(cloud[0]).attributes().attributes()}
    assert {"Red", "Green", "Blue", "Value", "Log10Value"} <= names


def test_values_and_colours_come_back(qgis_app, cloud):
    """Each point's record, found where the header says the points start and as long as it
    says, holds its position, colour and values (QGIS's own Identify needs the index it
    builds on first open, which a headless test does not start)."""
    import struct
    path, xyz, rgb, value = cloud
    raw = path.read_bytes()
    start, = struct.unpack_from("<I", raw, 96)
    fmt, length = struct.unpack_from("<BH", raw, 104)
    scale = struct.unpack_from("<3d", raw, 131)
    offset = struct.unpack_from("<3d", raw, 155)
    assert fmt == 7 and length == 36 + 2 * 8
    for i in (0, N - 1):
        rec = raw[start + i * length:start + (i + 1) * length]
        x, y, z = (struct.unpack_from("<i", rec, 4 * k)[0] * scale[k] + offset[k]
                   for k in range(3))
        assert (x, y, z) == pytest.approx(tuple(xyz[i]), abs=1e-3)
        assert struct.unpack_from("<3H", rec, 30) == tuple(int(c) * 257 for c in rgb[i])
        v, log = struct.unpack_from("<2d", rec, 36)
        assert v == pytest.approx(value[i]) and log == pytest.approx(np.log10(value[i]))
