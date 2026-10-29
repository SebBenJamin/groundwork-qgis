import shutil
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ert"


# -- brief tests ---------------------------------------------------------------------------
def test_new_store_adds_layers_and_property(qgis_app, tmp_path):
    from qgis.core import QgsProject
    from geophysics_workbench.ui.project_actions import new_store, attach_store
    prj = QgsProject()
    st = new_store(tmp_path / "w.gpkg", "EPSG:25832", prj)
    names = sorted(l.name() for l in prj.mapLayers().values())
    assert names == ["profiles", "stations"]
    assert attach_store(prj).path == st.path


def test_add_model_rejects_unreadable_file(qgis_app, tmp_path, store_with_model):
    import pytest
    from geophysics_workbench.ui.project_actions import add_model
    st, p, _ = store_with_model
    bad = tmp_path / "f002_res.dat"; bad.write_text("not numbers\n")
    with pytest.raises(ValueError):
        add_model(st, p.id, st.station_sets(p.id)[0].id, bad, "r2_res_dat", {}, "bad")
    assert len(st.datasets(p.id)) == 1


# -- store path property -------------------------------------------------------------------
def test_layers_are_grouped_and_valid(qgis_app, tmp_path):
    from qgis.core import QgsProject

    from geophysics_workbench.ui.project_actions import GROUP_NAME, new_store

    prj = QgsProject()
    new_store(tmp_path / "w.gpkg", "EPSG:25832", prj)
    group = prj.layerTreeRoot().findGroup(GROUP_NAME)
    assert group is not None
    assert sorted(l.name() for l in group.findLayers()) == ["profiles", "stations"]
    assert all(l.layer().isValid() for l in group.findLayers())
    profiles = prj.mapLayersByName("profiles")[0]
    assert profiles.labelsEnabled()
    assert not prj.mapLayersByName("stations")[0].labelsEnabled()


def test_store_path_relative_to_project_and_survives_move(qgis_app, tmp_path):
    from qgis.core import QgsProject

    from geophysics_workbench.ui.project_actions import (SCOPE, STORE_KEY, attach_store,
                                                         new_store)

    folder = tmp_path / "a"
    folder.mkdir()
    prj = QgsProject()
    prj.setFileName(str(folder / "proj.qgz"))
    new_store(folder / "w.gpkg", "EPSG:25832", prj)
    assert prj.readEntry(SCOPE, STORE_KEY, "")[0] == "w.gpkg"
    assert prj.write()

    moved = tmp_path / "b"
    shutil.copytree(folder, moved)          # original stays (QGIS holds it open on Windows)
    prj.clear()
    prj2 = QgsProject()
    assert prj2.read(str(moved / "proj.qgz"))
    st = attach_store(prj2)
    assert st.path.resolve() == (moved / "w.gpkg").resolve()


def test_store_path_absolute_without_project_file(qgis_app, tmp_path):
    from qgis.core import QgsProject

    from geophysics_workbench.ui.project_actions import SCOPE, STORE_KEY, new_store

    prj = QgsProject()
    st = new_store(tmp_path / "w.gpkg", "EPSG:25832", prj)
    entry = prj.readEntry(SCOPE, STORE_KEY, "")[0]
    assert Path(entry).is_absolute() and Path(entry) == st.path


def test_attach_store_none_without_entry_and_error_for_missing_file(qgis_app, tmp_path):
    from qgis.core import QgsProject

    from geophysics_workbench.ui.project_actions import (SCOPE, STORE_KEY, attach_store)

    prj = QgsProject()
    assert attach_store(prj) is None
    prj.writeEntry(SCOPE, STORE_KEY, str(tmp_path / "gone.gpkg"))
    with pytest.raises(ValueError, match="not found"):
        attach_store(prj)


def test_open_store_reuses_existing_layers(qgis_app, tmp_path):
    from qgis.core import QgsProject

    from geophysics_workbench.ui.project_actions import new_store, open_store

    prj = QgsProject()
    st = new_store(tmp_path / "w.gpkg", "EPSG:25832", prj)
    st2 = open_store(st.path, prj)
    assert st2.crs_authid == "EPSG:25832"
    assert len(prj.mapLayers()) == 2


# -- profiles and models -------------------------------------------------------------------
def test_add_profile_saves_and_refreshes_layers(qgis_app, tmp_path):
    from qgis.core import QgsProject

    from geophysics_workbench.core.model import profile_from_line
    from geophysics_workbench.ui.project_actions import add_profile, new_store

    prj = QgsProject()
    st = new_store(tmp_path / "w.gpkg", "EPSG:25832", prj)
    profiles = prj.mapLayersByName("profiles")[0]
    stations = prj.mapLayersByName("stations")[0]
    assert profiles.featureCount() == 0
    p, s = profile_from_line("L1", "EPSG:25832", np.array([[0.0, 0.0], [100.0, 0.0]]), 10.0)
    add_profile(st, p, s, prj)
    assert [pp.name for pp in st.profiles()] == ["L1"]
    assert profiles.featureCount() == 1
    assert stations.featureCount() == 11
    assert profiles.extent().xMaximum() == pytest.approx(100.0)


def test_add_model_fills_defaults_and_notifies(qgis_app, tmp_path, store_with_model):
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.ui.project_actions import add_model

    st, p, _ = store_with_model
    src = tmp_path / "models" / "f002_res.dat"
    src.parent.mkdir()
    shutil.copy(FIXTURES / "f001_res.dat", src)
    prov = SectionDataProvider(st)
    calls = []
    prov.on_change.append(lambda: calls.append(1))
    sid = st.station_sets(p.id)[0].id
    d = add_model(st, p.id, sid, src, "r2_res_dat", {}, "", provider=prov)
    assert d.reader_options == {"z_kind": "elevation", "chainage_offset": 0.0}
    assert d.name == "f002_res" and d.source_path == str(src)
    assert d.source_sha1 and d.provenance["n_points"] > 0
    assert [x.id for x in st.datasets(p.id)][-1] == d.id
    assert calls == [1]
    assert all(layer.error is None for layer in prov.layers(p.id))


def test_add_model_requires_z_kind_when_unknown(qgis_app, tmp_path, store_with_model):
    from geophysics_workbench.ui.project_actions import add_model

    st, p, _ = store_with_model
    sid = st.station_sets(p.id)[0].id
    src = FIXTURES / "zond_model.dat"
    with pytest.raises(ValueError, match="Choose whether Z is elevation or depth"):
        add_model(st, p.id, sid, src, "zondres_xyz", {"chainage_offset": 2.0}, "z")
    d = add_model(st, p.id, sid, src, "zondres_xyz",
                  {"chainage_offset": 2.0, "z_kind": "elevation"}, "z")
    assert d.reader_options == {"z_kind": "elevation", "chainage_offset": 2.0}
    assert len(st.datasets(p.id)) == 2
