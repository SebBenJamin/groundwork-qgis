"""Derived electrodes as one temporary map layer: never stored, own to the workbench, its
style the user's."""
import hashlib
import shutil
from pathlib import Path

import numpy as np
import pytest

from groundwork_geophysics.core.model import (Dataset, attach_station_set, file_fingerprint,
                                             profile_from_polyline)
from groundwork_geophysics.section.data import SectionDataProvider
from groundwork_geophysics.store.gpkg_store import ProjectStore

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CRS = "EPSG:25832"


def _model(st, p, tmp_path, did="d"):
    src = tmp_path / f"{did}.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset(did, p.id, "", "ert_model", str(src), mt, sha, "r2_res_dat",
                            {"z_kind": "elevation"}, {}, name=did))


@pytest.fixture
def drawn(qgis_app, tmp_path):
    """A store with one drawn line holding a model: its electrodes are guessed (6 of them)."""
    from qgis.core import QgsProject
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("D", CRS, np.array([[0.0, 0.0], [60.0, 0.0]]))
    st.save_profile(p)
    _model(st, p, tmp_path)
    return st, p, SectionDataProvider(st), QgsProject()


def test_layer_appears_for_a_profile_with_guessed_electrodes(drawn):
    from groundwork_geophysics.ui.derived_layers import sync
    st, p, provider, prj = drawn
    lyr = sync(st, provider, prj)
    assert lyr.name() == "electrodes (derived)" and lyr.featureCount() == 6
    assert {f["kind"] for f in lyr.getFeatures()} == {"guessed"}
    assert {f["profile_id"] for f in lyr.getFeatures()} == {p.id}
    assert lyr.readOnly()


def test_layer_is_not_in_the_geopackage(drawn):
    from groundwork_geophysics.ui.derived_layers import sync
    st, p, provider, prj = drawn
    path = Path(st.path)
    before = hashlib.sha1(path.read_bytes()).hexdigest()
    lyr = sync(st, provider, prj)
    provider.snapshot(p.id)
    from osgeo import ogr
    ogr.UseExceptions()
    ds = ogr.Open(str(path))
    names = [ds.GetLayer(i).GetName() for i in range(ds.GetLayerCount())]
    assert lyr.providerType() == "memory" and not [n for n in names if "electrodes" in n]
    assert hashlib.sha1(path.read_bytes()).hexdigest() == before


def test_layer_goes_when_real_positions_arrive(drawn):
    from groundwork_geophysics.ui.derived_layers import derived_layer, sync
    st, p, provider, prj = drawn
    sync(st, provider, prj)
    st.save_station_set(attach_station_set(p, "S", "ert", np.column_stack(
        [np.arange(6) * 2.0, np.zeros(6), np.full(6, 100.0)])))
    provider.notify_changed()
    assert sync(st, provider, prj) is None and derived_layer(prj) is None


def test_layer_sits_below_the_stations_and_a_second_sync_keeps_it(drawn):
    from groundwork_geophysics.ui import project_actions
    from groundwork_geophysics.ui.derived_layers import sync
    st, p, provider, prj = drawn
    project_actions.add_store_layers(st, prj)
    lyr = sync(st, provider, prj)
    group = prj.layerTreeRoot().findGroup(project_actions.GROUP_NAME)
    names = [n.name() for n in group.children()]
    assert names.index("electrodes (derived)") == names.index("stations") + 1
    assert sync(st, provider, prj) is lyr


def test_default_style_clones_the_stations_symbol_with_less_opacity(drawn):
    from groundwork_geophysics.ui import project_actions
    from groundwork_geophysics.ui.derived_layers import sync
    st, p, provider, prj = drawn
    stations = project_actions.add_store_layers(st, prj)["stations"]
    renderer = sync(st, provider, prj).renderer()
    assert renderer.type() == "categorizedSymbol" and renderer.classAttribute() == "kind"
    base = stations.renderer().symbol()
    guessed = next(c for c in renderer.categories() if c.value() == "guessed").symbol()
    assert guessed.color().name() == base.color().name() and guessed.opacity() == 0.5


def test_user_style_survives_a_reopen(drawn):
    from qgis.core import QgsProject, QgsSingleSymbolRenderer, QgsMarkerSymbol
    from groundwork_geophysics.ui.derived_layers import save_style, sync
    st, p, provider, prj = drawn
    lyr = sync(st, provider, prj)
    lyr.setRenderer(QgsSingleSymbolRenderer(QgsMarkerSymbol.createSimple({"color": "10,200,30"})))
    save_style(prj)
    prj2 = QgsProject()
    prj2.writeEntry("geophysics_workbench", "derived_style",
                    prj.readEntry("geophysics_workbench", "derived_style", "")[0])
    again = sync(st, provider, prj2)
    assert again.renderer().type() == "singleSymbol"
    assert again.renderer().symbol().color().name() == "#0ac81e"


