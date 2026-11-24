"""The Add Data dialog: fixed formats as before, any other text table by assigning its
columns, and the profile chosen or created on the spot. Driven programmatically (offscreen)."""
import shutil
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
WILD = FIXTURES / "wild"


@pytest.fixture(autouse=True)
def no_remembered_import(qgis_app):
    """Each test starts and ends without a remembered table assignment."""
    from qgis.core import QgsSettings

    from groundwork_geophysics.ui.add_data_dialog import SETTINGS_KEY
    QgsSettings().remove(SETTINGS_KEY)
    yield
    QgsSettings().remove(SETTINGS_KEY)


@pytest.fixture
def make_dialog(qgis_app, fake_iface):
    from groundwork_geophysics.ui.add_data_dialog import AddDataDialog

    made = []

    def make(store, profile_id=None, project=None, provider=None):
        dlg = AddDataDialog(fake_iface, store, profile_id, provider=provider, project=project)
        dlg.show()
        qgis_app.processEvents()
        made.append(dlg)
        return dlg

    yield make
    for dlg in made:
        dlg.close()
        dlg.deleteLater()
    qgis_app.processEvents()


@pytest.fixture
def selected_line(qgis_app, fake_iface):
    """A memory line layer (EPSG:25832) from (1000, 2000) to (1100, 2000), selected and
    active."""
    from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

    layer = QgsVectorLayer("LineString?crs=EPSG:25832", "survey_lines", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromWkt("LineString (1000 2000, 1100 2000)"))
    layer.dataProvider().addFeatures([f])
    layer.selectAll()
    fake_iface.setActiveLayer(layer)
    yield layer
    fake_iface.setActiveLayer(None)


def _index(combo, value):
    combo.setCurrentIndex(combo.findData(value))


def test_recognised_file_hides_the_columns_group(qgis_app, make_dialog, store_with_model):
    st, p, _ = store_with_model
    dlg = make_dialog(st, p.id)
    dlg.set_file(FIXTURES / "ert" / "f001_res.dat")
    assert dlg.format_combo.currentData() == "r2_res_dat" and not dlg.columns_group.isVisible()
    assert not dlg.table_options.isVisible() and dlg.z_combo.isVisible()


def test_unknown_text_file_falls_back_to_assignment(qgis_app, make_dialog, project_store):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    assert dlg.format_combo.currentData() == "text_columns" and dlg.columns_group.isVisible()
    assert "1 row skipped (line 9)" in dlg.summary_label.text()
    assert dlg.table_options.isVisible() and not dlg.z_combo.isVisible()
    header = dlg.preview_table.horizontalHeaderItem(0).text()
    assert header == "X\ndistance"
    assert dlg.preview_table.horizontalHeaderItem(3).text() == "Comment\nnot used"


def test_distance_file_on_a_selected_line_creates_profile_and_dataset(
        qgis_app, make_dialog, project_store, selected_line, warnings_shown):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    assert dlg.placement.source() == "line"
    assert "guessed" in dlg.electrode_label.text()
    assert dlg.method_combo.isVisible()              # the data's method, line or not
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    assert st.station_sets(p.id) == [] and p.name == "dist_y_rho_junk"
    [d] = st.datasets(p.id)
    assert d.station_set_id == "" and d.reader == "text_columns"
    assert d.reader_options["placement"] == {"zero": 0.0, "direction": 1}
    assert d.reader_options["columns"]["value"] == 2 and d.reader_options["table"]["skip"] == 2
    assert dlg.profile.id == p.id and dlg.created and dlg.dataset.id == d.id
    assert "electrode_spacing" not in p.metadata


def test_end_of_the_line_is_stored_with_the_length(qgis_app, make_dialog, project_store,
                                                   selected_line, warnings_shown):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    _index(dlg.placement.zero_combo, "end")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    [d] = st.datasets(p.id)
    assert d.reader_options["placement"] == {"zero": pytest.approx(100.0), "direction": -1}


