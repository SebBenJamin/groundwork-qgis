"""Show in 3D: ticked models as "Models in 3D" and the ticked profiles' boreholes as
"Boreholes in 3D", temporary layers kept in step with the section, never stored."""
import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from groundwork_geophysics.core.context import ContextItems, LogInterval, ProjectedPoint
from groundwork_geophysics.core.model import Dataset, file_fingerprint, profile_from_polyline
from groundwork_geophysics.section.data import SectionDataProvider
from groundwork_geophysics.store.gpkg_store import ProjectStore

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CRS = "EPSG:25832"


def _model(st, p, tmp_path, did="d"):
    src = tmp_path / f"{did}.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset(did, p.id, "", "ert_model", str(src), mt, sha, "r2_res_dat",
                            {"z_kind": "elevation"}, {}, name=f"Model {did}"))


def _borehole(label="B1", x=10.0, y=2.0, s=10.0):
    return ProjectedPoint(s, 2.0, label, "borehole", 100.0,
                          [LogInterval(0.0, 3.0, "sand"), LogInterval(3.0, 8.0, "clay")],
                          bid=label, layer_id="bh", x=x, y=y)


@pytest.fixture
def setup(qgis_app, tmp_path):
    from qgis.core import QgsProject
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("P1", CRS, np.array([[0.0, 0.0], [60.0, 0.0]]))
    st.save_profile(p)
    _model(st, p, tmp_path)
    provider = SectionDataProvider(st)
    provider.context_source = lambda profile: ContextItems(points=[_borehole()])
    return st, p, provider, QgsProject()


def _choose(prj, models=(), boreholes=()):
    from groundwork_geophysics.ui.view3d_layers import Choice, write_choice
    write_choice(prj, Choice(frozenset(models), frozenset(boreholes)))


def test_choice_round_trips_through_the_project(setup):
    from groundwork_geophysics.ui.view3d_layers import Choice, read_choice
    _st, _p, _provider, prj = setup
    assert read_choice(prj) == Choice(frozenset(), frozenset())
    _choose(prj, ["d"], ["p1"])
    assert read_choice(prj) == Choice(frozenset({"d"}), frozenset({"p1"}))


def test_a_ticked_model_becomes_cells_in_a_memory_layer(setup):
    from groundwork_geophysics.ui.view3d_layers import MODELS_NAME, sync
    st, p, provider, prj = setup
    before = hashlib.sha1(Path(st.path).read_bytes()).hexdigest()
    _choose(prj, ["d"])
    layers = sync(st, provider, prj, create=True)
    lyr = layers["models"]
    mesh = provider.layers(p.id)[0].mesh
    assert lyr.name() == MODELS_NAME and lyr.providerType() == "memory"
    assert lyr.featureCount() == len(mesh.cells)
    assert lyr.readOnly() and "boreholes" not in layers
    f = next(lyr.getFeatures())
    assert f["dataset_id"] == "d" and f["profile"] == "P1" and f["dataset"] == "Model d"
    assert f.geometry().constGet().is3D()
    assert hashlib.sha1(Path(st.path).read_bytes()).hexdigest() == before


def test_cells_carry_the_section_colours(setup):
    from qgis.PyQt.QtGui import QColor

    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    lyr = sync(st, provider, prj, create=True)["models"]
    layer = provider.layers(p.id)[0]
    rgba = layer.style.scale.rgba(layer.mesh.values)
    got = {round(f["value"], 6): f["color"] for f in lyr.getFeatures()}
    for value, row in zip(layer.mesh.values[:20], rgba[:20]):
        assert got[round(float(value), 6)] == QColor(*[int(c) for c in row[:3]]).name()


