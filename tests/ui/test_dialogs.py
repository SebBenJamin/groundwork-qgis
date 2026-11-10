"""Dialogs driven programmatically (offscreen): set the widgets, call accept()."""
import shutil
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ert"


def _close(dialog, qgis_app):
    dialog.close()
    dialog.deleteLater()
    qgis_app.processEvents()


# -- NewProfileDialog ----------------------------------------------------------------------
def test_new_profile_from_station_file(qgis_app, fake_iface, project_store, tmp_path,
                                       warnings_shown):
    from geophysics_workbench.ui.new_profile_dialog import TAB_FILE, NewProfileDialog

    st, prj = project_store
    csv = tmp_path / "el.txt"
    csv.write_text("Nr;Rechts;Hoch;Höhe\n1;100,0;0,0;50,0\n2;105,0;0,0;50,5\n3;110,0;0,0;51,0\n",
                   encoding="utf-8")
    dlg = NewProfileDialog(fake_iface, st, project=prj)
    try:
        dlg.tabs.setCurrentIndex(TAB_FILE)
        dlg.set_station_file(csv)
        assert dlg.col_number.currentData() == 0 and dlg.col_x.currentData() == 1
        assert dlg.col_y.currentData() == 2 and dlg.col_z.currentData() == 3
        dlg.name_edit.setText("")
        dlg.accept()                                     # validation: name missing
        assert warnings_shown and "name" in warnings_shown[-1].lower()
        assert st.profiles() == [] and dlg.result() == 0
        dlg.name_edit.setText("A1")
        dlg.accept()
        assert dlg.result() == 1
        [p] = st.profiles()
        assert p.name == "A1" and dlg.profile.id == p.id
        [s] = st.station_sets(p.id)
        assert s.numbers.tolist() == [1, 2, 3]
        assert s.xyz[:, 2].tolist() == [50.0, 50.5, 51.0]
        assert prj.mapLayersByName("profiles")[0].featureCount() == 1
    finally:
        _close(dlg, qgis_app)


def test_new_profile_from_points_validates_spacing(qgis_app, fake_iface, project_store,
                                                   warnings_shown):
    from geophysics_workbench.ui.new_profile_dialog import TAB_POINTS, NewProfileDialog

    st, prj = project_store
    dlg = NewProfileDialog(fake_iface, st, project=prj)
    try:
        dlg.tabs.setCurrentIndex(TAB_POINTS)
        dlg.name_edit.setText("L2")
        for w, v in ((dlg.x1, 1000.0), (dlg.y1, 2000.0), (dlg.x2, 1000.0), (dlg.y2, 2100.0)):
            w.setValue(v)
        dlg.points_spacing.setValue(0.0)
        dlg.accept()
        assert "spacing" in warnings_shown[-1].lower() and st.profiles() == []
        dlg.points_spacing.setValue(5.0)
        dlg.accept()
        [p] = st.profiles()
        assert np.allclose(p.xy, [[1000, 2000], [1000, 2100]])
        assert len(st.station_sets(p.id)[0].numbers) == 21
    finally:
        _close(dlg, qgis_app)


def test_new_profile_from_points_rejects_identical_points(qgis_app, fake_iface, project_store,
                                                          warnings_shown):
    from geophysics_workbench.ui.new_profile_dialog import TAB_POINTS, NewProfileDialog

    st, prj = project_store
    dlg = NewProfileDialog(fake_iface, st, project=prj)
    try:
        dlg.tabs.setCurrentIndex(TAB_POINTS)
        dlg.name_edit.setText("L3")
        dlg.accept()                                    # all coordinates 0: same point
        assert "different" in warnings_shown[-1].lower() and st.profiles() == []
    finally:
        _close(dlg, qgis_app)