def test_map_file_creates_its_own_profile(qgis_app, make_dialog, project_store,
                                          warnings_shown):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "east_north_depth_rho.csv")
    from groundwork_geophysics.core.numbers import fmt

    cols = dlg.columns_group.columns()
    assert cols.position == "map"
    assert dlg.placement.source() == "file"
    rows = np.loadtxt(WILD / "east_north_depth_rho.csv", delimiter=",", skiprows=1)
    file_length = float(np.hypot(*(rows[-1, :2] - rows[0, :2])))          # 95.0 m
    assert dlg.placement.file_info.text() == (
        f"Line through the file's coordinates, {fmt(file_length, 1)} m")
    assert "No electrode positions" in dlg.electrode_label.text()
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    assert abs(p.chainage.length - file_length) < 2.0
    [d] = st.datasets(p.id)
    assert "placement" not in d.reader_options and d.station_set_id == ""
    assert d.reader_options["columns"]["position"] == "map"


def test_map_file_rows_without_a_position_are_left_out_and_reported(
        qgis_app, make_dialog, project_store, tmp_path, warnings_shown):
    # exports write -9999 as easting/northing for cells past the surveyed line; a real
    # 642 m line once became 3480 km long, running to (-9999, -9999)
    path = tmp_path / "fill_coords.csv"
    path.write_text((WILD / "east_north_depth_rho.csv").read_text()
                    + "-9999,-9999,0.5,-9999\n-9999,-9999,1.5,120.0\n")
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    assert "2 rows have no map position (-9999)" in dlg.warning_label.text()
    assert "without a value" not in dlg.summary_label.text()   # not counted as blank cells
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    assert p.chainage.length < 100.0                            # the 95 m line, not 3480 km
    assert dlg.last_warning == ("2 rows of fill_coords.csv have no map position (-9999) "
                                "and were left out.")


def test_map_file_waits_for_the_line(qgis_app, make_dialog, project_store):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "east_north_depth_rho.csv")
    dlg.placement.select_source("line")                     # no line layer is active
    text = dlg.summary_label.text()
    assert "once the line is chosen" in text and "Select exactly one line" in text
    assert dlg.summary_label.styleSheet() == ""             # not an error of the file


def test_map_file_on_an_existing_profile_reports_the_distance_from_the_line(
        qgis_app, make_dialog, project_store):
    from groundwork_geophysics.core.model import profile_from_polyline

    st, prj = project_store
    # 20 m north of the file's own line, parallel to it
    rows = np.loadtxt(WILD / "east_north_depth_rho.csv", delimiter=",", skiprows=1)
    a, b = rows[0, :2], rows[-1, :2]
    u = (b - a) / np.hypot(*(b - a))
    n = np.array([-u[1], u[0]])
    p = profile_from_polyline("Beside", st.crs_authid, np.array([a + 20 * n, b + 20 * n]))
    st.save_profile(p)
    dlg = make_dialog(st, p.id, project=prj)
    dlg.set_file(WILD / "east_north_depth_rho.csv")
    assert dlg.placement.source() == "existing"
    assert "20" in dlg.fit_label.text() and "from the line" in dlg.fit_label.text()
    assert "from the profile line" in dlg.warning_label.text()


def test_sparse_positions_pin_and_report_the_fit(qgis_app, make_dialog, project_store,
                                                 warnings_shown):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    dlg.placement.set_positions_file(WILD / "positions_sparse.csv")
    dlg.placement.spacing_edit.setText("5")
    qgis_app.processEvents()
    assert dlg.method_combo.isVisible()              # the positions become a station set
    assert dlg.fit_label.text().startswith("5 known points, largest shift")
    assert not dlg.fit_label.text().endswith("(pinned with a guessed spacing)")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    [s] = st.station_sets(p.id)
    assert s.numbers.tolist() == [1, 5, 10, 16, 20]
    assert p.metadata["electrode_spacing"] == 5.0
    [d] = st.datasets(p.id)
    assert d.station_set_id == s.id


def test_untyped_guess_is_not_stored(qgis_app, make_dialog, project_store, warnings_shown):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    dlg.placement.set_positions_file(WILD / "positions_sparse.csv")
    qgis_app.processEvents()
    assert dlg.fit_label.text().endswith("(pinned with a guessed spacing)")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    assert "electrode_spacing" not in p.metadata