def test_layer_counts_as_own(drawn):
    from groundwork_geophysics.section.crossing_lines import own_layer_ids
    from groundwork_geophysics.ui.derived_layers import sync
    st, p, provider, prj = drawn
    lyr = sync(st, provider, prj)
    assert lyr.id() in own_layer_ids(st, prj)


def test_a_removed_layer_stays_gone_until_the_store_is_opened_again(drawn):
    from groundwork_geophysics.ui.derived_layers import derived_layer, sync
    st, p, provider, prj = drawn
    lyr = sync(st, provider, prj)
    prj.removeMapLayer(lyr.id())
    assert sync(st, provider, prj, create=False) is None and derived_layer(prj) is None
    assert sync(st, provider, prj) is not None          # a store opened again


def test_one_profile_that_fails_does_not_stop_the_others(drawn, tmp_path):
    from groundwork_geophysics.ui.derived_layers import sync
    st, p, provider, prj = drawn
    bad = profile_from_polyline("Bad", CRS, np.array([[0.0, 50.0], [60.0, 50.0]]))
    st.save_profile(bad)
    real = provider.electrodes

    def electrodes(pid):
        if pid == bad.id:
            raise RuntimeError("cannot resolve")
        return real(pid)
    provider.electrodes = electrodes
    lyr = sync(st, provider, prj)
    assert {f["profile_id"] for f in lyr.getFeatures()} == {p.id}


def test_untouched_default_style_is_not_written_to_the_project(drawn):
    from groundwork_geophysics.ui.derived_layers import save_style, sync
    st, p, provider, prj = drawn
    sync(st, provider, prj)
    save_style(prj)
    assert prj.readEntry("geophysics_workbench", "derived_style", "")[0] == ""


def test_notifications_sync_on_data_changes_only_and_once(qgis_app, fake_iface, drawn):
    from groundwork_geophysics import classFactory
    from groundwork_geophysics.ui import derived_layers
    from qgis.core import QgsProject
    st, p, _provider, _ = drawn
    plugin = classFactory(fake_iface)
    plugin.initGui()
    try:
        plugin.set_store(st)
        calls = []
        real = plugin.provider.electrodes
        plugin.provider.electrodes = lambda pid: (calls.append(pid), real(pid))[1]
        plugin.provider.notify_redraw()
        qgis_app.processEvents()
        assert calls == []                              # redraw only: no derivation
        for _ in range(3):
            plugin.provider.notify_changed()
        qgis_app.processEvents()
        assert calls.count(p.id) == 1                   # a burst syncs once
        layer = derived_layers.derived_layer(QgsProject.instance())
        QgsProject.instance().removeMapLayer(layer.id())
        plugin.provider.notify_changed()
        qgis_app.processEvents()
        assert derived_layers.derived_layer(QgsProject.instance()) is None
    finally:
        plugin.unload()
        QgsProject.instance().clear()


def test_opening_a_project_keeps_its_derived_layer(qgis_app, fake_iface, drawn, tmp_path):
    """A project opened with its derived-electrodes layer keeps that layer object and refills
    it: removing it while QGIS restores a 3D map view that holds it crashed QGIS."""
    from qgis.core import QgsProject

    from groundwork_geophysics.plugin import WorkbenchPlugin
    from groundwork_geophysics.ui.derived_layers import derived_layer
    from groundwork_geophysics.ui.project_actions import use_store
    st, _p, _provider, _prj = drawn
    project = QgsProject.instance()
    project.clear()
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        project.setFileName(str(tmp_path / "p.qgz"))
        plugin.set_store(use_store(st, project))
        assert derived_layer(project) is not None
        assert project.write()
        project.clear()
        removed = []
        project.layersWillBeRemoved.connect(removed.extend)
        assert project.read(str(tmp_path / "p.qgz"))
        layer = derived_layer(project)
        assert removed == [] and layer is not None and layer.featureCount() == 6
    finally:
        plugin.unload()
        project.clear()


def test_a_derived_layer_with_nothing_to_show_is_kept_empty_when_asked(drawn):
    """While a project is being read the layer is emptied, not removed."""
    from groundwork_geophysics.ui.derived_layers import sync
    st, p, provider, prj = drawn
    layer = sync(st, provider, prj)
    for d in st.datasets(p.id):
        st.delete_dataset(d.id)
    provider.notify_changed()
    assert sync(st, provider, prj, keep=True) is layer
    assert layer.featureCount() == 0 and prj.mapLayer(layer.id()) is layer
