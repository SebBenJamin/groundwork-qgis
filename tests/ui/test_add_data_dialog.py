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

    from geophysics_workbench.ui.add_data_dialog import SETTINGS_KEY
    QgsSettings().remove(SETTINGS_KEY)
    yield
    QgsSettings().remove(SETTINGS_KEY)


@pytest.fixture
def make_dialog(qgis_app, fake_iface):
    from geophysics_workbench.ui.add_data_dialog import AddDataDialog

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
    assert not dlg.method_combo.isVisible()          # a line makes no station set
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
                                                   selected_line):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "dist_y_rho_junk.txt")
    _index(dlg.placement.zero_combo, "end")
    dlg.accept()
    [p] = st.profiles()
    [d] = st.datasets(p.id)
    assert d.reader_options["placement"] == {"zero": pytest.approx(100.0), "direction": -1}


def test_map_file_creates_its_own_profile(qgis_app, make_dialog, project_store,
                                          warnings_shown):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(WILD / "east_north_depth_rho.csv")
    cols = dlg.columns_group.columns()
    assert cols.position == "map"
    assert dlg.placement.source() == "file"
    assert "bend" in dlg.placement.file_info.text() or " m" in dlg.placement.file_info.text()
    assert "No electrode positions" in dlg.electrode_label.text()
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    rows = np.loadtxt(WILD / "east_north_depth_rho.csv", delimiter=",", skiprows=1)
    file_length = float(np.hypot(*(rows[-1, :2] - rows[0, :2])))
    assert abs(p.chainage.length - file_length) < 2.0
    [d] = st.datasets(p.id)
    assert "placement" not in d.reader_options and d.station_set_id == ""
    assert d.reader_options["columns"]["position"] == "map"


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
    from geophysics_workbench.core.model import profile_from_polyline

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
    # table read) stops after the sample; Add reads the whole file
    from geophysics_workbench import readers
    from geophysics_workbench.readers import text_columns
    from geophysics_workbench.ui import add_data_dialog

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

    from geophysics_workbench.ui.add_data_dialog import SETTINGS_KEY
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
    assert not dlg.method_combo.isVisible()
    dlg.set_file(FIXTURES / "ert" / "f001_res.dat")
    assert dlg.placement.zero_combo.currentData() == "station1"   # as 0.8 placed it


def test_add_data_attaches_positions_to_an_existing_profile(qgis_app, project_store, tmp_path):
    from geophysics_workbench.core.model import profile_from_polyline
    from geophysics_workbench.core.placement import Placement, Positions
    from geophysics_workbench.ui.project_actions import add_data

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
    from geophysics_workbench.core.placement import Placement
    from geophysics_workbench.ui.project_actions import add_data

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


def test_menu_entry_is_add_data_and_needs_only_a_project(qgis_app, fake_iface, tmp_path):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench.plugin import WorkbenchPlugin
    from geophysics_workbench.ui.project_actions import new_store

    prj = QgsProject.instance()
    prj.clear()
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        texts = [a.text() for a in plugin.menu.actions()]
        assert "Add Data…" in texts and "Add ERT Model…" not in texts
        assert not plugin.add_data_action.isEnabled()
        assert "Open or create a workbench project" in plugin.add_data_action.toolTip()
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
    from geophysics_workbench import readers
    from geophysics_workbench.ui import add_data_dialog

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
    from geophysics_workbench.core.model import attach_station_set

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
    from geophysics_workbench.core.placement import Placement, Positions
    from geophysics_workbench.ui.project_actions import add_data

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

    from geophysics_workbench import readers
    from geophysics_workbench.ui.add_data_dialog import describe

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