def test_incomplete_assignment_blocks_add_with_a_message(qgis_app, make_dialog, project_store,
                                                         selected_line, warnings_shown):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    _index(dlg.columns_group.value_combo, None)
    assert "Choose the value column" in dlg.summary_label.text()
    dlg.accept()
    assert dlg.result() == 0 and "Choose the value column" in warnings_shown[-1]
    assert st.profiles() == []


def test_other_quantity_needs_a_name(qgis_app, make_dialog, project_store, selected_line,
                                     warnings_shown):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    box = dlg.columns_group
    _index(box.quantity_combo, "")
    assert box.quantity_name.isVisible() and box.unit_edit.isVisible()
    dlg.accept()
    assert "Type the name of the quantity" in warnings_shown[-1] and st.profiles() == []
    box.quantity_name.setText("Chargeability")
    box.unit_edit.setText("mV/V")
    box.quantity_name.editingFinished.emit()
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    [d] = st.datasets(p.id)
    assert (d.quantity, d.unit) == ("Chargeability", "mV/V")


def test_preview_reads_only_the_first_rows(qgis_app, make_dialog, project_store, monkeypatch,
                                           tmp_path, selected_line, warnings_shown):
    # a 200 000-row file: until Add, every read (the preview's, the reader's and its own
    # table read) stops after the sample; Add reads the whole file. (Only the check for an
    # over-fine grid reads the whole file's numbers once, without text: grid_of_file.)
    from groundwork_geophysics import readers
    from groundwork_geophysics.readers import text_columns
    from groundwork_geophysics.ui import add_data_dialog

    st, prj = project_store
    big = tmp_path / "big.txt"
    x = np.repeat(np.arange(2000) * 0.5, 100)
    z = np.tile(np.arange(100) * 0.25 + 0.125, 2000)
    lines = [f"{a:.2f} {b:.3f} {100 + (i % 37)}" for i, (a, b) in enumerate(zip(x, z))]
    big.write_text("distance depth rho\n" + "\n".join(lines) + "\n")
    calls = []

    def spy(module, name):
        real = getattr(module, name)

        def wrapped(*args, **kwargs):
            calls.append((name, kwargs.get("max_rows")))
            return real(*args, **kwargs)
        monkeypatch.setattr(module, name, wrapped)

    spy(add_data_dialog, "read_table")
    spy(text_columns, "read_table")
    spy(readers, "read")
    dlg = make_dialog(st, project=prj)
    dlg.set_file(big)
    assert ("read", 1000) in calls and ("read_table", 1000) in calls
    assert all(m is not None and m <= 1001 for _n, m in calls), calls
    assert dlg.preview_table.rowCount() == 20
    assert "(first 1000 rows)" in dlg.summary_label.text()
    calls.clear()
    dlg.name_edit.setText("typed name")                 # typing reads nothing
    assert calls == []
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    assert ("read", None) in calls                       # Add reads the whole file
    [p] = st.profiles()
    [d] = st.datasets(p.id)
    assert d.provenance["n_rows"] == 200_000


def test_last_assignment_is_offered_again(qgis_app, make_dialog, project_store, selected_line,
                                          tmp_path, warnings_shown):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    _index(dlg.columns_group.vertical_kind_combo, "local")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown

    again = tmp_path / "second_line.txt"
    shutil.copy(WILD / "dist_y_rho_junk.txt", again)
    second = make_dialog(st, project=prj)
    second.set_file(again)
    assert second.columns_group.columns().vertical_kind == "local"
    assert "last file" in second.columns_group.hint_label.text()

    other = make_dialog(st, project=prj)
    other.set_file(WILD / "x_zero_depth_rho.txt")           # other names: not offered
    assert other.columns_group.columns().vertical_kind != "local"


