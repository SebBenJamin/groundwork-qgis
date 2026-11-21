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


def _choose(prj, models=(), boreholes=(), **kw):
    from groundwork_geophysics.ui.view3d_layers import Choice, write_choice
    write_choice(prj, Choice(frozenset(models), frozenset(boreholes), **kw))


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
    sand = next(f for f in lyr.getFeatures() if f["text"] == "sand")
    # a round column: its base at the interval's bottom, extruded up by its thickness
    assert {v.z() for v in sand.geometry().constGet().vertices()} == {97.0}
    centre = sand.geometry().centroid().asPoint()
    assert (centre.x(), centre.y()) == pytest.approx((10.0, 2.0), abs=1e-6)
    assert sand["height"] == pytest.approx(3.0)
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
    assert again["models"].featureCount() > 0
    assert set(layers_3d(prj)) == {"models", "boreholes", "ground"}


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
    top = max(min(v.z() for v in f.geometry().constGet().vertices()) + f["height"]
              for f in lyr.getFeatures())
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


def test_boreholes_are_columns_you_can_see_and_identify(setup):
    """Simple 3D lines are thin and cannot be identified in the 3D view: each interval is a
    round column (a polygon extruded by the interval's thickness), shaded like the
    curtains, 0.6 x the station spacing across."""
    from qgis._3d import QgsPolygon3DSymbol
    from qgis.core import Qgis, QgsAbstract3DSymbol
    from qgis.PyQt import sip

    from groundwork_geophysics.ui.project_actions import station_radius
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose(prj, boreholes=[p.id])
    lyr = sync(st, provider, prj, create=True)["boreholes"]
    symbol = sip.cast(lyr.renderer3D().symbol(), QgsPolygon3DSymbol)
    assert symbol.altitudeClamping() == Qgis.AltitudeClamping.Absolute
    prop = symbol.dataDefinedProperties().property(QgsAbstract3DSymbol.Property.ExtrusionHeight)
    assert prop.isActive() and prop.field() == "height"
    f = next(lyr.getFeatures())
    centre = f.geometry().centroid().asPoint()
    radius = max(((v.x() - centre.x()) ** 2 + (v.y() - centre.y()) ** 2) ** 0.5
                 for v in f.geometry().constGet().vertices())
    assert radius == pytest.approx(2 * station_radius(st), rel=1e-6)


