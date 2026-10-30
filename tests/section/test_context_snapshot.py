"""Context items, profile ties and the DEM topography choice in the section snapshot."""
import os
import shutil

import numpy as np
import pytest
from pytest import approx

from geophysics_workbench.core.context import BandSegment, ContextItems, Crossing, ProjectedPoint
from geophysics_workbench.core.model import Dataset, file_fingerprint, profile_from_stations
from geophysics_workbench.section.data import LayerStyle, SectionDataProvider

FIXTURES = os.path.join(os.path.dirname(__file__), "..", "fixtures", "ert")


def _add_b(st, tmp_path):
    """Profile "B" from (20, -5) to (20, 45), crossing P1 (0,0)-(50,0) at s_a = 20,
    s_b = 5, with its own copy of f001_res.dat (cells 0 .. 10 m along B)."""
    b, s = profile_from_stations("B", "EPSG:25832", np.array([[20, -5, 100], [20, 45, 100.0]]))
    st.save_profile(b); st.save_station_set(s)
    src = tmp_path / "b_res.dat"
    shutil.copy(os.path.join(FIXTURES, "f001_res.dat"), src)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("dB", b.id, s.id, "ert_model", str(src), mt, sha, "r2_res_dat",
                            {"z_kind": "elevation"}, {}, name="B model"))
    return b


def _fake_items(dem_offset=0.0):
    s = np.linspace(0.0, 50.0, 11)
    return ContextItems(
        crossings=[Crossing(10.0, "380 kV", "powerline", 90.0)],
        points=[ProjectedPoint(12.0, 3.0, "W1", "point")],
        band=[BandSegment(5.0, 15.0, "Sand")],
        dem=(s, np.interp(s, [0, 50], [100, 102]) + dem_offset))


def test_snapshot_carries_context_and_ties(store_with_model, tmp_path):
    st, p, _ = store_with_model
    b = _add_b(st, tmp_path)
    prov = SectionDataProvider(st)
    calls = []
    prov.context_source = lambda profile: calls.append(profile.id) or _fake_items()
    snap = prov.snapshot(p.id)
    ctx = snap.context
    assert [c.label for c in ctx.crossings] == ["380 kV"]
    assert [pt.label for pt in ctx.points] == ["W1"]
    [tie] = ctx.ties
    assert tie.other_name == "B" and tie.other_id == b.id
    assert tie.s == approx(20) and tie.s_other == approx(5) and tie.distance == 0.0
    [col] = tie.columns
    [b_layer] = prov.layers(b.id)
    z_top, z_bottom, values = b_layer.mesh.column_at(tie.s_other)
    assert col.dataset_name == "B model" and col.quantity == "resistivity"
    np.testing.assert_allclose(col.values, np.array(values))
    np.testing.assert_allclose(col.z_top, np.array(z_top))
    np.testing.assert_allclose(col.z_bottom, np.array(z_bottom))
    assert col.scale == b_layer.style.scale and col.scale is not b_layer.style.scale
    assert prov.ties(p.id)[0].s == approx(20)
    assert prov.context(p.id).ties[0].other_name == "B"
    # gathered items are cached per profile until notify_changed()
    n = calls.count(p.id)
    prov.snapshot(p.id); prov.context(p.id); prov.topography(p.id)
    assert calls.count(p.id) == n
    prov.notify_changed()
    prov.context(p.id)
    assert calls.count(p.id) == n + 1


def test_tie_column_drops_zero_thickness_and_duplicates(store_with_model, tmp_path):
    st, p, _ = store_with_model
    b = _add_b(st, tmp_path)
    # move B so the crossing falls on the shared cell edge x = 4 along B
    b.xy = np.array([[20, -4.0], [20, 46.0]])
    st.save_profile(b)
    prov = SectionDataProvider(st)
    [tie] = prov.ties(p.id)
    assert tie.s_other == approx(4)
    raw_top, _raw_bottom, _v = prov.layers(b.id)[0].mesh.column_at(tie.s_other)
    assert len(raw_top) > 4                                        # both neighbours
    [col] = tie.columns
    assert np.all(col.z_top > col.z_bottom)
    intervals = list(zip(col.z_top.tolist(), col.z_bottom.tolist()))
    assert len(intervals) == len(set(intervals)) == 4              # 4 rows of cells
    assert np.all(np.diff(col.z_top) < 0)                          # top to bottom