def test_remembered_settings_that_no_longer_load_are_ignored(qgis_app, make_dialog,
                                                             project_store):
    import json

    from qgis.core import QgsSettings

    from groundwork_geophysics.ui.add_data_dialog import SETTINGS_KEY
    st, prj = project_store
    QgsSettings().setValue(SETTINGS_KEY, json.dumps(
        {"names": ["X", "Y", "Rho", "Comment"], "table": {"delimiter": "pipe"},
         "columns": {"position": "polar"}}))
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    assert dlg.columns_group.columns().value == 2            # the guess
    assert "Guessed" in dlg.columns_group.hint_label.text()


def test_opened_with_a_profile_it_is_preselected(qgis_app, make_dialog, store_with_model):
    st, p, _ = store_with_model
    dlg = make_dialog(st, p.id)
    assert dlg.placement.source() == "existing"
    assert dlg.placement.placement().profile_id == p.id
    assert dlg.method_combo.isVisible()              # the data's method
    dlg.set_file(FIXTURES / "ert" / "f001_res.dat")
    assert dlg.placement.zero_combo.currentData() == "station1"   # as 0.8 placed it


def test_add_data_attaches_positions_to_an_existing_profile(qgis_app, project_store, tmp_path):
    from groundwork_geophysics.core.model import profile_from_polyline
    from groundwork_geophysics.core.placement import Placement, Positions
    from groundwork_geophysics.ui.project_actions import add_data

    st, prj = project_store
    p = profile_from_polyline("L", st.crs_authid, np.array([[0.0, 0.0], [100.0, 0.0]]))
    st.save_profile(p)
    src = tmp_path / "f001_res.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    xyz = np.array([[0.0, 1.0, 50.0], [50.0, 1.0, 51.0], [100.0, 1.0, 52.0]])
    placement = Placement(profile_id=p.id, positions=Positions(xyz, np.array([1, 11, 21])),
                          zero="station1", spacing=5.0)
    profile, d = add_data(st, placement, src, "r2_res_dat", {"z_kind": "elevation"}, "m",
                          "ert", prj)
    assert profile.id == p.id and np.allclose(st.profile(p.id).xy, p.xy)   # line kept
    [s] = st.station_sets(p.id)
    assert s.numbers.tolist() == [1, 11, 21] and d.station_set_id == s.id
    assert "placement" not in d.reader_options
    assert st.profile(p.id).metadata["electrode_spacing"] == 5.0


def test_failed_read_creates_no_profile(qgis_app, project_store, tmp_path):
    from groundwork_geophysics.core.placement import Placement
    from groundwork_geophysics.ui.project_actions import add_data

    st, prj = project_store
    bad = tmp_path / "f009_res.dat"
    bad.write_text("not numbers\n")
    placement = Placement(line_xy=np.array([[0.0, 0.0], [10.0, 0.0]]))
    with pytest.raises(ValueError):
        add_data(st, placement, bad, "r2_res_dat", {}, "bad", "ert", prj)
    assert st.profiles() == []


def test_done_releases_the_pick_and_the_overlay(qgis_app, make_dialog, project_store,
                                                selected_line, fake_iface):
    from qgis.gui import QgsRubberBand

    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    dlg.placement.start_pick()
    assert fake_iface.mapCanvas().mapTool() is not None
    dlg.reject()
    qgis_app.processEvents()
    assert fake_iface.mapCanvas().mapTool() is None
    assert not [i for i in fake_iface.mapCanvas().scene().items()
                if isinstance(i, QgsRubberBand)]


def test_hig_rules_with_a_text_table(qgis_app, make_dialog, project_store):
    from tests.ui.test_hig_strings import collect, problems

    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    _index(dlg.columns_group.quantity_combo, "")
    bad = problems(collect(dlg), "Add Data")
    assert not bad, "\n".join(bad)