def test_the_borehole_columns_take_the_width_chosen(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup

    def radius(layer):
        f = next(layer.getFeatures())
        centre = f.geometry().centroid().asPoint()
        return max(((v.x() - centre.x()) ** 2 + (v.y() - centre.y()) ** 2) ** 0.5
                   for v in f.geometry().constGet().vertices())

    _choose(prj, boreholes=[p.id], borehole_width=1.5)        # the diameter
    lyr = sync(st, provider, prj, create=True)["boreholes"]
    assert radius(lyr) == pytest.approx(0.75, rel=1e-6)
    _choose(prj, boreholes=[p.id], borehole_width=3.0)
    assert radius(sync(st, provider, prj)["boreholes"]) == pytest.approx(1.5, rel=1e-6)


def test_a_borehole_layer_saved_as_lines_becomes_columns(setup):
    """A project saved while boreholes were lines comes back with columns."""
    from qgis.core import QgsVectorLayer, QgsWkbTypes

    from groundwork_geophysics.ui.view3d_layers import layers_3d, sync
    st, p, provider, prj = setup
    old = QgsVectorLayer(f"LineStringZ?crs={CRS}", "Boreholes in 3D", "memory")
    old.setCustomProperty("geophysics_workbench/view3d", "boreholes")
    prj.addMapLayer(old)
    assert layers_3d(prj).get("boreholes") is old
    _choose(prj, boreholes=[p.id])
    lyr = sync(st, provider, prj)["boreholes"]
    assert lyr.geometryType() == QgsWkbTypes.GeometryType.PolygonGeometry
    assert lyr.featureCount() == 2


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
    assert "1 point cloud" in text and "contour lines" in text
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
        assert not layers_3d(prj)
    finally:
        plug.unload()
        prj.clear()
        prj.setProperty("groundwork3dNeeds", None)


# -- a representation per model -----------------------------------------------------------
def test_the_representations_and_options_round_trip_with_the_choice(setup):
    from groundwork_geophysics.ui.view3d_layers import Choice, read_choice
    _st, _p, _provider, prj = setup
    _choose(prj, ["d", "e"], looks={"d": "picture", "e": "cloud"}, interpretation=True,
            borehole_width=1.5, station_size=0.25)
    choice = read_choice(prj)
    assert choice == Choice(frozenset({"d", "e"}), frozenset(), {"d": "picture", "e": "cloud"},
                            True, 1.5, 0.25)
    assert choice.look_of("d") == "picture" and choice.look_of("x") == "section"
    _choose(prj, ["d"])
    assert read_choice(prj) == Choice(frozenset({"d"}))
    assert read_choice(prj).borehole_width is None and not read_choice(prj).interpretation


def test_an_older_choice_of_pictures_gives_every_model_a_picture(setup):
    import json

    from groundwork_geophysics.ui.project_actions import SCOPE
    from groundwork_geophysics.ui.view3d_layers import ENTRY, read_choice
    _st, _p, _provider, prj = setup
    prj.writeEntry(SCOPE, ENTRY, json.dumps({"models": ["d", "e"], "boreholes": [],
                                             "look": "pictures"}))
    choice = read_choice(prj)
    assert choice.look_of("d") == choice.look_of("e") == "picture"
    prj.writeEntry(SCOPE, ENTRY, json.dumps({"models": ["d"], "look": "layers",
                                             "looks": {"d": "nonsense"}}))
    assert read_choice(prj).look_of("d") == "section"


def test_a_point_cloud_whatever_the_section_shows(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _mode(provider, p, "cells")
    _choose(prj, ["d"], looks={"d": "cloud"})
    out = sync(st, provider, prj, create=True)
    assert out["clouds"]["d"].isValid() and out["clouds"]["d"].pointCount() > 0
    assert {"models", "contours", "pictures"}.isdisjoint(out)
    _mode(provider, p, "contours")                    # with the section's contour lines
    out = sync(st, provider, prj)
    assert out["clouds"]["d"].isValid() and out["contours"].featureCount() > 0


def test_models_of_different_representations_mix(setup, tmp_path):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _model(st, p, tmp_path, did="e")
    _model(st, p, tmp_path, did="f")
    provider.notify_changed()
    _mode(provider, p, "cells", did="d")
    _mode(provider, p, "cells", did="e")
    _mode(provider, p, "smooth", did="f")
    _choose(prj, ["d", "e", "f"], looks={"e": "picture"})
    out = sync(st, provider, prj, create=True)
    assert {f["dataset_id"] for f in out["models"].getFeatures()} == {"d"}
    assert set(out["clouds"]) == {"f"} and set(out["pictures"]) == {p.id}


# -- section pictures (3D Tiles), one per profile -------------------------------------------
def _choose_pictures(prj, models=(), boreholes=(), **kw):
    _choose(prj, models, boreholes, looks={m: "picture" for m in models}, **kw)


def test_pictures_are_one_tiled_scene_per_profile_and_nothing_else(setup):
    from qgis.core import QgsTiledSceneLayer

    from groundwork_geophysics.ui.view3d_layers import (PICTURES_GROUP, cloud_folder,
                                                        shown_summary, sync)
    st, p, provider, prj = setup
    _mode(provider, p, "smooth+contours")
    _choose_pictures(prj, ["d"])
    out = sync(st, provider, prj, create=True)
    picture = out["pictures"][p.id]
    assert isinstance(picture, QgsTiledSceneLayer) and picture.isValid()
    assert picture.name() == "P1"
    assert {"models", "clouds", "contours"}.isdisjoint(out)
    files = sorted(f.suffix for f in cloud_folder(st).iterdir())
    assert files == [".glb", ".json"]
    assert prj.layerTreeRoot().findLayer(picture.id()).parent().name() == PICTURES_GROUP
    assert "1 section picture" in shown_summary(out)


def test_the_picture_hangs_under_the_profile_line(setup):
    import json
    import struct

    from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject,
                           QgsVector3D)

    from groundwork_geophysics.ui.view3d_layers import cloud_folder, sync
    st, p, provider, prj = setup
    _mode(provider, p, "smooth")
    _choose_pictures(prj, ["d"])
    sync(st, provider, prj, create=True)
    folder = cloud_folder(st)
    tileset = json.loads(next(folder.glob("*.json")).read_text())
    data = next(folder.glob("*.glb")).read_bytes()
    jlen = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20:20 + jlen])
    acc = doc["accessors"][doc["meshes"][0]["primitives"][0]["attributes"]["POSITION"]]
    view = doc["bufferViews"][acc["bufferView"]]
    start = 20 + jlen + 8 + view["byteOffset"]
    pos = np.frombuffer(data[start:start + view["byteLength"]], np.float32).reshape(-1, 3)
    t = np.array(tileset["root"]["transform"]).reshape(4, 4).T
    east, up, south = pos[:, 0], pos[:, 1], pos[:, 2]            # glTF is y-up
    ecef = (t @ np.column_stack([east, -south, up, np.ones(len(pos))]).T).T[:, :3]
    back = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4978"),
                                  QgsCoordinateReferenceSystem(CRS), QgsProject.instance())
    pts = np.array([[q.x(), q.y(), q.z()] for q in
                    (back.transform(QgsVector3D(*map(float, e))) for e in ecef)])
    s, offset = p.chainage.project(pts[:, :2])
    from groundwork_geophysics.core.view3d import curtain_gap        # each face a gap off
    assert np.abs(np.abs(offset) - curtain_gap(p.chainage.length)).max() < 0.01
    mesh = provider.layers(p.id)[0].mesh
    _s0, _s1, z0, z1 = mesh.bounds()
    assert pts[:, 2].min() >= z0 - 0.5 and pts[:, 2].max() <= z1 + 5.0