def test_new_profile_from_points_pick_on_map(qgis_app, fake_iface, project_store):
    from qgis.core import QgsCoordinateReferenceSystem, QgsPointXY
    from qgis.PyQt.QtCore import Qt

    from geophysics_workbench.ui.new_profile_dialog import NewProfileDialog

    st, prj = project_store
    fake_iface.mapCanvas().setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:25832"))
    dlg = NewProfileDialog(fake_iface, st, project=prj)
    try:
        dlg.start_pick()
        tool = dlg.pick_tool
        assert fake_iface.mapCanvas().mapTool() is tool and not dlg.isVisible()
        dlg.pick_tool.canvasClicked.emit(QgsPointXY(10.0, 20.0), Qt.MouseButton.LeftButton)
        dlg.pick_tool.canvasClicked.emit(QgsPointXY(30.0, 40.0), Qt.MouseButton.LeftButton)
        assert (dlg.x1.value(), dlg.y1.value(), dlg.x2.value(), dlg.y2.value()) == (10, 20, 30, 40)
        assert fake_iface.mapCanvas().mapTool() is not tool and dlg.pick_tool is None
        assert dlg.isVisible()                          # back after the second click
    finally:
        _close(dlg, qgis_app)


def test_new_profile_from_selected_line(qgis_app, fake_iface, project_store, warnings_shown):
    from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

    from geophysics_workbench.ui.new_profile_dialog import TAB_LINE, NewProfileDialog

    st, prj = project_store
    layer = QgsVectorLayer("LineString?crs=EPSG:25832", "lines", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromWkt("LineString (0 0, 30 40, 60 40)"))
    layer.dataProvider().addFeatures([f])
    fake_iface.setActiveLayer(layer)
    dlg = NewProfileDialog(fake_iface, st, project=prj)
    try:
        dlg.tabs.setCurrentIndex(TAB_LINE)
        dlg.name_edit.setText("Crooked")
        dlg.accept()                                    # nothing selected yet
        assert "select" in warnings_shown[-1].lower() and st.profiles() == []
        layer.selectAll()
        dlg.line_spacing.setValue(10.0)
        dlg.accept()
        [p] = st.profiles()
        assert np.allclose(p.xy, [[0, 0], [30, 40], [60, 40]])
        assert len(st.station_sets(p.id)[0].numbers) == 9            # 0..80 m every 10 m
    finally:
        fake_iface.setActiveLayer(None)
        _close(dlg, qgis_app)


# -- AddModelDialog ------------------------------------------------------------------------
def test_add_model_dialog_preview_and_save(qgis_app, fake_iface, store_with_model, tmp_path,
                                           warnings_shown):
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.ui.add_model_dialog import AddModelDialog

    st, p, _ = store_with_model
    src = tmp_path / "zz" / "zond_model.dat"
    src.parent.mkdir()
    shutil.copy(FIXTURES / "zond_model.dat", src)
    prov = SectionDataProvider(st)
    calls = []
    prov.on_change.append(lambda: calls.append(1))
    dlg = AddModelDialog(fake_iface, st, p.id, provider=prov)
    try:
        dlg.set_file(src)
        assert dlg.reader_combo.currentData() == "zondres_xyz"
        assert dlg.name_edit.text() == "zond_model"
        assert "ohm" in dlg.preview.text() and "x " in dlg.preview.text()
        assert dlg.z_combo.currentData() is None              # zond 'Z' header: unknown
        dlg.accept()
        assert "elevation or depth" in warnings_shown[-1] and len(st.datasets(p.id)) == 1
        dlg.z_combo.setCurrentIndex(dlg.z_combo.findData("elevation"))
        dlg.offset_spin.setValue(3.5)
        dlg.accept()
        assert dlg.result() == 1 and calls == [1]
        d = st.datasets(p.id)[-1]
        assert d.reader == "zondres_xyz" and d.name == "zond_model"
        assert d.reader_options == {"z_kind": "elevation", "chainage_offset": 3.5}
        assert d.station_set_id == st.station_sets(p.id)[0].id
    finally:
        _close(dlg, qgis_app)


def test_add_model_dialog_reports_unreadable_file(qgis_app, fake_iface, store_with_model,
                                                  tmp_path, warnings_shown):
    from geophysics_workbench.ui.add_model_dialog import AddModelDialog

    st, p, _ = store_with_model
    bad = tmp_path / "f009_res.dat"
    bad.write_text("not numbers\n")
    dlg = AddModelDialog(fake_iface, st, p.id)
    try:
        dlg.set_file(bad)
        assert dlg.reader_combo.currentData() == "r2_res_dat"
        assert "f009_res.dat" in dlg.preview.text()            # preview shows the error
        dlg.accept()
        assert "f009_res.dat" in warnings_shown[-1]
        assert dlg.result() == 0 and len(st.datasets(p.id)) == 1
    finally:
        _close(dlg, qgis_app)