def test_menu_entry_is_add_data_and_needs_only_a_project(qgis_app, fake_iface, tmp_path,
                                                         warnings_shown):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from groundwork_geophysics.plugin import WorkbenchPlugin
    from groundwork_geophysics.ui.project_actions import new_store

    prj = QgsProject.instance()
    prj.clear()
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        texts = [a.text() for a in plugin.menu.actions()]
        assert "Add Data…" in texts and "Add ERT Model…" not in texts
        assert not plugin.add_data_action.isEnabled()
        assert "Open or create a Groundwork project" in plugin.add_data_action.toolTip()
        st = new_store(tmp_path / "w.gpkg", "EPSG:25832", prj)
        plugin.set_store(st)
        assert st.profiles() == [] and plugin.add_data_action.isEnabled()

        plugin.add_data_action.trigger()                     # non-modal, one at a time
        dlg = plugin._data_dialog
        assert dlg is not None and dlg.isVisible() and not dlg.isModal()
        plugin.add_data_action.trigger()
        assert plugin._data_dialog is dlg
        dlg.set_file(WILD / "dist_y_rho_junk.txt")
        dlg.placement.set_points(0.0, 0.0, 100.0, 0.0)
        dlg.accept()
        assert dlg.result() == 1, warnings_shown
        [p] = st.profiles()
        assert plugin.dock.current_profile_id() == p.id      # the new profile is opened
    finally:
        plugin.unload()
        prj.clear()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()


def test_unexpected_errors_on_add_keep_the_dialog_open(qgis_app, make_dialog, project_store,
                                                       selected_line, warnings_shown,
                                                       monkeypatch):
    # under PyQt6 an exception leaving the Add slot aborts QGIS
    from groundwork_geophysics import readers
    from groundwork_geophysics.ui import add_data_dialog

    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")

    def broken(*_a, **_k):
        raise RuntimeError("disk on fire")

    real = add_data_dialog.read_table
    monkeypatch.setattr(add_data_dialog, "read_table", broken)
    _index(dlg.table_options.delimiter_combo, "semicolon")     # the preview reads again
    dlg.accept()
    assert "disk on fire" in warnings_shown[-1]
    assert dlg.result() == 0 and dlg.isVisible() and st.profiles() == []
    monkeypatch.setattr(add_data_dialog, "read_table", real)
    _index(dlg.table_options.delimiter_combo, "detect")
    monkeypatch.setattr(readers, "read", broken)               # the read on Add
    dlg.accept()
    assert "disk on fire" in warnings_shown[-1]
    assert dlg.result() == 0 and dlg.isVisible() and st.profiles() == []


def test_station_set_can_be_chosen(qgis_app, make_dialog, store_with_model, warnings_shown):
    from groundwork_geophysics.core.model import attach_station_set

    st, p, src = store_with_model
    second = attach_station_set(p, "Second survey", "ert",
                                np.array([[0, 0, 100], [25, 0, 101], [50, 0, 102.0]]))
    st.save_station_set(second)
    first = st.station_sets(p.id)[0]
    dlg = make_dialog(st, p.id)
    dlg.set_file(src)
    combo = dlg.station_set_combo
    assert combo.isVisible() and combo.currentData() == first.id
    assert combo.findText("Second survey") >= 0
    _index(combo, second.id)
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    assert st.datasets(p.id)[-1].station_set_id == second.id


def test_one_station_set_is_used_without_asking(qgis_app, make_dialog, store_with_model,
                                                warnings_shown):
    st, p, src = store_with_model
    before = len(st.datasets(p.id))
    dlg = make_dialog(st, p.id)
    dlg.set_file(src)
    assert not dlg.station_set_combo.isVisible()
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    assert len(st.datasets(p.id)) == before + 1
    assert st.datasets(p.id)[-1].station_set_id == st.station_sets(p.id)[0].id


def test_failed_station_set_write_saves_nothing(qgis_app, project_store, tmp_path,
                                                monkeypatch):
    from groundwork_geophysics.core.placement import Placement, Positions
    from groundwork_geophysics.ui.project_actions import add_data

    st, prj = project_store
    src = tmp_path / "f001_res.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)

    def broken(*_a, **_k):
        raise RuntimeError("attempt to write a readonly database")

    monkeypatch.setattr(st, "_write_station_set", broken)
    xyz = np.array([[0.0, 0.0, 50.0], [10.0, 0.0, 51.0]])
    placement = Placement(positions=Positions(xyz, np.array([1, 2])), spacing=10.0)
    with pytest.raises(RuntimeError):
        add_data(st, placement, src, "r2_res_dat", {"z_kind": "elevation"}, "m", "ert", prj)
    assert st.profiles() == []