def test_a_style_change_redraws_the_picture_in_the_same_layer(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _mode(provider, p, "smooth")
    _choose_pictures(prj, ["d"])
    picture = sync(st, provider, prj, create=True)["pictures"][p.id]
    old = picture.source()
    _mode(provider, p, "smooth+contours")
    again = sync(st, provider, prj)["pictures"][p.id]
    sync(st, provider, prj)
    assert again is picture and again.isValid() and again.source() != old
    from groundwork_geophysics.ui.view3d_layers import cloud_folder
    assert len(list(cloud_folder(st).glob("*.json"))) == 1     # the old one let go


def test_two_models_of_a_profile_are_one_picture(setup, tmp_path):
    from groundwork_geophysics.ui.view3d_layers import cloud_folder, pictures_3d, sync
    st, p, provider, prj = setup
    _model(st, p, tmp_path, did="e")
    provider.notify_changed()
    _choose_pictures(prj, ["d"])
    first = sync(st, provider, prj, create=True)["pictures"][p.id]
    one = first.source()
    _choose_pictures(prj, ["d", "e"])
    out = sync(st, provider, prj, create=True)
    sync(st, provider, prj)
    assert list(out["pictures"]) == [p.id] and out["pictures"][p.id] is first
    assert first.source() != one and len(pictures_3d(prj)) == 1
    assert len(list(cloud_folder(st).glob("*.json"))) == 1     # the old one let go
    assert len(list(cloud_folder(st).glob("*.glb"))) == 1


def _interp_piece(provider, p, name="K", line=False):
    from groundwork_geophysics.core.interpretation import InterpFeature, InterpPiece, new_id
    st = provider.store
    s0, s1, z0, z1 = provider.layers(p.id)[0].mesh.bounds()
    sm, zm = (s0 + s1) / 2, (z0 + z1) / 2
    vertices = [(sm - 5, zm), (sm + 5, zm - 2)] if line else \
        [(sm - 5, zm + 1), (sm + 5, zm + 1), (sm + 5, zm - 1), (sm - 5, zm - 1)]
    st.ensure_interpretation()
    v = st.current_version()
    f = InterpFeature(new_id(), v.id, type="clay", name=name)
    st.save_feature(f)
    st.save_piece(InterpPiece(new_id(), v.id, f.id, p.id, "line" if line else "polygon",
                              vertices))
    provider.notify_redraw()
    return f


def test_the_picture_shows_the_interpretation_only_when_asked(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose_pictures(prj, ["d"])
    picture = sync(st, provider, prj, create=True)["pictures"][p.id]
    plain = picture.source()
    _interp_piece(provider, p)
    assert sync(st, provider, prj)["pictures"][p.id].source() == plain     # not asked
    _choose_pictures(prj, ["d"], interpretation=True)
    with_it = sync(st, provider, prj)["pictures"][p.id].source()
    assert with_it != plain
    _interp_piece(provider, p, name="L", line=True)                        # another edit
    assert sync(st, provider, prj)["pictures"][p.id].source() != with_it


def test_the_picture_follows_the_interpretations_2d_style(setup):
    from qgis.core import QgsFillSymbol, QgsSingleSymbolRenderer, QgsVectorLayer

    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _interp_piece(provider, p)
    polygons = QgsVectorLayer(f"PolygonZ?crs={CRS}&field=feature_id:string&field=name:string",
                              "polygons", "memory")
    polygons.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "red"})))
    provider.interp_layers = lambda: {"interp_polygons_3d": polygons}
    _choose_pictures(prj, ["d"], interpretation=True)
    red = sync(st, provider, prj, create=True)["pictures"][p.id].source()
    polygons.setRenderer(QgsSingleSymbolRenderer(QgsFillSymbol.createSimple({"color": "blue"})))
    provider.notify_redraw()
    assert sync(st, provider, prj)["pictures"][p.id].source() != red