def test_the_3d_style_holds_every_cell_in_one_piece(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, _p, provider, prj = setup
    _choose(prj, ["d"])
    lyr = sync(st, provider, prj, create=True)["models"]
    r3d = lyr.renderer3D()
    assert r3d is not None
    assert r3d.tilingSettings().maximumChunkFeatures() >= lyr.featureCount()


def test_a_scale_change_recolours(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, _p, provider, prj = setup
    _choose(prj, ["d"])
    lyr = sync(st, provider, prj, create=True)["models"]
    style = provider.style("d")
    first = {f["color"] for f in lyr.getFeatures()}
    provider.set_style("d", replace(style, scale=replace(style.scale, cmap="viridis")))
    sync(st, provider, prj)
    assert {f["color"] for f in lyr.getFeatures()} != first


def test_the_section_fade_leaves_out_unresolved_cells(qgis_app, tmp_path):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_layers import sync
    st = ProjectStore.create(tmp_path / "s.gpkg", CRS)
    p = profile_from_polyline("L9", CRS, np.array([[0.0, 0.0], [200.0, 0.0]]))
    st.save_profile(p)
    for name in ("L9_xzv.txt", "L9_topography.txt"):
        shutil.copy(FIXTURES / "seismic" / name, tmp_path / name)
    src = tmp_path / "L9_xzv.txt"
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("v", p.id, "", "srt_model", str(src), mt, sha, "refrapy_xzv",
                            {"z_kind": "elevation"}, {}, name="L9 Vp"))
    provider, prj = SectionDataProvider(st), QgsProject()
    _choose(prj, ["v"])
    lyr = sync(st, provider, prj, create=True)["models"]
    everything = lyr.featureCount()
    unresolved = sum(1 for f in lyr.getFeatures() if not f["resolved"])
    assert everything > unresolved > 0
    provider.set_style("v", replace(provider.style("v"), fade_coverage=True))
    sync(st, provider, prj)
    assert lyr.featureCount() == everything - unresolved
    assert all(f["resolved"] for f in lyr.getFeatures())


def test_an_unchanged_sync_keeps_the_features(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, _p, provider, prj = setup
    _choose(prj, ["d"])
    lyr = sync(st, provider, prj, create=True)["models"]
    ids = sorted(f.id() for f in lyr.getFeatures())
    sync(st, provider, prj)
    assert sorted(f.id() for f in lyr.getFeatures()) == ids


def test_unticking_removes_the_layer_and_unknown_ids_are_ignored(setup):
    from groundwork_geophysics.ui.view3d_layers import layers_3d, sync
    st, _p, provider, prj = setup
    _choose(prj, ["d", "gone"])
    assert sync(st, provider, prj, create=True)["models"].featureCount() > 0
    _choose(prj, [])
    assert sync(st, provider, prj) == {} and layers_3d(prj) == {}


def test_without_create_no_layer_appears(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, _p, provider, prj = setup
    _choose(prj, ["d"])
    assert sync(st, provider, prj) == {}


def test_a_deleted_model_leaves_the_3d_view(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, _p, provider, prj = setup
    _choose(prj, ["d"])
    sync(st, provider, prj, create=True)
    provider.remove_dataset("d")
    assert sync(st, provider, prj) == {}


def test_a_model_that_cannot_be_read_is_skipped(setup, tmp_path):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _model(st, p, tmp_path, did="bad")
    (tmp_path / "bad.dat").write_text("not a model")
    provider.notify_changed()
    _choose(prj, ["d", "bad"])
    lyr = sync(st, provider, prj, create=True)["models"]
    assert {f["dataset_id"] for f in lyr.getFeatures()} == {"d"}


def test_boreholes_stand_at_their_map_position_one_feature_per_interval(setup):
    from groundwork_geophysics.ui.view3d_layers import BOREHOLES_NAME, sync
    st, p, provider, prj = setup
    _choose(prj, boreholes=[p.id])
    lyr = sync(st, provider, prj, create=True)["boreholes"]
    assert lyr.name() == BOREHOLES_NAME and lyr.providerType() == "memory"
    rows = sorted((f["text"], f["top"], f["bottom"]) for f in lyr.getFeatures())
    assert rows == [("clay", 3.0, 8.0), ("sand", 0.0, 3.0)]
    geom = next(f for f in lyr.getFeatures() if f["text"] == "sand").geometry().constGet()
    pts = [(v.x(), v.y(), v.z()) for v in geom.vertices()]
    assert pts == [(10.0, 2.0, 100.0), (10.0, 2.0, 97.0)]
    assert lyr.renderer3D() is not None


def test_a_borehole_on_two_ticked_profiles_appears_once(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    q = profile_from_polyline("P2", CRS, np.array([[10.0, -30.0], [10.0, 30.0]]))
    st.save_profile(q)
    provider.notify_changed()
    _choose(prj, boreholes=[p.id, q.id])
    lyr = sync(st, provider, prj, create=True)["boreholes"]
    assert lyr.featureCount() == 2


def test_the_layers_keep_their_place_when_the_project_comes_back(setup):
    from groundwork_geophysics.ui.view3d_layers import layers_3d, sync
    st, p, provider, prj = setup
    _choose(prj, ["d"], [p.id])
    first = sync(st, provider, prj, create=True)
    # as a memory layer read back from a project file: empty, a new object without the mark
    first["models"].dataProvider().truncate()
    first["models"].setProperty("groundworkFilled", None)
    again = sync(st, provider, prj)
    assert again["models"].id() == first["models"].id()
    assert again["models"].featureCount() > 0 and set(layers_3d(prj)) == {"models", "boreholes"}


def test_a_borehole_without_collar_height_starts_at_the_sections_surface(setup):
    import numpy as np

    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    provider.context_source = lambda profile: ContextItems(
        points=[replace(_borehole(), z_top=None)])
    provider.notify_changed()
    _choose(prj, boreholes=[p.id])
    lyr = sync(st, provider, prj, create=True)["boreholes"]
    line_s, line_z = provider.surface(p.id).line
    top = max(v.z() for f in lyr.getFeatures() for v in f.geometry().constGet().vertices())
    assert top == pytest.approx(float(np.interp(10.0, line_s, line_z)))


def test_a_style_only_refill_leaves_the_boreholes_alone(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose(prj, ["d"], [p.id])
    lyr = sync(st, provider, prj, create=True)["boreholes"]
    provider.context_source = lambda profile: ContextItems(points=[])
    provider.notify_changed()
    assert sync(st, provider, prj, boreholes=False)["boreholes"].featureCount() == 2
    assert sync(st, provider, prj)["boreholes"] is lyr and lyr.featureCount() == 0


def _two_models(st, p, provider, prj, tmp_path):
    _model(st, p, tmp_path, did="e")
    provider.notify_changed()
    _choose(prj, ["d", "e"])


def test_a_filter_on_the_layer_never_leaves_stale_cells(setup, tmp_path):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _two_models(st, p, provider, prj, tmp_path)
    lyr = sync(st, provider, prj, create=True)["models"]
    n = lyr.featureCount()
    lyr.setSubsetString("\"dataset_id\" = 'e'")
    style = provider.style("d")
    provider.set_style("d", replace(style, scale=replace(style.scale, cmap="viridis")))
    sync(st, provider, prj)
    _choose(prj, ["d"])
    sync(st, provider, prj)
    lyr.setSubsetString("")
    assert lyr.featureCount() == n // 2
    assert {f["dataset_id"] for f in lyr.getFeatures()} == {"d"}


def test_one_failing_model_does_not_stop_the_others(setup, tmp_path, monkeypatch):
    from groundwork_geophysics.ui import view3d_layers
    st, p, provider, prj = setup
    _two_models(st, p, provider, prj, tmp_path)
    real = view3d_layers._model_features

    def flaky(layer, profile, dataset, section_layer):
        if dataset.id == "e":
            raise RuntimeError("broken")
        return real(layer, profile, dataset, section_layer)
    monkeypatch.setattr(view3d_layers, "_model_features", flaky)
    lyr = view3d_layers.sync(st, provider, prj, create=True)["models"]
    assert {f["dataset_id"] for f in lyr.getFeatures()} == {"d"}


def test_hiding_a_borehole_in_the_section_takes_it_out_of_3d(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose(prj, boreholes=[p.id])
    lyr = sync(st, provider, prj, create=True)["boreholes"]
    provider.set_boreholes_hidden(p.id, [("bh", "B1")], True)
    sync(st, provider, prj, boreholes=False)               # a redraw, as the plugin does
    assert lyr.featureCount() == 0
    provider.set_boreholes_hidden(p.id, [("bh", "B1")], False)
    sync(st, provider, prj, boreholes=False)
    assert lyr.featureCount() == 2


def test_the_borehole_layer_field_names_the_layer(setup):
    from qgis.core import QgsVectorLayer

    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    bh = QgsVectorLayer("Point?crs=EPSG:25832", "Cores 2024", "memory")
    prj.addMapLayer(bh)
    provider.context_source = lambda profile: ContextItems(
        points=[replace(_borehole(), layer_id=bh.id())])
    provider.notify_changed()
    _choose(prj, boreholes=[p.id])
    lyr = sync(st, provider, prj, create=True)["boreholes"]
    assert {f["layer"] for f in lyr.getFeatures()} == {"Cores 2024"}


def test_a_profile_without_real_heights_stays_out_of_3d(qgis_app, tmp_path):
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_layers import sync
    st = ProjectStore.create(tmp_path / "l.gpkg", CRS)
    p = profile_from_polyline("Local", CRS, np.array([[0.0, 0.0], [60.0, 0.0]]))
    st.save_profile(p)
    src = tmp_path / "m.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("m", p.id, "", "ert_model", str(src), mt, sha, "r2_res_dat",
                            {"z_kind": "depth"}, {}, name="Depth model"))
    provider, prj = SectionDataProvider(st), QgsProject()
    provider.context_source = lambda profile: ContextItems(points=[_borehole()])
    assert provider.is_local(p.id)
    _choose(prj, ["m"], [p.id])
    layers = sync(st, provider, prj, create=True)
    assert all(layer.featureCount() == 0 for layer in layers.values())


def test_boreholes_are_drawn_as_lines_at_their_own_heights(setup):
    """QGIS lays a buffered (wide) 3D line flat at height 0, so a vertical borehole became a
    disc at sea level; lines drawn as "simple lines" keep each vertex's height."""
    from qgis._3d import QgsAbstractMaterialSettings, QgsLine3DSymbol
    from qgis.core import Qgis
    from qgis.PyQt import sip

    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose(prj, boreholes=[p.id])
    lyr = sync(st, provider, prj, create=True)["boreholes"]
    symbol = sip.cast(lyr.renderer3D().symbol(), QgsLine3DSymbol)
    assert symbol.renderAsSimpleLines()
    assert symbol.altitudeClamping() == Qgis.AltitudeClamping.Absolute
    material = symbol.materialSettings()
    assert material.type() == "simpleline"
    prop = material.dataDefinedProperties().property(QgsAbstractMaterialSettings.Property.Ambient)
    assert prop.isActive() and prop.field() == "color"


# -- curtains follow the section's mode: smooth = point cloud, contours = 3D lines ------------
def _mode(provider, p, mode, did="d", **kw):
    provider.layers(p.id)                         # the style exists once the model is read
    provider.set_style(did, replace(provider.style(did), mode=mode, **kw))


def test_a_cells_model_stays_cells(setup):
    from groundwork_geophysics.ui.view3d_layers import clouds_3d, sync
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    out = sync(st, provider, prj, create=True)
    assert out["models"].featureCount() > 0
    assert not out.get("clouds") and not clouds_3d(prj) and "contours" not in out


def test_a_smooth_model_is_a_point_cloud(setup):
    from qgis.core import QgsPointCloudLayer

    from groundwork_geophysics.ui.view3d_layers import SMOOTH_GROUP, cloud_folder, sync
    st, p, provider, prj = setup
    _mode(provider, p, "smooth")
    _choose(prj, ["d"])
    out = sync(st, provider, prj, create=True)
    assert "models" not in out                    # no cells for a smooth model
    cloud = out["clouds"]["d"]
    assert isinstance(cloud, QgsPointCloudLayer) and cloud.isValid()
    assert cloud.pointCount() > 0 and cloud.name() == "Model d"
    assert Path(cloud.source()).parent == cloud_folder(st)
    assert cloud.renderer().type() == "rgb"
    assert prj.layerTreeRoot().findLayer(cloud.id()).parent().name() == SMOOTH_GROUP


def test_smooth_and_contours_gives_both_in_the_sections_contour_colour(setup):
    from qgis.PyQt.QtGui import QColor

    from groundwork_geophysics.section.display_render import CONTOUR_DARKER
    from groundwork_geophysics.ui.view3d_layers import CONTOURS_NAME, sync
    st, p, provider, prj = setup
    _mode(provider, p, "smooth+contours")
    _choose(prj, ["d"])
    out = sync(st, provider, prj, create=True)
    lines = out["contours"]
    assert out["clouds"]["d"].isValid()
    assert lines.name() == CONTOURS_NAME and lines.featureCount() > 0
    f = next(lines.getFeatures())
    assert f["dataset_id"] == "d" and f.geometry().constGet().is3D()
    rgb = provider.style("d").scale.rgba([f["level"]])[0][:3]
    assert f["color"] == QColor(*(int(c) for c in rgb)).darker(CONTOUR_DARKER).name()


def test_contours_alone_are_lines_only(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _mode(provider, p, "contours")
    _choose(prj, ["d"])
    out = sync(st, provider, prj, create=True)
    assert out["contours"].featureCount() > 0
    assert not out.get("clouds") and "models" not in out


def test_switching_back_to_cells_removes_the_cloud(setup):
    from qgis.core import QgsPointCloudLayer

    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _mode(provider, p, "smooth")
    _choose(prj, ["d"])
    path = Path(sync(st, provider, prj, create=True)["clouds"]["d"].source())
    _mode(provider, p, "cells")
    out = sync(st, provider, prj)                 # a redraw, not the dialog
    sync(st, provider, prj)                       # a file still held is removed next time
    assert not out.get("clouds")
    assert not [la for la in prj.mapLayers().values() if isinstance(la, QgsPointCloudLayer)]
    assert out["models"].featureCount() > 0      # the cells come back by themselves
    assert not path.exists()


def test_a_scale_change_rewrites_the_file_and_keeps_the_users_style(setup):
    from qgis.core import QgsPointCloudAttributeByRampRenderer

    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _mode(provider, p, "smooth")
    _choose(prj, ["d"])
    cloud = sync(st, provider, prj, create=True)["clouds"]["d"]
    old = Path(cloud.source())
    ramp = QgsPointCloudAttributeByRampRenderer()
    ramp.setAttribute("Value")
    cloud.setRenderer(ramp)                       # the user's own style
    style = provider.style("d")
    provider.set_style("d", replace(style, scale=replace(style.scale, cmap="viridis")))
    again = sync(st, provider, prj)["clouds"]["d"]
    sync(st, provider, prj)
    assert again is cloud and again.isValid()
    assert Path(again.source()) != old and not old.exists()
    assert again.renderer().type() == "ramp"


def test_unticking_removes_cloud_and_lines(setup):
    from groundwork_geophysics.ui.view3d_layers import SMOOTH_GROUP, clouds_3d, layers_3d, sync
    st, p, provider, prj = setup
    _mode(provider, p, "smooth+contours")
    _choose(prj, ["d"])
    sync(st, provider, prj, create=True)
    _choose(prj, [])
    sync(st, provider, prj)
    assert not clouds_3d(prj) and "contours" not in layers_3d(prj)
    assert prj.layerTreeRoot().findGroup(SMOOTH_GROUP) is None


def test_a_missing_file_is_rebuilt(setup, tmp_path):
    from groundwork_geophysics.ui.view3d_layers import cloud_folder, sync
    st, p, provider, prj = setup
    _mode(provider, p, "smooth")
    _choose(prj, ["d"])
    cloud = sync(st, provider, prj, create=True)["clouds"]["d"]
    cloud.setDataSource(str(tmp_path / "gone.las"), cloud.name(), "pdal")   # as if deleted
    assert not cloud.isValid()
    sync(st, provider, prj)
    assert cloud.isValid() and Path(cloud.source()).parent == cloud_folder(st)


def test_the_message_counts_cells_smooth_models_lines_and_intervals(setup):
    from groundwork_geophysics.ui.view3d_layers import shown_summary, sync
    st, p, provider, prj = setup
    _mode(provider, p, "smooth+contours")
    _choose(prj, ["d"], [p.id])
    text = shown_summary(sync(st, provider, prj, create=True))
    assert "1 smooth model" in text and "contour lines" in text
    assert "borehole intervals" in text and "model cells" not in text
    assert shown_summary({}) == "nothing that could be built"


# -- final review: files, removed layers, retries, projects ---------------------------------
def test_the_users_own_files_beside_the_store_are_never_deleted(setup):
    from groundwork_geophysics.ui.view3d_layers import cloud_folder, sync
    st, p, provider, prj = setup
    folder = cloud_folder(st)
    folder.mkdir()
    own = [folder / "scan.las", folder / "scan.copc.laz", folder / "drone.las.part"]
    for f in own:
        f.write_bytes(b"theirs")
    _choose(prj, ["d"])
    sync(st, provider, prj, create=True)          # cells: no cloud at all
    _mode(provider, p, "smooth")
    sync(st, provider, prj, create=True)
    style = provider.style("d")
    provider.set_style("d", replace(style, scale=replace(style.scale, cmap="viridis")))
    sync(st, provider, prj)
    assert all(f.exists() for f in own)


def test_a_cloud_removed_by_hand_stays_removed(setup):
    from groundwork_geophysics.ui.view3d_layers import clouds_3d, sync
    st, p, provider, prj = setup
    _mode(provider, p, "smooth")
    _choose(prj, ["d"])
    cloud = sync(st, provider, prj, create=True)["clouds"]["d"]
    sync(st, provider, prj)                       # a redraw while it is there
    prj.removeMapLayer(cloud.id())
    sync(st, provider, prj)                       # a redraw
    assert not clouds_3d(prj)


def test_a_model_with_nothing_to_show_gets_its_cloud_once_it_has(setup, monkeypatch):
    from groundwork_geophysics.ui import view3d_layers
    st, p, provider, prj = setup
    _mode(provider, p, "smooth")
    _choose(prj, ["d"])
    real = view3d_layers._write_cloud
    monkeypatch.setattr(view3d_layers, "_write_cloud", lambda *a: 0)    # all faded, say
    assert not view3d_layers.sync(st, provider, prj, create=True).get("clouds")
    monkeypatch.setattr(view3d_layers, "_write_cloud", real)
    style = provider.style("d")
    provider.set_style("d", replace(style, scale=replace(style.scale, cmap="viridis")))
    assert view3d_layers.sync(st, provider, prj)["clouds"]["d"].isValid()


def test_going_back_to_an_earlier_scale_reuses_its_file(setup):
    import os
    import shutil as sh

    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _mode(provider, p, "smooth")
    _choose(prj, ["d"])
    first = Path(sync(st, provider, prj, create=True)["clouds"]["d"].source())
    keep = first.with_name("held.bak")
    sh.copy2(first, keep)
    style = provider.style("d")
    provider.set_style("d", replace(style, scale=replace(style.scale, cmap="viridis")))
    sync(st, provider, prj)
    if not first.exists():                        # as if QGIS still held it open
        sh.copy2(keep, first)
    stamp = os.stat(first).st_mtime_ns
    provider.set_style("d", style)
    cloud = sync(st, provider, prj)["clouds"]["d"]
    assert Path(cloud.source()) == first and cloud.isValid()
    assert os.stat(first).st_mtime_ns == stamp    # not written again


def test_a_new_project_does_not_inherit_what_the_last_one_showed(setup, fake_iface):
    """What the last sync showed is kept on the project object, which QGIS reuses for the
    next project: opening a store starts afresh, so it never adds a layer by itself."""
    from qgis.core import QgsProject

    from groundwork_geophysics import classFactory
    from groundwork_geophysics.ui.view3d_layers import layers_3d
    st, _p, _provider, _prj = setup
    prj = QgsProject.instance()
    prj.clear()
    _choose(prj, ["d"])
    prj.setProperty("groundwork3dNeeds", "")      # the last project showed nothing
    plug = classFactory(fake_iface)
    plug.initGui()
    try:
        plug.set_store(st)
        assert "models" not in layers_3d(prj)
    finally:
        plug.unload()
        prj.clear()
        prj.setProperty("groundwork3dNeeds", None)
