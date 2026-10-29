import time

import numpy as np
import pytest


def _wait_until(cond, timeout_s):
    """Spin a real event loop until cond() is true or the timeout expires."""
    from qgis.PyQt.QtCore import QEventLoop, QTimer

    if cond():
        return True
    loop, timer = QEventLoop(), QTimer()
    timer.setInterval(2)
    deadline = time.perf_counter() + timeout_s

    def check():
        if cond() or time.perf_counter() > deadline:
            loop.quit()

    timer.timeout.connect(check)
    timer.start()
    loop.exec()
    timer.stop()
    return cond()


def _curve(xy):
    from qgis.core import QgsLineString, QgsPoint
    return QgsLineString([QgsPoint(float(x), float(y)) for x, y in xy])


def _request(xy, crs_authid):
    from qgis.core import QgsCoordinateReferenceSystem, QgsProfileRequest
    req = QgsProfileRequest(_curve(xy))
    req.setCrs(QgsCoordinateReferenceSystem(crs_authid))
    return req


def _registered_ids():
    from qgis.core import QgsApplication
    return [s.profileSourceId() for s in QgsApplication.profileSourceRegistry().profileSources()]


def _generate(source, xy, crs):
    gen = source.createProfileGenerator(_request(xy, crs))
    assert gen.generateProfile()
    return gen.takeResults()


def test_source_registers_and_renders(qgis_app, store_with_model, tmp_path):
    from qgis.core import QgsCoordinateReferenceSystem, QgsProfilePoint, QgsProject
    from qgis.gui import QgsElevationProfileCanvas
    from qgis.PyQt.QtGui import QColor

    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.section.profile_source import (SOURCE_ID, register_source,
                                                             unregister_source)

    st, p, _ = store_with_model
    source = register_source(SectionDataProvider(st))
    assert source.profileSourceId() == SOURCE_ID == "geophysics_workbench"
    assert source.profileSourceName() == "Geophysics Workbench"
    assert _registered_ids().count(SOURCE_ID) == 1

    crs = QgsCoordinateReferenceSystem(st.crs_authid)
    canvas = QgsElevationProfileCanvas()
    try:
        canvas.resize(900, 450)
        canvas.setProject(QgsProject.instance())
        canvas.setCrs(crs)
        canvas.setProfileCurve(_curve(p.xy))
        canvas.setSources([source])
        jobs = {"count": None}
        canvas.activeJobCountChanged.connect(lambda n: jobs.__setitem__("count", n))
        canvas.show()
        canvas.refresh()

        # active job count can bounce 1 -> 0 -> 1: require results and 0 jobs for 150 ms
        stable = {"since": None}

        def done():
            if source.last_results is None or jobs["count"] not in (None, 0):
                stable["since"] = None
                return False
            stable["since"] = stable["since"] or time.perf_counter()
            return time.perf_counter() - stable["since"] > 0.15

        assert _wait_until(done, 30), "profile generation did not finish"
        results = source.last_results
        zr = results.zRange()
        assert zr.lower() <= -5 and zr.upper() >= 102            # mesh and topography

        # zoom onto the model (the fixture's topography sits ~100 m above it)
        canvas.setVisiblePlotRange(0, 10, -6, 0.5)
        n_render = results.render_count
        canvas.viewport().repaint()
        assert _wait_until(lambda: results.render_count > n_render, 5)
        img = canvas.grab().toImage()
        out = tmp_path / "section.png"
        img.save(str(out))

        arr = np.frombuffer(img.convertToFormat(img.Format.Format_RGB32).constBits().asstring(
            img.sizeInBytes()), dtype=np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)
        rgb = arr[..., :3].astype(int)
        coloured = (rgb.max(axis=2) - rgb.min(axis=2)) > 40      # saturated = section cells
        assert coloured.mean() > 0.05, f"only {coloured.mean():.1%} coloured pixels ({out})"

        def pixel(s, z):
            pt = canvas.plotPointToCanvasPoint(QgsProfilePoint(s, z))
            return QColor(img.pixel(int(pt.x()), int(pt.y())))

        # values grow with depth and chainage: Spectral_r -> blue top-left, red bottom-right
        top_left, bottom_right = pixel(2.0, -1.0), pixel(8.0, -4.6)
        assert top_left.blue() > top_left.red(), (top_left.name(), out)
        assert bottom_right.red() > bottom_right.blue(), (bottom_right.name(), out)

        # every cell is drawn: no background at any cell centroid
        [layer] = results.snapshot.layers
        cells = layer.mesh.cells
        tri = np.where(cells >= 0, cells, cells[:, :1])
        centroids = layer.mesh.vertices[tri[:, :3]].mean(axis=1)
        blank = [tuple(c) for c in centroids if pixel(*c).name() == "#ffffff"]
        assert not blank, (blank, out)
    finally:
        canvas.setSources([])
        canvas.hide()
        canvas.deleteLater()
        unregister_source(source)
    assert SOURCE_ID not in _registered_ids()


def test_results_identify_returns_layer_dicts(qgis_app, store_with_model):
    from qgis.core import QgsProfileIdentifyContext, QgsProfilePoint

    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.section.profile_source import WorkbenchProfileSource

    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    source = WorkbenchProfileSource(prov)
    results = _generate(source, p.xy, st.crs_authid)
    hits = results.identify(QgsProfilePoint(5.0, -2.0), QgsProfileIdentifyContext())
    assert len(hits) == 1 and hits[0].layer() is None
    [attrs] = hits[0].results()
    assert attrs["name"] == "P1 model" and attrs["unit"] == "ohm.m" and attrs["version"] == 1
    assert attrs["value"] == pytest.approx(prov.identify(p.id, 5.0, -2.0)[0]["value"])
    assert results.identify(QgsProfilePoint(40.0, -2.0), QgsProfileIdentifyContext()) == []

    # a reversed curve still matches; distances then run from the profile's far end
    rev = _generate(source, p.xy[::-1], st.crs_authid)
    length = float(np.hypot(*(p.xy[-1] - p.xy[0])))
    [hit] = rev.identify(QgsProfilePoint(length - 5.0, -2.0), QgsProfileIdentifyContext())
    assert hit.results()[0]["value"] == pytest.approx(attrs["value"])
    assert rev.identify(QgsProfilePoint(5.0, -2.0), QgsProfileIdentifyContext()) == []