def test_back_to_the_section_look_removes_the_pictures(setup):
    from groundwork_geophysics.ui.view3d_layers import (PICTURES_GROUP, cloud_folder,
                                                        pictures_3d, sync)
    st, p, provider, prj = setup
    _choose_pictures(prj, ["d"])
    sync(st, provider, prj, create=True)
    _choose(prj, ["d"])
    out = sync(st, provider, prj, create=True)
    sync(st, provider, prj)
    assert not pictures_3d(prj) and out["models"].featureCount() > 0
    assert not list(cloud_folder(st).glob("*.json"))
    assert prj.layerTreeRoot().findGroup(PICTURES_GROUP) is None


def test_a_folder_name_with_a_hash_still_gives_a_valid_picture(qgis_app, tmp_path):
    """The tileset path goes through QGIS's own URI encoding: a "#" is not a URL fragment."""
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.view3d_layers import pictures_3d, sync
    folder = tmp_path / "survey #3"
    folder.mkdir()
    st = ProjectStore.create(folder / "p.gpkg", CRS)
    p = profile_from_polyline("P1", CRS, np.array([[0.0, 0.0], [60.0, 0.0]]))
    st.save_profile(p)
    _model(st, p, folder)
    provider = SectionDataProvider(st)
    prj = QgsProject()
    _choose_pictures(prj, ["d"])
    sync(st, provider, prj, create=True)
    picture = pictures_3d(prj)[p.id]
    assert picture.isValid()


# -- two faces per curtain, so an interpretation in the plane is never hidden ---------------
def test_cells_are_two_faces_standing_back_from_the_plane(setup):
    from qgis._3d import Qgs3DTypes, QgsPolygon3DSymbol
    from qgis.PyQt import sip

    from groundwork_geophysics.core.view3d import curtain_gap
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    lyr = sync(st, provider, prj, create=True)["models"]
    gap = curtain_gap(p.chainage.length)
    f = next(lyr.getFeatures())
    parts = f.geometry().constGet()
    assert parts.numGeometries() == 2                    # one face per side
    ys = sorted({round(v.y(), 6) for v in parts.vertices()})
    assert ys == pytest.approx([-gap, gap])              # the line runs east at y = 0
    symbol = sip.cast(lyr.renderer3D().symbol(), QgsPolygon3DSymbol)
    assert not symbol.addBackFaces() and symbol.cullingMode() == Qgs3DTypes.CullingMode.Back