def test_hidden_layer_not_in_tie_columns(store_with_model, tmp_path):
    st, p, _ = store_with_model
    _add_b(st, tmp_path)
    prov = SectionDataProvider(st)
    assert len(prov.snapshot(p.id).context.ties[0].columns) == 1
    prov.set_style("dB", LayerStyle(visible=False))
    [tie] = prov.snapshot(p.id).context.ties
    assert tie.columns == []


def test_near_miss_distance_is_used(store_with_model, tmp_path):
    st, p, _ = store_with_model
    b = _add_b(st, tmp_path)
    b.xy = np.array([[20, 6.0], [20, 56.0]])                        # 6 m short of P1
    st.save_profile(b)
    prov = SectionDataProvider(st)
    assert prov.ties(p.id)[0].distance == approx(6)
    prov.near_miss = 5.0
    assert prov.ties(p.id) == []


def test_reverse_snapshot_mirrors_context(store_with_model, tmp_path):
    st, p, _ = store_with_model
    _add_b(st, tmp_path)
    prov = SectionDataProvider(st)
    items = _fake_items()
    items.dem = (np.array([0.0, 5.0, 20.0, 50.0]), np.array([100.0, 100.5, 101.0, 102.0]))
    prov.context_source = lambda profile: items
    fwd = prov.snapshot(p.id).context
    rev = prov.snapshot(p.id, reverse=True).context
    length = 50.0
    np.testing.assert_allclose(rev.dem[0], length - fwd.dem[0][::-1])   # asymmetric grid
    np.testing.assert_allclose(rev.dem[0], np.array([0.0, 30.0, 45.0, 50.0]))
    np.testing.assert_allclose(rev.ties[0].columns[0].values, fwd.ties[0].columns[0].values)
    np.testing.assert_allclose(rev.ties[0].columns[0].z_top, fwd.ties[0].columns[0].z_top)
    assert [c.s for c in rev.crossings] == approx([length - c.s for c in fwd.crossings])
    assert [pt.s for pt in rev.points] == approx([length - pt.s for pt in fwd.points])
    assert [t.s for t in rev.ties] == approx([30.0])
    assert rev.ties[0].s_other == approx(5)
    assert np.array([(b.s0, b.s1) for b in rev.band]) == approx(np.array([(35.0, 45.0)]))
    assert all(b.s0 < b.s1 for b in rev.band)
    assert np.all(np.diff(rev.dem[0]) > 0)
    np.testing.assert_allclose(rev.dem[1], np.array(fwd.dem[1][::-1]))
    # the forward snapshot is untouched by the mirrored one
    assert fwd.crossings[0].s == approx(10) and fwd.ties[0].s == approx(20)


def _add_depth_model(st, p, tmp_path, offset=0.0):
    """Zond depth model, cells 0 .. 10 m (+ ``offset``) along P1."""
    src = tmp_path / "zond_model_depth.dat"
    shutil.copy(os.path.join(FIXTURES, "zond_model_depth.dat"), src)
    s = st.station_sets(p.id)[0]
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("dz", p.id, s.id, "ert_model", str(src), mt, sha, "zondres_xyz",
                            {"z_kind": "depth", "chainage_offset": offset}, {}, name="depth"))


def _stations(s):
    return np.interp(s, [0, 50], [100, 102])


