"""Derived electrodes as one temporary map layer: never stored, own to the workbench, its
style the user's."""
import hashlib
import shutil
from pathlib import Path

import numpy as np
import pytest

from geophysics_workbench.core.model import (Dataset, attach_station_set, file_fingerprint,
                                             profile_from_polyline)
from geophysics_workbench.section.data import SectionDataProvider
from geophysics_workbench.store.gpkg_store import ProjectStore

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
    from geophysics_workbench.ui.derived_layers import sync
    st, p, provider, prj = drawn
    lyr = sync(st, provider, prj)
    assert lyr.name() == "electrodes (derived)" and lyr.featureCount() == 6
    assert {f["kind"] for f in lyr.getFeatures()} == {"guessed"}
    assert {f["profile_id"] for f in lyr.getFeatures()} == {p.id}
    assert lyr.readOnly()


def test_layer_is_not_in_the_geopackage(drawn):
    from geophysics_workbench.ui.derived_layers import sync
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
    from geophysics_workbench.ui.derived_layers import derived_layer, sync
    st, p, provider, prj = drawn
    sync(st, provider, prj)
    st.save_station_set(attach_station_set(p, "S", "ert", np.column_stack(
        [np.arange(6) * 2.0, np.zeros(6), np.full(6, 100.0)])))
    provider.notify_changed()
    assert sync(st, provider, prj) is None and derived_layer(prj) is None


def test_layer_sits_below_the_stations_and_a_second_sync_keeps_it(drawn):
    from geophysics_workbench.ui import project_actions
    from geophysics_workbench.ui.derived_layers import sync
    st, p, provider, prj = drawn
    project_actions.add_store_layers(st, prj)
    lyr = sync(st, provider, prj)
    group = prj.layerTreeRoot().findGroup(project_actions.GROUP_NAME)
    names = [n.name() for n in group.children()]
    assert names.index("electrodes (derived)") == names.index("stations") + 1
    assert sync(st, provider, prj) is lyr


def test_default_style_clones_the_stations_symbol_with_less_opacity(drawn):
    from geophysics_workbench.ui import project_actions
    from geophysics_workbench.ui.derived_layers import sync
    st, p, provider, prj = drawn
    stations = project_actions.add_store_layers(st, prj)["stations"]
    renderer = sync(st, provider, prj).renderer()
    assert renderer.type() == "categorizedSymbol" and renderer.classAttribute() == "kind"
    base = stations.renderer().symbol()
    guessed = next(c for c in renderer.categories() if c.value() == "guessed").symbol()
    assert guessed.color().name() == base.color().name() and guessed.opacity() == 0.5


def test_user_style_survives_a_reopen(drawn):
    from qgis.core import QgsProject, QgsSingleSymbolRenderer, QgsMarkerSymbol
    from geophysics_workbench.ui.derived_layers import save_style, sync
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
    from geophysics_workbench.section.crossing_lines import own_layer_ids
    from geophysics_workbench.ui.derived_layers import sync
    st, p, provider, prj = drawn
    lyr = sync(st, provider, prj)
    assert lyr.id() in own_layer_ids(st, prj)