def test_summary_numbers_follow_the_locale(qgis_app):
    from qgis.PyQt.QtCore import QLocale

    from groundwork_geophysics import readers
    from groundwork_geophysics.ui.add_data_dialog import describe

    result = readers.read(WILD / "dist_y_rho_junk.txt", reader="text_columns", table={},
                          columns={"distance": 0, "vertical": 1, "vertical_kind": "depth",
                                   "value": 2})
    QLocale.setDefault(QLocale(QLocale.Language.German, QLocale.Country.Germany))
    try:
        text = describe(result, "depth")
    finally:
        QLocale.setDefault(QLocale.c())
    assert "– 98,8 m, z 0,0 – 1,3 m" in text


def test_file_dialog_caption(qgis_app, make_dialog, project_store, monkeypatch):
    from qgis.PyQt.QtWidgets import QFileDialog

    st, prj = project_store
    seen = []
    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda parent, caption, *a, **k: seen.append(caption)
                                     or ("", "")))
    dlg = make_dialog(st, project=prj)
    dlg._browse()
    assert seen == ["Data File"]


def test_a_sample_without_a_section_waits_for_add(qgis_app, make_dialog, project_store,
                                                  tmp_path, selected_line, warnings_shown):
    # the first 1000 rows all lie in the first row of cells: no section from them alone
    st, prj = project_store
    f = tmp_path / "long_rows.txt"
    rows = [f"{0.5 * i:.1f} {d} {100 + i % 7}" for d in (0.5, 1.5) for i in range(1200)]
    f.write_text("distance depth rho\n" + "\n".join(rows) + "\n")
    dlg = make_dialog(st, project=prj)
    dlg.set_file(f)
    box = dlg.columns_group                      # constant in the sample: not guessed
    _index(box.vertical_combo, 1)
    _index(box.vertical_kind_combo, "depth")
    assert "the whole file is read on Add" in dlg.summary_label.text()
    assert dlg.summary_label.styleSheet() == ""
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    assert st.datasets(p.id)[0].provenance["n_rows"] == 2400


def test_preview_and_section_take_the_guess_from_the_same_model(qgis_app, make_dialog,
                                                                tmp_path, warnings_shown):
    """A triangulated model is already on the profile; the row model added now gives the
    guess, in the preview and in the section after Add."""
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.placement_resolve import resolve_map
    from tests.section.test_placement_resolve import _surveyed_with_a_triangulated_model

    st, p, s, s_true = _surveyed_with_a_triangulated_model(tmp_path)
    src = tmp_path / "f001_res.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    provider = SectionDataProvider(st)
    dlg = make_dialog(st, p.id, provider=provider)
    dlg.set_file(src)
    dlg.z_combo.setCurrentIndex(dlg.z_combo.findData("elevation"))
    assert "(pinned with a guessed spacing)" in dlg.fit_label.text()
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    d = dlg.dataset
    assert resolve_map(st.profile(p.id), st.station_sets(p.id), d,
                       provider.layout(p.id))[1] == "guessed"


def test_a_refresh_failing_after_the_save_is_a_warning_not_a_failed_import(
        qgis_app, fake_iface, make_dialog, store_with_model, warnings_shown):
    """The data are committed; a listener that raises afterwards must not make the dialog
    report a failed import (a second Add would duplicate the dataset)."""
    from groundwork_geophysics.section.data import SectionDataProvider

    st, p, src = store_with_model
    provider = SectionDataProvider(st)

    def broken():
        raise RuntimeError("panel gone")

    provider.on_change.append(broken)
    dlg = make_dialog(st, p.id, provider=provider)
    dlg.set_file(src)
    dlg.accept()
    assert dlg.result() == 1 and warnings_shown == []
    assert len(st.datasets(p.id)) == 2 and dlg.dataset is not None
    assert dlg.last_warning == "Saved, but the view could not be refreshed: panel gone"
    assert any("panel gone" in i.text() for i in fake_iface.messageBar().items())