def test_partial_dem_falls_back_to_stations_beyond_its_data(store_with_model, tmp_path):
    st, p, _ = store_with_model
    _add_depth_model(st, p, tmp_path, offset=30.0)            # cells 30 .. 40 m
    items = _fake_items(dem_offset=2.0)
    s = items.dem[0]
    items.dem[1][s > 25] = np.nan                             # the raster ends at s = 25
    prov = SectionDataProvider(st)
    prov.context_source = lambda profile: items
    prov.set_topography_source(p.id, "dem")
    line_s, line_z = prov.topography(p.id)
    np.testing.assert_allclose(line_s, s)
    np.testing.assert_allclose(line_z[s <= 25], _stations(s[s <= 25]) + 2.0)   # DEM
    np.testing.assert_allclose(line_z[s > 25], _stations(s[s > 25]))           # stations
    v = prov.layers(p.id)[1].mesh.vertices
    assert v[:, 0].min() == approx(30.0)
    # the top row follows the station line, not the DEM edge value (103 m at s = 25)
    assert v[:, 1].max() == approx(_stations(40.0))
    top = v[np.isclose(v[:, 1], _stations(v[:, 0]))]
    assert len(top) == 10                                     # 5 cells x 2 corners


def test_dem_topography_choice_drives_depth_model(store_with_model, tmp_path):
    st, p, _ = store_with_model
    _add_depth_model(st, p, tmp_path)
    prov = SectionDataProvider(st)
    prov.context_source = lambda profile: _fake_items(dem_offset=2.0)
    top_stations = prov.layers(p.id)[1].mesh.vertices[:, 1].max()
    assert top_stations == approx(np.interp(10.0, [0, 50], [100, 102]))
    calls = []
    prov.on_change.append(lambda: calls.append(1))
    prov.set_topography_source(p.id, "dem")
    assert calls == [1]
    assert st.profile(p.id).metadata["topography"] == "dem"
    assert prov.layers(p.id)[1].mesh.vertices[:, 1].max() == approx(top_stations + 2.0)
    s, z = prov.topography(p.id)
    assert z == approx(np.interp(s, [0, 50], [100, 102]) + 2.0)
    assert prov.snapshot(p.id).topo[1] == approx(z)
    # a fresh provider follows the stored choice; "stations" goes back
    fresh = SectionDataProvider(st)
    fresh.context_source = prov.context_source
    assert fresh.layers(p.id)[1].mesh.vertices[:, 1].max() == approx(top_stations + 2.0)
    prov.set_topography_source(p.id, "stations")
    assert st.profile(p.id).metadata["topography"] == "stations"
    assert prov.layers(p.id)[1].mesh.vertices[:, 1].max() == approx(top_stations)
    with pytest.raises(ValueError):
        prov.set_topography_source(p.id, "lidar")


def test_dem_choice_without_dem_uses_stations_and_fills_nan(store_with_model, tmp_path):
    st, p, _ = store_with_model
    _add_depth_model(st, p, tmp_path)
    prov = SectionDataProvider(st)
    prov.set_topography_source(p.id, "dem")
    stations = prov.topography(p.id)                    # no context source: no DEM
    np.testing.assert_allclose(stations[1], np.array([100.0, 102.0]))
    items = _fake_items(dem_offset=2.0)
    items.dem[1][3:5] = np.nan                          # a nodata gap inside the profile
    prov.context_source = lambda profile: items
    s, z = prov.topography(p.id)
    assert np.isfinite(z).all() and len(s) == 11
    np.testing.assert_allclose(z[3:5], _stations(s[3:5]))     # the gap: station line
    np.testing.assert_allclose(z[5:], _stations(s[5:]) + 2.0)
    mesh = prov.layers(p.id)[1].mesh
    assert np.isfinite(mesh.vertices).all()
    all_nan = _fake_items()
    all_nan.dem[1][:] = np.nan
    prov.context_source = lambda profile: all_nan       # setting a source drops the cache
    np.testing.assert_allclose(prov.topography(p.id)[1], np.array([100.0, 102.0]))


def test_no_context_source_is_harmless(store_with_model, tmp_path):
    st, p, _ = store_with_model
    _add_b(st, tmp_path)
    prov = SectionDataProvider(st)
    ctx = prov.snapshot(p.id).context
    assert ctx.crossings == [] and ctx.points == [] and ctx.band == []
    assert ctx.dem is None
    assert [t.other_name for t in ctx.ties] == ["B"]
    assert prov.context("no-such-profile") is None


