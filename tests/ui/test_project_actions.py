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


class _Provider:
    def __init__(self):
        self.calls = 0

    def notify_changed(self):
        self.calls += 1


def test_create_profile_from_a_line_has_no_stations(qgis_app, project_store):
    from geophysics_workbench.core.placement import Placement
    from geophysics_workbench.ui.project_actions import create_profile

    st, prj = project_store
    prov = _Provider()
    p = create_profile(st, Placement(line_xy=np.array([[0.0, 0.0], [30.0, 40.0]])), "L1",
                       "ert", prj, prov)
    assert [q.id for q in st.profiles()] == [p.id] and st.profile(p.id).name == "L1"
    assert st.station_sets(p.id) == [] and st.datasets(p.id) == []
    assert "electrode_spacing" not in st.profile(p.id).metadata
    assert prj.mapLayersByName("profiles")[0].featureCount() == 1
    assert prov.calls == 1


def test_create_profile_from_positions_keeps_them_and_the_spacing(qgis_app, project_store):
    from geophysics_workbench.core.placement import Placement, Positions
    from geophysics_workbench.ui.project_actions import create_profile

    st, prj = project_store
    xyz = np.array([[0.0, 0.0, 50.0], [50.0, 0.0, 51.0], [100.0, 0.0, 52.0]])
    placement = Placement(positions=Positions(xyz, np.array([1, 11, 21])), spacing=5.0)
    p = create_profile(st, placement, "P", "ert", prj)
    [s] = st.station_sets(p.id)
    assert s.numbers.tolist() == [1, 11, 21] and s.method == "ert"
    assert st.profile(p.id).metadata["electrode_spacing"] == 5.0
    assert prj.mapLayersByName("stations")[0].featureCount() == 3


def test_create_profile_failure_saves_nothing_and_does_not_notify(qgis_app, project_store,
                                                                  monkeypatch):
    from geophysics_workbench.core.placement import Placement, Positions
    from geophysics_workbench.ui.project_actions import create_profile

    st, prj = project_store

    def broken(*_a, **_k):
        raise RuntimeError("attempt to write a readonly database")

    monkeypatch.setattr(st, "_write_station_set", broken)
    prov = _Provider()
    xyz = np.array([[0.0, 0.0, 50.0], [10.0, 0.0, 51.0]])
    with pytest.raises(RuntimeError):
        create_profile(st, Placement(positions=Positions(xyz, np.array([1, 2]))), "P", "ert",
                       prj, prov)
    assert st.profiles() == [] and prov.calls == 0


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
    assert d.name == "f002_res" and d.source_path == "models/f002_res.dat"   # under store dir
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


def test_add_model_outside_store_folder_saves_absolute_path(qgis_app, tmp_path_factory,
                                                           store_with_model):
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.ui.project_actions import add_model

    st, p, _ = store_with_model
    src = tmp_path_factory.mktemp("elsewhere") / "f003_res.dat"
    shutil.copy(FIXTURES / "f001_res.dat", src)
    d = add_model(st, p.id, st.station_sets(p.id)[0].id, src, "r2_res_dat", {}, "far")
    assert Path(d.source_path).is_absolute()
    assert Path(d.source_path) == src.resolve()
    assert all(layer.error is None for layer in SectionDataProvider(st).layers(p.id))


# -- store layers are read-only ------------------------------------------------------------
def test_store_layers_are_read_only(qgis_app, tmp_path):
    """Profiles and stations are written by the workbench only (its rules: ids, station
    sets, chainage), also after the QGIS project is saved and read again."""
    from qgis.core import QgsProject

    from geophysics_workbench.ui.project_actions import attach_store, new_store, store_layers

    prj = QgsProject()
    st = new_store(tmp_path / "w.gpkg", "EPSG:25832", prj)
    layers = store_layers(st, prj)
    assert sorted(layers) == ["profiles", "stations"]
    for layer in layers.values():
        assert layer.readOnly() and not layer.startEditing()
    assert prj.write(str(tmp_path / "w.qgz"))
    again = QgsProject()
    assert again.read(str(tmp_path / "w.qgz"))
    for layer in again.mapLayers().values():          # whatever the project file says ...
        layer.setReadOnly(False)
    attached = attach_store(again)                      # ... attaching protects them again
    for layer in store_layers(attached, again).values():
        assert layer.readOnly() and not layer.startEditing()


# -- add_model checks ----------------------------------------------------------------------
def test_add_model_accepts_depth_model_without_station_elevations(qgis_app, tmp_path):
    from geophysics_workbench.core.model import profile_from_stations
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.store.gpkg_store import ProjectStore
    from geophysics_workbench.ui.project_actions import add_model

    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p, s = profile_from_stations("Flat", "EPSG:25832", np.array([[0, 0], [50, 0.0]]))  # no z
    st.save_profile(p); st.save_station_set(s)
    src = tmp_path / "zond_model_depth.dat"
    shutil.copy(FIXTURES / "zond_model_depth.dat", src)
    d = add_model(st, p.id, s.id, src, "zondres_xyz", {}, "depth model")
    assert d.reader_options["z_kind"] == "depth"
    [layer] = SectionDataProvider(st).layers(p.id)       # hung from the flat surface at 0
    assert layer.error is None and layer.mesh.bounds()[3] == 0.0
    add_model(st, p.id, s.id, src, "zondres_xyz", {"z_kind": "elevation"}, "as elevation")
    assert len(st.datasets(p.id)) == 2


def test_add_model_keeps_the_readers_quantity_and_unit(qgis_app, tmp_path, store_with_model):
    from geophysics_workbench.ui.project_actions import add_model

    st, p, _ = store_with_model
    src = tmp_path / "f001_res.vtk"
    shutil.copy(FIXTURES / "f001_res.vtk", src)
    d = add_model(st, p.id, st.station_sets(p.id)[0].id, src, "vtk_legacy",
                  {"array": "Sensitivity(log10)"}, "sens")
    assert (d.quantity, d.unit) == ("Sensitivity(log10)", "")
    [back] = [x for x in st.datasets(p.id) if x.id == d.id]
    assert (back.quantity, back.unit) == ("Sensitivity(log10)", "")


def test_build_profile_refuses_a_placement_on_an_existing_profile(store_with_model):
    from geophysics_workbench.core.placement import Placement
    from geophysics_workbench.ui.project_actions import build_profile
    st, p, _ = store_with_model
    with pytest.raises(ValueError, match="existing profile"):
        build_profile(st, Placement(profile_id=p.id), "X", "ert")