def test_unmatched_curve_gives_empty_results(qgis_app, store_with_model):
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.section.profile_source import WorkbenchProfileSource

    st, p, _ = store_with_model
    source = WorkbenchProfileSource(SectionDataProvider(st))
    results = _generate(source, p.xy + 500, st.crs_authid)
    from qgis.core import QgsProfileIdentifyContext, QgsProfilePoint
    assert results is not None and results.snapshot is None
    assert results.identify(QgsProfilePoint(5.0, -2.0), QgsProfileIdentifyContext()) == []


def test_register_twice_does_not_duplicate(qgis_app, store_with_model):
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.section.profile_source import (SOURCE_ID, register_source,
                                                             unregister_source)

    st, _, _ = store_with_model
    prov = SectionDataProvider(st)
    first = register_source(prov)
    second = register_source(prov)
    try:
        assert _registered_ids().count(SOURCE_ID) == 1
        from qgis.core import QgsApplication
        assert QgsApplication.profileSourceRegistry().findSourceById(SOURCE_ID) is second
    finally:
        unregister_source(second)
    assert SOURCE_ID not in _registered_ids()
    unregister_source(first)                                   # already gone: no error


def test_station_ticks_follow_topography_or_mesh_top(qgis_app, store_with_model, tmp_path):
    import shutil

    from geophysics_workbench.core.model import Dataset, file_fingerprint, profile_from_stations
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.section.profile_source import WorkbenchProfileSource
    from geophysics_workbench.store.gpkg_store import ProjectStore

    st, p, src = store_with_model
    with_topo = _generate(WorkbenchProfileSource(SectionDataProvider(st)), p.xy, st.crs_authid)
    assert with_topo._station_z == pytest.approx([100, 102])

    st2 = ProjectStore.create(tmp_path / "q.gpkg", "EPSG:25832")
    p2, s2 = profile_from_stations("P2", "EPSG:25832", np.array([[0, 0], [50, 0.0]]))  # no z
    st2.save_profile(p2); st2.save_station_set(s2)
    src2 = tmp_path / "f003_res.dat"; shutil.copy(src, src2)
    mt, sha = file_fingerprint(src2)
    st2.save_dataset(Dataset("e1", p2.id, s2.id, "ert_model", str(src2), mt, sha, "r2_res_dat",
                             {}, {}, name="no topo"))
    no_topo = _generate(WorkbenchProfileSource(SectionDataProvider(st2)), p2.xy, st2.crs_authid)
    assert no_topo._station_z == pytest.approx([-0.5, -0.5])            # top of the mesh
    assert no_topo.zRange().lower() == pytest.approx(-5) and no_topo.zRange().upper() == pytest.approx(-0.5)


class _LogCatcher:
    # QGIS 4.2: logMessage() emits messageReceivedWithFormat; the old messageReceived
    # signal did not fire for it in this environment (measured).
    def __init__(self):
        from qgis.core import QgsApplication
        self.messages = []
        self._sig = QgsApplication.messageLog().messageReceivedWithFormat
        self._sig.connect(self._on)

    def _on(self, message, tag, level, fmt=None):
        self.messages.append((message, tag, level))

    def close(self):
        self._sig.disconnect(self._on)


def test_callback_failures_are_logged_not_raised(qgis_app, store_with_model, monkeypatch):
    from qgis.core import (Qgis, QgsProfileIdentifyContext, QgsProfilePoint,
                           QgsProfileRenderContext, QgsRenderContext)
    from qgis.PyQt.QtGui import QImage, QPainter

    from geophysics_workbench.section import profile_source as ps
    from geophysics_workbench.section.data import SectionDataProvider

    st, p, _ = store_with_model
    source = ps.WorkbenchProfileSource(SectionDataProvider(st))
    good = _generate(source, p.xy, st.crs_authid)
    log = _LogCatcher()
    try:
        def boom(*a, **k):
            raise MemoryError("simulated")

        # generateProfile (worker thread in the canvas) returns False instead of raising
        monkeypatch.setattr(ps, "cell_path_groups", boom)
        gen = source.createProfileGenerator(_request(p.xy, st.crs_authid))
        assert gen.generateProfile() is False
        assert gen.takeResults() is None

        # renderResults and identify are called from C++ paint / identify paths
        monkeypatch.setattr(ps, "identify_layers", boom)
        assert good.identify(QgsProfilePoint(5.0, -2.0), QgsProfileIdentifyContext()) == []
        good._layers = [(1.0, [("not a colour", None)])]
        img = QImage(200, 100, QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(0)
        painter = QPainter(img)
        try:
            good.renderResults(QgsProfileRenderContext(QgsRenderContext.fromQPainter(painter)))
            assert painter.isActive()
        finally:
            painter.end()
    finally:
        log.close()
    mine = [(m, lvl) for m, tag, lvl in log.messages if tag == "Geophysics Workbench"]
    assert [m.split(" failed")[0] for m, _ in mine] == [
        "Section generation", "Section identify", "Section drawing"]
    assert all(lvl == Qgis.MessageLevel.Critical for _, lvl in mine)
    assert "MemoryError: simulated" in mine[0][0]