def test_the_verdict_stays_above_the_buttons(qgis_app, make_dialog, project_store):
    """Summary, fit line, electrode note and warnings sit outside the scroll area, right above
    Add/Cancel; only the groups and the preview table scroll."""
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    for label in (dlg.summary_label, dlg.fit_label, dlg.electrode_label, dlg.warning_label):
        assert dlg.status_block.isAncestorOf(label) and not dlg._scroll.isAncestorOf(label)
    assert dlg._scroll.isAncestorOf(dlg.preview_table)
    layout = dlg.layout()
    assert layout.indexOf(dlg.status_block) == layout.indexOf(dlg._scroll) + 1


def test_a_fit_that_warns_is_shown_in_the_warning_style(qgis_app, make_dialog, project_store):
    from groundwork_geophysics.ui.fit_line import FIT_WARNING, WARNING_STYLE

    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    dlg.placement.set_positions_file(WILD / "positions_sparse.csv")
    dlg.placement.spacing_edit.setText("12")             # stations 16 and 20 land far off
    qgis_app.processEvents()
    assert dlg.fit_label.styleSheet() == WARNING_STYLE
    assert dlg.fit_label.text().endswith(". " + FIT_WARNING)
    dlg.placement.spacing_edit.setText("5")
    qgis_app.processEvents()
    assert dlg.fit_label.styleSheet() == "" and FIT_WARNING not in dlg.fit_label.text()


def test_a_missing_file_says_what_to_do_here(qgis_app, make_dialog, project_store, tmp_path):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(tmp_path / "does_not_exist.txt")
    text = dlg.summary_label.text()
    assert "does_not_exist.txt: file not found" in text
    assert text.endswith("Check the path, or choose another file.") and "layer" not in text


def test_velocity_table_with_a_coverage_column(qgis_app, make_dialog, project_store,
                                               selected_line, warnings_shown, tmp_path):
    p = tmp_path / "vp.txt"
    p.write_text("dist elev vp cov\n" + "".join(
        f"{x} {z} {500 + x + z} {1 + x / 10}\n" for z in (100, 98, 96) for x in (1, 3, 5, 7)))
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(p)
    box = dlg.columns_group
    _index(box.vertical_combo, 1)
    _index(box.vertical_kind_combo, "elevation")
    _index(box.value_combo, 2)
    _index(box.quantity_combo, "p_velocity")
    assert not box.quantity_name.isVisible()
    _index(box.coverage_combo, 3)
    assert box.roles()[3] == "coverage" and box.roles()[2] == "P-wave velocity"
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [prof] = st.profiles()
    [d] = st.datasets(prof.id)
    assert (d.quantity, d.unit) == ("p_velocity", "m/s")
    assert d.reader_options["columns"]["coverage"] == 3
    assert d.kind == "srt_model"                      # the velocity quantity proposes it


def _refrapy_copy(tmp_path):
    for name in ("L9_xzv.txt", "L9_topography.txt"):
        shutil.copy(FIXTURES / "seismic" / name, tmp_path / name)
    return tmp_path / "L9_xzv.txt"


def test_dialog_preselects_reader_method(qgis_app, make_dialog, project_store, selected_line,
                                         tmp_path):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(_refrapy_copy(tmp_path))
    assert dlg.method_combo.currentData() == "srt"
    assert dlg.method_combo.isVisible() and dlg.method_combo.isEnabled()


def test_dialog_fixes_ert_for_readings(qgis_app, make_dialog, project_store, selected_line,
                                       tmp_path):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    _index(dlg.method_combo, "srt")
    data = tmp_path / "t.data"
    data.write_text(BERT_DATA)
    dlg.set_file(data)
    assert dlg.method_combo.currentData() == "ert" and not dlg.method_combo.isEnabled()
    assert dlg.method_combo.toolTip()


def test_geophone_words(qgis_app, make_dialog, project_store, selected_line, tmp_path,
                        warnings_shown):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(_refrapy_copy(tmp_path))
    assert dlg.electrode_label.text().startswith("Geophones:"), dlg.electrode_label.text()
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    [d] = st.datasets(p.id)
    assert d.kind == "srt_model"