def test_failing_context_source_does_not_break_the_section(store_with_model):
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)

    def boom(profile):
        raise RuntimeError("layer gone")
    reported = []
    prov.on_context_error = lambda pid, message: reported.append((pid, message))
    prov.context_source = boom
    snap = prov.snapshot(p.id)
    assert snap.context.crossings == [] and snap.layers[0].error is None
    assert prov.context_errors == {p.id: "RuntimeError: layer gone"}
    prov.snapshot(p.id)                                       # cached: not asked again
    assert reported == [(p.id, "RuntimeError: layer gone")]
    prov.context_source = lambda profile: _fake_items()
    assert prov.context(p.id).crossings and prov.context_errors == {}   # cleared on success


def test_plugin_logs_context_errors_once(qgis_app, fake_iface, store_with_model, monkeypatch):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench import plugin as plugin_module
    from geophysics_workbench.plugin import WorkbenchPlugin

    QgsProject.instance().clear()
    logged = []

    class FakeLog:
        @staticmethod
        def logMessage(message, tag, level):
            logged.append((message, tag))
    monkeypatch.setattr(plugin_module, "QgsMessageLog", FakeLog)
    st, p, _ = store_with_model

    def boom(profile):
        raise RuntimeError("layer gone")
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.set_store(st)
        plugin.provider.context_source = boom
        plugin.provider.snapshot(p.id)
        plugin.provider.notify_changed()                      # asked again, same error
        plugin.provider.snapshot(p.id)
        assert len(logged) == 1
        message, tag = logged[0]
        assert tag == "Geophysics Workbench"
        assert "P1" in message and "RuntimeError: layer gone" in message
    finally:
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()


def test_plugin_closes_gatherer_on_store_change(qgis_app, fake_iface, store_with_model,
                                                monkeypatch):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench.plugin import WorkbenchPlugin
    from geophysics_workbench.section.context_layers import ContextGatherer

    QgsProject.instance().clear()                    # default context settings
    closed = []
    original = ContextGatherer.close

    def spy(self):
        closed.append(self)
        original(self)
    monkeypatch.setattr(ContextGatherer, "close", spy)
    store = store_with_model[0]
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.set_store(store)
        first, provider = plugin.gatherer, plugin.provider
        assert isinstance(first, ContextGatherer)
        assert provider.context_source == first.items_for
        assert provider.near_miss == approx(10.0)
        plugin.set_store(None)
        assert closed == [first] and plugin.gatherer is None
        assert provider.context_source is None
        plugin.set_store(store)
        second = plugin.gatherer
        assert second is not first and closed == [first]
    finally:
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()
    assert closed == [first, second] and plugin.gatherer is None


def test_plugin_edit_context_refreshes_the_section(qgis_app, fake_iface, store_with_model,
                                                   monkeypatch):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent
    from qgis.PyQt.QtWidgets import QDialog

    from geophysics_workbench.core.context_settings import ContextSettings
    from geophysics_workbench.plugin import WorkbenchPlugin
    from geophysics_workbench.ui import context_dialog

    project = QgsProject.instance()
    project.clear()

    class AcceptingDialog:
        """Stands in for ContextDialog: the user saves near_miss 3.5 and presses OK. (The real
        dialog with a patched ``exec`` crashes a later test of the full run at random.)"""
        def __init__(self, iface, prj):
            self.project = prj

        def exec(self):
            context_dialog.write_settings(self.project, ContextSettings(near_miss=3.5))
            return QDialog.DialogCode.Accepted

        def deleteLater(self):
            pass
    monkeypatch.setattr(context_dialog, "ContextDialog", AcceptingDialog)
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.set_store(store_with_model[0])
        calls = []
        plugin.provider.on_change.append(lambda: calls.append(1))
        plugin.edit_context()
        assert calls == [1] and plugin.provider.near_miss == approx(3.5)
    finally:
        plugin.unload()
        project.clear()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()