# -- plugin wiring -------------------------------------------------------------------------
def test_plugin_actions_follow_project_and_dock(qgis_app, fake_iface, tmp_path):
    from qgis.core import QgsProject

    from geophysics_workbench.core.model import profile_from_line
    from geophysics_workbench.plugin import WorkbenchPlugin
    from geophysics_workbench.ui.project_actions import add_profile, new_store

    prj = QgsProject.instance()
    prj.clear()
    prj.setFileName(str(tmp_path / "proj.qgz"))
    st = new_store(tmp_path / "w.gpkg", "EPSG:25832", prj)
    p, s = profile_from_line("L1", "EPSG:25832", np.array([[0.0, 0.0], [50.0, 0.0]]), 5.0)
    add_profile(st, p, s, prj)
    assert prj.write()
    prj.clear()

    signals = (prj.readProject, prj.cleared, prj.fileNameChanged)
    before = [prj.receivers(sig) for sig in signals]
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        assert [prj.receivers(sig) for sig in signals] != before
        texts = [a.text() for a in plugin.menu.actions()]
        for t in ("New Workbench Project…", "Open Workbench Project…", "New Profile…",
                  "Add ERT Model…"):
            assert t in texts
        assert plugin.provider is None
        assert not plugin.new_profile_action.isEnabled()
        assert not plugin.add_model_action.isEnabled()

        assert prj.read(str(tmp_path / "proj.qgz"))            # readProject -> attach store
        assert plugin.provider is not None
        assert plugin.provider.store.path.resolve() == (tmp_path / "w.gpkg").resolve()
        assert plugin.new_profile_action.isEnabled()
        assert not plugin.add_model_action.isEnabled()
        plugin.dock.open_profile(p.id)
        assert plugin.add_model_action.isEnabled()

        plugin.new_profile_action.trigger()                    # non-modal dialog
        dlg = plugin._profile_dialog
        dlg.tabs.setCurrentIndex(2)
        dlg.name_edit.setText("L2")
        dlg.x2.setValue(30.0)
        dlg.accept()
        new_id = dlg.profile.id
        assert plugin.dock.current_profile_id() == new_id
        assert sorted(pp.name for pp in st.profiles()) == ["L1", "L2"]

        prj.clear()                                            # cleared -> tear down
        assert plugin.provider is None and plugin.source is None
        assert not plugin.add_model_action.isEnabled()
        assert not plugin.new_profile_action.isEnabled()
    finally:
        plugin.unload()
        prj.clear()
    assert [prj.receivers(sig) for sig in signals] == before       # all disconnected
    prj.read(str(tmp_path / "proj.qgz"))                       # unloaded: nothing happens
    assert plugin.provider is None
    prj.clear()


# -- fix round 1 ---------------------------------------------------------------------------
def _gdal_write_error(*_a, **_k):
    raise RuntimeError("attempt to write a readonly database")


def test_guess_columns_never_reuses_a_header_column():
    from geophysics_workbench.ui.new_profile_dialog import NONE, guess_columns

    assert guess_columns(["station", "x", "y"], 3) == {"number": 0, "x": 1, "y": 2, "z": NONE}
    assert guess_columns(["Nr", "X", "Y"], 3) == {"number": 0, "x": 1, "y": 2, "z": NONE}
    assert guess_columns(None, 3) == {"number": NONE, "x": 0, "y": 1, "z": 2}


def test_new_profile_station_file_without_z_and_rejects_z_equal_y(
        qgis_app, fake_iface, project_store, tmp_path, warnings_shown):
    from geophysics_workbench.ui.new_profile_dialog import NONE, TAB_FILE, NewProfileDialog

    st, prj = project_store
    csv = tmp_path / "st.csv"
    csv.write_text("station,x,y\n1,100.0,5800000.0\n2,105.0,5800000.0\n", encoding="utf-8")
    dlg = NewProfileDialog(fake_iface, st, project=prj)
    try:
        dlg.tabs.setCurrentIndex(TAB_FILE)
        dlg.set_station_file(csv)
        assert dlg.col_z.currentData() == NONE
        dlg.col_z.setCurrentIndex(dlg.col_z.findData(2))          # Z = the Y column
        dlg.accept()
        assert "z column" in warnings_shown[-1].lower() and st.profiles() == []
        dlg.col_z.setCurrentIndex(dlg.col_z.findData(NONE))
        dlg.accept()
        [p] = st.profiles()
        assert np.isnan(st.station_sets(p.id)[0].xyz[:, 2]).all()
    finally:
        _close(dlg, qgis_app)