BERT_DATA = """6
# x z
0 10.0
1 10.1
2 10.2
3 10.3
4 10.4
5 10.5
5
# a b m n rhoa err
1 4 2 3 100.0 0.03
2 5 3 4 110.0 0.03
3 6 4 5 120.0 0.03
1 6 2 5 130.0 0.03
1 2 3 4 140.0 0.03
0
"""


def test_summary_values_are_plain_numbers_with_the_unit(qgis_app, tmp_path):
    from groundwork_geophysics import readers
    from groundwork_geophysics.ui.add_data_dialog import describe
    text = describe(readers.read(_refrapy_copy(tmp_path)), "elevation")
    assert "e+0" not in text
    assert text.endswith("m/s") and "1430" in text.replace(".", "").replace(",", "")


def test_method_follows_the_next_file(qgis_app, make_dialog, project_store, selected_line,
                                      tmp_path):
    """A file that names no method gets the method of what it holds, never the previous
    file's: a resistivity model after a Refrapy file is ERT again."""
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(_refrapy_copy(tmp_path))
    assert dlg.method_combo.currentData() == "srt"
    res = tmp_path / "f001_res.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", res)
    dlg.set_file(res)
    assert dlg.method_combo.currentData() == "ert"


def _fine_export(tmp_path, nx=404, nz=250):
    """A model exported on a 0.25 x 0.1 m lattice: 101 000 points by default."""
    path = tmp_path / "fine.txt"
    x, z = np.meshgrid(np.arange(nx) * 0.25, np.arange(nz) * 0.1 + 0.05)
    rho = 10 ** (1 + x / 100)
    lines = [f"{a:.2f} {b:.2f} {c:.3f}" for a, b, c in zip(x.ravel(), z.ravel(), rho.ravel())]
    path.write_text("distance depth rho\n" + "\n".join(lines) + "\n")
    return path


def _digits(text):
    import re
    return re.sub(r"\D", "", text)


def test_an_over_fine_table_is_offered_coarser_cells(qgis_app, make_dialog, project_store,
                                                     tmp_path, selected_line, warnings_shown):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(_fine_export(tmp_path))
    assert not dlg.coarse_row.isHidden() and dlg.coarse_check.isChecked()
    assert (dlg.coarse_dx.value(), dlg.coarse_dz.value()) == pytest.approx((0.5, 0.2))
    assert "25250" in _digits(dlg.coarse_count.text())
    assert "101000" in _digits(dlg.coarse_note.text())
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    [d] = st.datasets(p.id)
    assert d.reader_options["block"] == [2, 2]
    assert d.provenance["cell"] == pytest.approx([0.5, 0.2])


def test_unticked_keeps_the_full_detail(qgis_app, make_dialog, project_store, tmp_path,
                                        selected_line, warnings_shown):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(_fine_export(tmp_path))
    dlg.coarse_check.setChecked(False)
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    [d] = st.datasets(p.id)
    assert "block" not in d.reader_options and "cell" not in d.provenance


def test_a_typed_size_snaps_to_the_files_spacing(qgis_app, make_dialog, project_store,
                                                 tmp_path, selected_line):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(_fine_export(tmp_path))
    dlg.coarse_dx.setValue(1.1)
    dlg.coarse_dx.editingFinished.emit()
    assert dlg.coarse_dx.value() == pytest.approx(1.0)
    assert "12625" in _digits(dlg.coarse_count.text())


def test_a_small_table_shows_no_offer(qgis_app, make_dialog, project_store):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    assert dlg.coarse_row.isHidden() and dlg.coarse_note.isHidden()
    assert "block" not in dlg._reader_options()


def test_an_unticked_offer_stays_unticked_when_the_file_format_changes(
        qgis_app, make_dialog, project_store, tmp_path):
    # the user said no to coarser cells: choosing the delimiter by hand reads the same grid,
    # so the box must not come back ticked
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(_fine_export(tmp_path))
    dlg.coarse_check.setChecked(False)
    _index(dlg.table_options.delimiter_combo, "space")
    assert dlg.table_options.options().delimiter == "space"
    assert not dlg.coarse_row.isHidden() and not dlg.coarse_check.isChecked()
    assert "block" not in dlg._reader_options()
