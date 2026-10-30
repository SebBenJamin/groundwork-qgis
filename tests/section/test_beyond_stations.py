"""The part of a model beyond the station coverage is marked (0.1.1, finding F1)."""
import numpy as np
import pytest


@pytest.fixture
def overhanging(qgis_app, tmp_path):
    """Profile 0 .. 100 m with stations every 10 m over 0 .. 60 m (z = 0), and a uniform
    R2 model (1000 ohm.m, cells 0 .. 20 m x -2 .. 0 m) placed at chainage 50 .. 70.
    Returns (store, profile, dataset_id)."""
    from geophysics_workbench.core.model import (Dataset, Profile, attach_station_set,
                                                 file_fingerprint)
    from geophysics_workbench.store.gpkg_store import ProjectStore

    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p = Profile("p1", "P4", np.array([[0.0, 0.0], [100.0, 0.0]]), "EPSG:25832")
    xyz = np.column_stack([np.arange(7) * 10.0, np.zeros(7), np.zeros(7)])
    s = attach_station_set(p, "P4", "ert", xyz)
    st.save_profile(p)
    st.save_station_set(s)
    src = tmp_path / "f001_res.dat"
    src.write_text("".join(f"\t{x:.1f}\t{z:.1f}\t1000.0\t3.0\n"
                           for z in (-0.5, -1.5) for x in np.arange(1.0, 20.0, 2.0)))
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("d1", p.id, s.id, "ert_model", str(src), mt, sha, "r2_res_dat",
                            {"z_kind": "elevation", "chainage_offset": 50.0}, {},
                            name="P2 model"))
    return st, p, "d1"


def test_snapshot_carries_station_coverage(overhanging):
    from geophysics_workbench.section.data import SectionDataProvider

    st, p, _ = overhanging
    prov = SectionDataProvider(st)
    assert prov.coverage(p.id) == pytest.approx((0.0, 60.0))
    assert prov.snapshot(p.id).coverage == pytest.approx((0.0, 60.0))
    assert prov.snapshot(p.id, reverse=True).coverage == pytest.approx((40.0, 100.0))


def _render(results, size=(400, 200)):
    """Draw ``results`` into an image; chainage 40 .. 80 m and z 1 .. -3 m fill it."""
    from qgis.core import QgsProfileRenderContext, QgsRenderContext
    from qgis.PyQt.QtGui import QImage, QPainter, QTransform

    img = QImage(*size, QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    try:
        ctx = QgsProfileRenderContext(QgsRenderContext.fromQPainter(painter))
        ctx.setWorldTransform(QTransform(10.0, 0.0, 0.0, -50.0, -400.0, 50.0))
        results.renderResults(ctx)
    finally:
        painter.end()
    return img


def test_model_beyond_the_stations_is_drawn_lighter(overhanging, tmp_path):
    from qgis.PyQt.QtGui import QColor

    from geophysics_workbench.core.colors import ColorScale
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.section.profile_source import WorkbenchProfileSource

    st, p, did = overhanging
    prov = SectionDataProvider(st)
    prov.style(did).scale = ColorScale("Spectral_r", 1.0, 1000.0, True)   # dark red
    gen = WorkbenchProfileSource(prov).createProfileGenerator(_request(p.xy, st.crs_authid))
    assert gen.generateProfile()
    img = _render(gen.takeResults())
    img.save(str(tmp_path / "beyond.png"))
    inside = QColor(img.pixel(150, 100))            # s = 55, z = -1
    beyond = QColor(img.pixel(250, 100))            # s = 65, z = -1
    blank = QColor(img.pixel(150, 180))             # s = 55, z = -2.6: below the model
    assert blank.name() == "#ffffff"
    assert inside.red() > inside.blue() and inside.name() != "#ffffff"
    for a, b in ((inside.red(), beyond.red()), (inside.green(), beyond.green()),
                 (inside.blue(), beyond.blue())):
        assert b > a, (inside.name(), beyond.name())
    assert beyond.name() != "#ffffff"               # still readable: not painted over
    assert beyond.red() > beyond.blue()


def _request(xy, crs_authid):
    from qgis.core import QgsCoordinateReferenceSystem, QgsLineString, QgsPoint, QgsProfileRequest

    req = QgsProfileRequest(QgsLineString([QgsPoint(float(x), float(y)) for x, y in xy]))
    req.setCrs(QgsCoordinateReferenceSystem(crs_authid))
    return req


def test_readout_says_beyond_stations(overhanging, make_dock):
    from geophysics_workbench.section.readout import format_readout

    assert format_readout(5.0, 1.0, beyond=True) == "s = 5.0 m · z = 1.0 m · beyond stations"
    assert format_readout(5.0, 1.0) == "s = 5.0 m · z = 1.0 m"
    st, p, _ = overhanging
    dock = make_dock(st)
    dock.open_profile(p.id)
    dock.show_cursor(65.0)
    assert dock.readout.text().endswith(" · beyond stations")
    dock.show_cursor(55.0)
    assert "beyond stations" not in dock.readout.text()