def test_new_profile_store_write_error_is_shown(qgis_app, fake_iface, project_store,
                                                warnings_shown, monkeypatch):
    from geophysics_workbench.ui.new_profile_dialog import TAB_POINTS, NewProfileDialog

    st, prj = project_store
    monkeypatch.setattr(st, "save_profile", _gdal_write_error)
    dlg = NewProfileDialog(fake_iface, st, project=prj)
    try:
        dlg.tabs.setCurrentIndex(TAB_POINTS)
        dlg.name_edit.setText("L")
        dlg.x2.setValue(20.0)
        dlg.accept()
        assert "readonly" in warnings_shown[-1] and dlg.result() == 0
    finally:
        _close(dlg, qgis_app)


def test_add_model_store_write_error_is_shown(qgis_app, fake_iface, store_with_model, tmp_path,
                                              warnings_shown, monkeypatch):
    from geophysics_workbench.ui.add_model_dialog import AddModelDialog

    st, p, src = store_with_model
    monkeypatch.setattr(st, "save_dataset", _gdal_write_error)
    dlg = AddModelDialog(fake_iface, st, p.id)
    try:
        dlg.set_file(src)
        dlg.accept()
        assert "readonly" in warnings_shown[-1] and dlg.result() == 0
    finally:
        _close(dlg, qgis_app)


def test_add_model_preview_rereads_a_fixed_file(qgis_app, fake_iface, store_with_model,
                                                tmp_path):
    from geophysics_workbench.ui.add_model_dialog import AddModelDialog

    st, p, _ = store_with_model
    f = tmp_path / "f004_res.dat"
    f.write_text("not numbers\n")
    dlg = AddModelDialog(fake_iface, st, p.id)
    try:
        dlg.set_file(f)
        assert "f004_res.dat" in dlg.preview.text()
        shutil.copy(FIXTURES / "f001_res.dat", f)                 # user fixes the file
        dlg.set_file(f)
        assert "ohm" in dlg.preview.text()
    finally:
        _close(dlg, qgis_app)


def test_new_workbench_project_errors_are_shown(qgis_app, fake_iface, tmp_path, warnings_shown,
                                                monkeypatch):
    from qgis.core import QgsCoordinateReferenceSystem
    from qgis.PyQt.QtWidgets import QDialog, QFileDialog

    import geophysics_workbench.plugin as plugin_mod
    from geophysics_workbench.plugin import WorkbenchPlugin
    from geophysics_workbench.store.gpkg_store import ProjectStore

    class FakeCrsDialog:
        def __init__(self, *_a):
            pass

        def setWindowTitle(self, _t):
            pass

        def setCrs(self, _c):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def crs(self):
            return QgsCoordinateReferenceSystem("EPSG:25832")

    seen = {}

    def fake_save(*args, **kwargs):
        seen["options"] = kwargs.get("options")
        return str(target), ""

    target = tmp_path / "w.gpkg"
    monkeypatch.setattr(plugin_mod, "QgsProjectionSelectionDialog", FakeCrsDialog)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(fake_save))
    real_create = ProjectStore.__dict__["create"]
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        monkeypatch.setattr(ProjectStore, "create", classmethod(
            lambda cls, *a: _gdal_write_error()))
        plugin.new_workbench_project()                       # unwritable folder
        assert "readonly" in warnings_shown[-1] and plugin.provider is None
        assert seen["options"] == QFileDialog.Option.DontConfirmOverwrite
        monkeypatch.setattr(ProjectStore, "create", real_create)
        target.write_bytes(b"")
        plugin.new_workbench_project()                       # existing file is never replaced
        assert "will not overwrite" in warnings_shown[-1] and "w.gpkg" in warnings_shown[-1]
        assert plugin.provider is None and target.read_bytes() == b""
    finally:
        plugin.unload()
