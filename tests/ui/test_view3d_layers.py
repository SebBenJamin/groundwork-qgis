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
    first["models"].dataProvider().truncate()      # as a memory layer read from a project
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