def test_a_cells_layer_saved_with_one_face_becomes_two(setup):
    from qgis.core import QgsVectorLayer, QgsWkbTypes

    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    old = QgsVectorLayer(f"PolygonZ?crs={CRS}", "Models in 3D", "memory")
    old.setCustomProperty("geophysics_workbench/view3d", "models")
    prj.addMapLayer(old)
    _choose(prj, ["d"])
    lyr = sync(st, provider, prj)["models"]
    assert QgsWkbTypes.isMultiType(lyr.wkbType()) and lyr.featureCount() > 0


def test_a_picture_is_two_faces_standing_back_from_the_plane(setup):
    import json
    import struct

    from groundwork_geophysics.core.view3d import curtain_gap
    from groundwork_geophysics.ui.view3d_layers import cloud_folder, sync
    st, p, provider, prj = setup
    _choose_pictures(prj, ["d"])
    sync(st, provider, prj, create=True)
    data = next(cloud_folder(st).glob("*.glb")).read_bytes()
    jlen = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20:20 + jlen])
    prim = doc["meshes"][0]["primitives"][0]
    acc = doc["accessors"][prim["attributes"]["POSITION"]]
    view = doc["bufferViews"][acc["bufferView"]]
    start = 20 + jlen + 8 + view["byteOffset"]
    pos = np.frombuffer(data[start:start + view["byteLength"]], np.float32).reshape(-1, 3)
    north = -pos[:, 2]                                    # glTF z is south, for this line
    gap = curtain_gap(p.chainage.length)
    half = len(pos) // 2
    assert np.allclose(north[:half] - north[half:], 2 * gap, atol=1e-3)
    indices = doc["accessors"][prim["indices"]]["count"]
    assert indices == 2 * 3 * (half // 2 - 1) * 2       # two triangles per column gap, twice


# -- what a new 3D view looks at ----------------------------------------------------------
def test_the_box_holds_the_shown_curtains_and_boreholes(setup):
    from groundwork_geophysics.ui.view3d_layers import shown_box, sync
    st, p, provider, prj = setup
    assert shown_box(st, provider, prj) is None                 # nothing ticked
    _choose(prj, ["d"], [p.id])
    out = sync(st, provider, prj, create=True)
    xmin, ymin, xmax, ymax, zmin, zmax = shown_box(st, provider, prj)
    s0, s1, z0, z1 = provider.layers(p.id)[0].mesh.bounds()
    column = out["boreholes"].extent3D()
    assert xmin <= s0 + 1e-6 and xmax >= s1 - 1e-6 and xmax - xmin < s1 - s0 + 2.0
    assert ymin <= 0.0 and ymax == pytest.approx(column.yMaximum())   # the borehole, off the line
    assert (zmin, zmax) == pytest.approx((min(z0, column.zMinimum()),
                                          max(z1, column.zMaximum())))


def test_the_box_of_section_pictures_comes_from_their_models(setup):
    from groundwork_geophysics.ui.view3d_layers import shown_box, sync
    st, p, provider, prj = setup
    _choose_pictures(prj, ["d"])
    sync(st, provider, prj, create=True)
    xmin, _ymin, xmax, _ymax, zmin, zmax = shown_box(st, provider, prj)
    s0, s1, z0, z1 = provider.layers(p.id)[0].mesh.bounds()
    assert (xmin, xmax, zmin, zmax) == pytest.approx((s0, s1, z0, z1), abs=0.01)


# -- the ground line ----------------------------------------------------------------------
def _ground_points(layer, profile_id):
    f = next(f for f in layer.getFeatures() if f["profile_id"] == profile_id)
    return np.array([(v.x(), v.y(), v.z()) for v in f.geometry().constGet().vertices()])


def test_a_ticked_profile_shows_the_sections_ground_line(setup):
    from qgis.core import QgsWkbTypes

    from groundwork_geophysics.ui.view3d_layers import GROUND_NAME, sync
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    ground = sync(st, provider, prj, create=True)["ground"]
    assert ground.name() == GROUND_NAME and ground.providerType() == "memory"
    assert ground.readOnly() and ground.wkbType() == QgsWkbTypes.Type.LineStringZ
    (f,) = list(ground.getFeatures())
    assert f["profile_id"] == p.id and f["profile"] == "P1"
    s, z = provider.surface(p.id).line
    xy = p.chainage.to_xy(np.asarray(s))
    assert np.allclose(_ground_points(ground, p.id), np.column_stack([xy, z]), atol=1e-6)


def test_ticked_boreholes_bring_their_profiles_ground_line_too(setup, tmp_path):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    q = profile_from_polyline("P2", CRS, np.array([[0.0, 20.0], [60.0, 20.0]]))
    st.save_profile(q)
    _model(st, q, tmp_path, did="e")
    provider.notify_changed()
    _choose(prj, boreholes=[p.id])
    ground = sync(st, provider, prj, create=True)["ground"]
    assert [f["profile_id"] for f in ground.getFeatures()] == [p.id]   # P2: nothing ticked
    _choose(prj, ["e"], [p.id])
    sync(st, provider, prj)
    assert sorted(f["profile"] for f in ground.getFeatures()) == ["P1", "P2"]


def test_the_ground_line_is_a_simple_3d_line_in_the_sections_ground_colour(setup):
    from qgis._3d import QgsLine3DSymbol, QgsSimpleLineMaterialSettings
    from qgis.core import Qgis
    from qgis.PyQt import sip

    from groundwork_geophysics.section.profile_source import GROUND_COLOUR
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    ground = sync(st, provider, prj, create=True)["ground"]
    assert ground.renderer().symbol().color() == GROUND_COLOUR
    symbol = sip.cast(ground.renderer3D().symbol(), QgsLine3DSymbol)
    assert symbol.renderAsSimpleLines()
    assert symbol.altitudeClamping() == Qgis.AltitudeClamping.Absolute
    material = sip.cast(symbol.materialSettings(), QgsSimpleLineMaterialSettings)
    assert material.ambient() == GROUND_COLOUR


def test_the_ground_line_follows_the_rules_of_the_other_layers(setup):
    from groundwork_geophysics.section.crossing_lines import own_layer_ids
    from groundwork_geophysics.ui.view3d_layers import layers_3d, sync
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    assert "ground" not in sync(st, provider, prj)              # never without being asked
    ground = sync(st, provider, prj, create=True)["ground"]
    assert ground.id() in own_layer_ids(st, prj)
    prj.removeMapLayer(ground.id())                             # removed by hand
    assert "ground" not in sync(st, provider, prj)              # a redraw keeps it removed
    ground = sync(st, provider, prj, create=True)["ground"]     # OK in Show in 3D brings it
    _choose(prj, [])
    sync(st, provider, prj)
    assert "ground" not in layers_3d(prj)


def test_the_ground_line_follows_the_profile_and_comes_back_with_the_project(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    ground = sync(st, provider, prj, create=True)["ground"]
    assert _ground_points(ground, p.id)[:, 1] == pytest.approx(0.0)
    moved = replace(p, xy=p.xy + np.array([0.0, 5.0]))
    st.save_profile(moved)
    provider.notify_changed()
    assert sync(st, provider, prj)["ground"] is ground
    assert _ground_points(ground, p.id)[:, 1] == pytest.approx(5.0)
    # as a memory layer read back from a project file: empty, without the mark
    ground.dataProvider().truncate()
    ground.setProperty("groundworkFilled", None)
    sync(st, provider, prj)
    assert ground.featureCount() == 1


def test_a_profile_without_real_heights_has_no_ground_line(qgis_app, tmp_path):
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
    _choose(prj, ["m"], [p.id])
    assert "ground" not in sync(st, provider, prj, create=True)


def test_the_message_counts_the_ground_lines(setup):
    from groundwork_geophysics.ui.view3d_layers import shown_summary, sync
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    assert shown_summary(sync(st, provider, prj, create=True)).endswith("and 1 ground line")


# -- section pictures stay out of the 2D map ----------------------------------------------
def test_a_section_picture_is_drawn_in_3d_only(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose_pictures(prj, ["d"])
    picture = sync(st, provider, prj, create=True)["pictures"][p.id]
    assert picture.renderer3D() is not None
    # its scale range ends at 1:1, so the 2D map never draws (or decodes) it; the 3D view
    # does not look at scale ranges
    assert picture.hasScaleBasedVisibility()
    assert not any(picture.isInScaleRange(s) for s in (10.0, 1_000.0, 1e5, 1e8))


def test_a_picture_the_user_shows_in_2d_again_stays_so(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose_pictures(prj, ["d"])
    picture = sync(st, provider, prj, create=True)["pictures"][p.id]
    picture.setScaleBasedVisibility(False)
    style = provider.style("d")
    provider.set_style("d", replace(style, scale=replace(style.scale, cmap="viridis")))
    assert sync(st, provider, prj)["pictures"][p.id] is picture     # drawn again
    assert not picture.hasScaleBasedVisibility()


# -- profile names in 3D: a text annotation per profile (QGIS's own 3D text) -----------------
def _name_item(layer):
    from qgis.core import QgsAnnotationPointTextItem
    items = list(layer.items().values())
    assert len(items) == 1 and isinstance(items[0], QgsAnnotationPointTextItem)
    return items[0]


def test_each_profile_name_is_a_text_annotation_above_its_start(setup):
    """QGIS 4 draws text annotations in 3D (QgsAnnotationLayer3DRenderer), but all items of a
    layer at one height: one annotation layer per profile, at its start's height."""
    from qgis.core import Qgis, QgsAnnotationLayer

    from groundwork_geophysics.ui.view3d_layers import NAMES_GROUP, NAME_LIFT_M, sync
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    name = sync(st, provider, prj, create=True)["names"][p.id]
    assert isinstance(name, QgsAnnotationLayer) and name.name() == "P1"
    item = _name_item(name)
    assert item.text() == "P1"
    x0, y0 = (float(v) for v in p.chainage.to_xy(0.0))
    assert (item.point().x(), item.point().y()) == pytest.approx((x0, y0))
    r3d = name.renderer3D()
    assert r3d.type() == "annotation" and r3d.altitudeClamping() == Qgis.AltitudeClamping.Absolute
    s, z = provider.surface(p.id).line
    lift = max(NAME_LIFT_M, 0.03 * p.chainage.length)
    assert r3d.zOffset() == pytest.approx(float(np.interp(0.0, s, z)) + lift)
    assert prj.layerTreeRoot().findLayer(name.id()).parent().name() == NAMES_GROUP
    assert not name.isInScaleRange(1000.0)           # the map labels the profiles already


def test_a_renamed_profile_gets_its_new_name(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    name = sync(st, provider, prj, create=True)["names"][p.id]
    p.name = "Line 77"
    st.save_profile(p)
    provider.notify_changed()
    again = sync(st, provider, prj)["names"][p.id]
    assert again is name and _name_item(name).text() == "Line 77" and name.name() == "Line 77"


def test_a_name_removed_by_hand_stays_removed_and_unticking_removes_it(setup):
    from groundwork_geophysics.ui.view3d_layers import NAMES_GROUP, names_3d, sync
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    name = sync(st, provider, prj, create=True)["names"][p.id]
    sync(st, provider, prj)
    prj.removeMapLayer(name.id())
    sync(st, provider, prj)
    assert not names_3d(prj)
    sync(st, provider, prj, create=True)                 # OK in Show in 3D brings it back
    assert p.id in names_3d(prj)
    _choose(prj, [])
    sync(st, provider, prj)
    assert not names_3d(prj) and prj.layerTreeRoot().findGroup(NAMES_GROUP) is None


def test_names_made_as_lettering_are_replaced(setup):
    from qgis.core import QgsVectorLayer

    from groundwork_geophysics.ui.view3d_layers import names_3d, sync
    st, p, provider, prj = setup
    old = QgsVectorLayer(f"MultiPolygonZ?crs={CRS}", "Profile names in 3D", "memory")
    old.setCustomProperty("geophysics_workbench/view3d", "names")
    prj.addMapLayer(old)
    old_id = old.id()
    _choose(prj, ["d"])
    sync(st, provider, prj)
    assert old_id not in prj.mapLayers() and p.id in names_3d(prj)


# -- a kind of 3D layer new in an update comes by itself; one the user removed stays away ----
def test_a_kind_of_layer_new_in_an_update_comes_when_the_project_opens(setup):
    """A project made before an update knows no "Ground in 3D": opening it adds the new
    kind (its user never removed it), while the kinds it had stay as they were."""
    import json

    from groundwork_geophysics.ui.view3d_layers import ENTRY_MADE, forget_shown, layers_3d, sync
    from groundwork_geophysics.ui.project_actions import SCOPE
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    sync(st, provider, prj, create=True)
    prj.removeMapLayer(layers_3d(prj)["ground"].id())     # as before the update ...
    made = set(json.loads(prj.readEntry(SCOPE, ENTRY_MADE, "[]")[0]))
    prj.writeEntry(SCOPE, ENTRY_MADE, json.dumps(sorted(made - {"ground"})))  # ... unknown
    forget_shown(prj)                                     # the project is opened again
    sync(st, provider, prj)
    assert "ground" in layers_3d(prj)


def test_a_kind_the_user_removed_stays_removed_when_the_project_opens(setup):
    from groundwork_geophysics.ui.view3d_layers import forget_shown, layers_3d, sync
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    sync(st, provider, prj, create=True)
    prj.removeMapLayer(layers_3d(prj)["ground"].id())     # the user's choice
    forget_shown(prj)
    sync(st, provider, prj)
    sync(st, provider, prj)
    assert "ground" not in layers_3d(prj)


def test_an_annotation_the_user_adds_to_a_name_layer_stays(setup):
    """Only the plugin's own text item is replaced when the name changes or moves."""
    from qgis.core import QgsAnnotationPointTextItem, QgsPointXY

    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose(prj, ["d"])
    name = sync(st, provider, prj, create=True)["names"][p.id]
    mine = name.addItem(QgsAnnotationPointTextItem("my note", QgsPointXY(30.0, 1.0)))
    p.name = "Line 78"
    st.save_profile(p)
    provider.notify_changed()
    sync(st, provider, prj)
    items = name.items()
    assert mine in items and items[mine].text() == "my note"
    assert sorted(item.text() for item in items.values()) == ["Line 78", "my note"]
    sync(st, provider, prj)                               # unchanged: nothing replaced
    assert sorted(item.text() for item in name.items().values()) == ["Line 78", "my note"]


def test_a_section_picture_takes_its_profiles_new_name_unless_the_user_named_it(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose_pictures(prj, ["d"])
    picture = sync(st, provider, prj, create=True)["pictures"][p.id]
    assert picture.name() == "P1"
    p.name = "Line 79"
    st.save_profile(p)
    provider.notify_changed()
    assert sync(st, provider, prj)["pictures"][p.id] is picture
    assert picture.name() == "Line 79"
    picture.setName("my picture")                         # the user's own name stays
    p.name = "Line 80"
    st.save_profile(p)
    provider.notify_changed()
    sync(st, provider, prj)
    assert picture.name() == "my picture"


def test_a_project_that_never_showed_anything_in_3d_stays_unmodified(setup):
    """A sync with a 3D view open (any style change) on a project that never used Show in
    3D writes nothing into it: QGIS would ask to save changes nobody made."""
    from groundwork_geophysics.ui.project_actions import SCOPE
    from groundwork_geophysics.ui.view3d_layers import ENTRY_MADE, sync
    st, p, provider, prj = setup
    prj.setDirty(False)
    assert sync(st, provider, prj) == {}
    sync(st, provider, prj)
    assert not prj.isDirty()
    assert not prj.readEntry(SCOPE, ENTRY_MADE, "")[1]
    _choose(prj, ["d"])
    sync(st, provider, prj, create=True)                  # OK in Show in 3D notes it
    assert prj.readEntry(SCOPE, ENTRY_MADE, "")[1]
    prj.setDirty(False)
    sync(st, provider, prj)                               # unchanged: not written again
    assert not prj.isDirty()
