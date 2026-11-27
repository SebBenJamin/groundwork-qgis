"""Add Data with a radar file (GSSI .dzt, pulseEKKO .dt1 + .hd): the Radargram group instead of
the table and Z rows, a radargram hung with the velocity and time zero typed, fitted to the
line's length on request. Driven programmatically (offscreen)."""
import numpy as np
import pytest

from gpr_files import write_dzt, write_pulseekko

NS = 1e-9


@pytest.fixture(autouse=True)
def no_remembered_settings(qgis_app):
    from qgis.core import QgsSettings

    from groundwork_geophysics.ui.add_data_dialog import RADAR_SETTINGS_KEY
    QgsSettings().remove(RADAR_SETTINGS_KEY)
    yield
    QgsSettings().remove(RADAR_SETTINGS_KEY)


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


def _radargram(n=196, ns=64, arrival=10):
    """Quiet traces with a strong direct wave at sample ``arrival`` (the first two samples are
    the GSSI counter and marks, as in real files)."""
    a = np.zeros((n, ns), np.int32)
    a[:, arrival:arrival + 3] = (8000, -12000, 6000)
    a[:, 0] = np.arange(n) - 32768
    a[:, 1] = -7168
    return a


def _profile(store, length=20.0, name="P1"):
    from groundwork_geophysics.core.model import profile_from_polyline
    p = profile_from_polyline(name, store.crs_authid,
                              np.array([[1000.0, 2000.0], [1000.0 + length, 2000.0]]))
    store.save_profile(p)
    return p


def _type(edit, text):
    edit.setText(text)
    edit.editingFinished.emit()


def test_a_dzt_on_an_existing_profile_is_a_radargram(
        qgis_app, make_dialog, project_store, tmp_path, warnings_shown):
    path = write_dzt(tmp_path / "AAA_____023.DZT", _radargram(), 64.0, scans_per_metre=10.0)
    st, prj = project_store
    p = _profile(st)
    dlg = make_dialog(st, p.id, project=prj)
    dlg.set_file(path)
    box = dlg.radar_box
    assert dlg.format_combo.currentData() == "gssi_dzt"
    assert box.isVisible() and not dlg.segy_box.isVisible() and not dlg.z_combo.isVisible()
    assert not dlg.columns_group.isVisible() and not dlg.table_options.isVisible()
    assert dlg.method_combo.currentData() == "gpr"
    assert box.by_file.isChecked()
    # time zero estimated from the first arrival on the preview read (counter samples skipped)
    assert box.options()["time_zero"] == pytest.approx(10 * NS)
    assert box.time_zero_note.text() == "estimated from the first arrival"
    assert "Enter the velocity or the dielectric constant." in dlg.missing_label.text()
    _type(box.velocity_edit, "0,1")
    box.set_zero("ground")
    dlg.method_combo.setCurrentIndex(dlg.method_combo.findData("refl"))   # never a model
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [d] = st.datasets(p.id)
    assert d.kind == "gpr_section" and d.reader == "gssi_dzt" and d.quantity == "amplitude"
    o = d.reader_options
    assert (o["position"], o["zero"]) == ("file", "ground")
    assert o["velocity"] == pytest.approx(1.0e8) and o["time_zero"] == pytest.approx(10 * NS)
    assert "fit_length" not in o and "datum" not in o
    assert d.name == "AAA_____023 (270MHz)"


def test_the_summary_speaks_of_ns_and_depth(qgis_app, make_dialog, project_store, tmp_path):
    from groundwork_geophysics.core.numbers import fmt_count
    path = write_dzt(tmp_path / "a.dzt", _radargram(), 64.0, scans_per_metre=10.0)
    st, prj = project_store
    p = _profile(st)
    dlg = make_dialog(st, p.id, project=prj)
    dlg.set_file(path)
    _type(dlg.radar_box.velocity_edit, "0,1")
    # 54 ns below time zero at 0.1 m/ns: 2.7 m
    assert dlg.summary_label.text() == (f"{fmt_count(196)} traces × {fmt_count(64)} samples · "
                                        "1 ns · 0 – 64 ns · to 2.7 m depth")


def test_the_file_is_read_once_for_the_preview_and_the_add(
        qgis_app, make_dialog, project_store, tmp_path, warnings_shown, monkeypatch):
    from groundwork_geophysics import readers
    path = write_dzt(tmp_path / "a.dzt", _radargram(), 64.0, scans_per_metre=10.0)
    st, prj = project_store
    p = _profile(st)
    reads = []
    real = readers.read
    monkeypatch.setattr(readers, "read", lambda *a, **k: reads.append(a) or real(*a, **k))
    dlg = make_dialog(st, p.id, project=prj)
    dlg.set_file(path)
    _type(dlg.radar_box.velocity_edit, "0,1")
    _type(dlg.radar_box.time_zero_edit, "12")
    dlg.radar_box.set_zero("datum")
    _type(dlg.radar_box.datum_edit, "100")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    assert len(reads) == 1


def test_the_line_length_is_compared_and_the_file_fitted(
        qgis_app, make_dialog, project_store, tmp_path, warnings_shown):
    from groundwork_geophysics.section.placement_resolve import ProfileLayout, resolve
    path = write_dzt(tmp_path / "a.dzt", _radargram(), 64.0, scans_per_metre=10.0)  # 19.5 m
    st, prj = project_store
    p = _profile(st, 20.0)
    dlg = make_dialog(st, p.id, project=prj)
    dlg.set_file(path)
    box = dlg.radar_box
    assert (box.from_edit.text(), box.to_edit.text()) == ("0", "19.5")
    assert box.fit_check.isVisibleTo(dlg) and not box.fit_check.isChecked()
    _type(box.to_edit, "20")
    assert box.length_label.text() == ("The file is 19.5 m long, the stretch from From to To "
                                       "20 m (2.6 % longer).")
    box.fit_check.setChecked(True)
    _type(box.velocity_edit, "0,1")
    box.set_zero("ground")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [d] = st.datasets(p.id)
    assert "fit_length" not in d.reader_options and "span" not in d.reader_options
    dmap = resolve(st.profile(p.id), st.station_sets(p.id), d, ProfileLayout()).map
    assert dmap([0.0, 19.5]) == pytest.approx([0.0, 20.0])


def test_fitting_against_the_profile_direction(
        qgis_app, make_dialog, project_store, tmp_path, warnings_shown):
    from groundwork_geophysics.section.placement_resolve import ProfileLayout, resolve
    path = write_dzt(tmp_path / "a.dzt", _radargram(), 64.0, scans_per_metre=10.0)
    st, prj = project_store
    p = _profile(st, 20.0)
    dlg = make_dialog(st, p.id, project=prj)
    dlg.set_file(path)
    dlg.placement._expand()
    combo = dlg.placement.zero_combo
    combo.setCurrentIndex(combo.findData("end"))
    combo.activated.emit(combo.currentIndex())
    box = dlg.radar_box
    assert (box.from_edit.text(), box.to_edit.text()) == ("20", "0.5")
    _type(box.to_edit, "0")
    box.fit_check.setChecked(True)
    _type(box.velocity_edit, "0,1")
    box.set_zero("ground")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [d] = st.datasets(p.id)
    dmap = resolve(st.profile(p.id), st.station_sets(p.id), d, ProfileLayout()).map
    assert dmap([0.0, 19.5]) == pytest.approx([20.0, 0.0])


def _long_file(tmp_path):
    """A 124 m file (1241 traces, 10 a metre)."""
    return write_dzt(tmp_path / "long.dzt", _radargram(n=1241), 64.0, scans_per_metre=10.0)


def _add_between(make_dialog, st, prj, p, path, start, end, fit):
    dlg = make_dialog(st, p.id, project=prj)
    dlg.set_file(path)
    box = dlg.radar_box
    _type(box.from_edit, start)
    _type(box.to_edit, end)
    box.fit_check.setChecked(fit)
    _type(box.velocity_edit, "0,1")
    box.set_zero("ground")
    dlg.accept()
    assert dlg.result() == 1
    return dlg


@pytest.mark.parametrize("start, end, fit, expected", [
    ("25,5", "136,8", True, [25.5, 136.8]),
    ("136,8", "25,5", True, [136.8, 25.5]),
    ("25,5", "136,8", False, [25.5, 149.5]),
    ("136,8", "25,5", False, [136.8, 12.8])])
def test_a_file_fitted_between_two_points_of_the_profile(
        qgis_app, make_dialog, project_store, tmp_path, start, end, fit, expected):
    from groundwork_geophysics.section.placement_resolve import ProfileLayout, resolve
    st, prj = project_store
    p = _profile(st, 140.0)
    dlg = _add_between(make_dialog, st, prj, p, _long_file(tmp_path), start, end, fit)
    [d] = st.datasets(p.id)
    dmap = resolve(st.profile(p.id), st.station_sets(p.id), d, ProfileLayout()).map
    assert dmap([0.0, 124.0]) == pytest.approx(expected)
    assert "span" not in d.reader_options


def test_untouched_from_and_to_place_the_file_as_before(
        qgis_app, make_dialog, project_store, tmp_path, warnings_shown):
    st, prj = project_store
    p = _profile(st, 140.0)
    dlg = make_dialog(st, p.id, project=prj)
    dlg.set_file(_long_file(tmp_path))
    dlg.placement._expand()
    combo = dlg.placement.zero_combo
    combo.setCurrentIndex(combo.findData("end"))
    combo.activated.emit(combo.currentIndex())
    dlg.placement.offset_spin.setValue(16.9)
    box = dlg.radar_box
    assert (box.from_edit.text(), box.to_edit.text()) == ("123.1", "-0.9")
    _type(box.velocity_edit, "0,1")
    box.set_zero("ground")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [d] = st.datasets(p.id)
    assert d.reader_options["placement"] == {"zero": pytest.approx(140.0), "direction": -1,
                                             "own": True}
    assert d.reader_options["chainage_offset"] == pytest.approx(16.9)


def test_a_new_line_offers_its_start_and_end(qgis_app, make_dialog, project_store, tmp_path):
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(write_dzt(tmp_path / "a.dzt", _radargram(), 64.0, scans_per_metre=10.0))
    dlg.placement.select_source("points")
    dlg.placement.set_points(1000.0, 2000.0, 1030.0, 2000.0)
    box = dlg.radar_box
    assert (box.from_edit.text(), box.to_edit.text()) == ("0", "30")


def test_a_file_without_a_distance_wheel_asks_for_the_spacing(
        qgis_app, make_dialog, project_store, tmp_path, warnings_shown):
    path = write_dzt(tmp_path / "a.dzt", _radargram(), 64.0, scans_per_metre=0.0)
    st, prj = project_store
    p = _profile(st)
    dlg = make_dialog(st, p.id, project=prj)
    dlg.set_file(path)
    box = dlg.radar_box
    assert box.by_spacing.isChecked()
    assert box.position_note.text() == "This file was recorded without a distance wheel."
    assert "Enter the trace spacing in metres." in dlg.missing_label.text()
    _type(box.spacing_edit, "0,1")
    _type(box.velocity_edit, "0,1")
    box.set_zero("ground")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [d] = st.datasets(p.id)
    assert (d.reader_options["position"], d.reader_options["spacing"]) == ("spacing", 0.1)


@pytest.mark.parametrize("chosen", [".DT1", ".HD"])
def test_the_pulseekko_pair_is_added_by_either_file(
        qgis_app, make_dialog, project_store, tmp_path, warnings_shown, chosen):
    a = np.zeros((101, 50), np.int16)
    a[:, 12:15] = (3000, -5000, 2000)
    dt1 = write_pulseekko(tmp_path / "LINE00.DT1", a, 50.0, step_m=0.2, timezero_point=13)
    st, prj = project_store
    p = _profile(st)
    dlg = make_dialog(st, p.id, project=prj)
    dlg.set_files([dt1.with_suffix(chosen)])
    assert dlg.format_combo.currentData() == "pulseekko"
    assert dlg.radar_box.time_zero_note.text() == "from the file"
    _type(dlg.radar_box.velocity_edit, "0,1")
    dlg.radar_box.set_zero("ground")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [d] = st.datasets(p.id)
    assert d.source_path.endswith("LINE00.DT1") and d.reader == "pulseekko"
    assert d.reader_options["header_file"] == "LINE00.HD"
    assert d.reader_options["time_zero"] == pytest.approx(12 * 50.0 / 50 * NS)


def test_choosing_both_files_of_a_pair_adds_one(qgis_app, make_dialog, project_store, tmp_path):
    a = np.zeros((101, 50), np.int16)
    dt1 = write_pulseekko(tmp_path / "LINE00.DT1", a, 50.0, step_m=0.2, timezero_point=13)
    st, prj = project_store
    p = _profile(st)
    dlg = make_dialog(st, p.id, project=prj)
    dlg.set_files([dt1, dt1.with_suffix(".HD")])
    assert dlg._files == [] and dlg._path() == str(dt1)


def test_a_new_header_reads_the_line_again(tmp_path):
    import os
    from groundwork_geophysics.section.data import _companion_mtime
    a = np.zeros((11, 50), np.int16)
    dt1 = write_pulseekko(tmp_path / "LINE00.DT1", a, 50.0)
    before = _companion_mtime(str(dt1), {"header_file": "LINE00.HD"})
    hd = dt1.with_suffix(".HD")
    os.utime(hd, (before + 10, before + 10))
    assert _companion_mtime(str(dt1), {"header_file": "LINE00.HD"}) == before + 10


def test_the_time_zero_choice_and_the_placement_are_remembered(
        qgis_app, make_dialog, project_store, tmp_path, warnings_shown):
    first = write_dzt(tmp_path / "a.dzt", _radargram(), 64.0, scans_per_metre=0.0)
    st, prj = project_store
    p = _profile(st)
    dlg = make_dialog(st, p.id, project=prj)
    dlg.set_file(first)
    _type(dlg.radar_box.spacing_edit, "0,1")
    _type(dlg.radar_box.velocity_edit, "0,1")
    dlg.radar_box.set_zero("datum")
    _type(dlg.radar_box.datum_edit, "250")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    second = write_dzt(tmp_path / "b.dzt", _radargram(), 64.0, scans_per_metre=0.0)
    again = make_dialog(st, p.id, project=prj)
    again.set_file(second)
    box = again.radar_box
    assert box.zero() == "datum" and box.position() == "spacing"
    assert box.datum_edit.text() == "" and box.velocity_edit.text() == ""
    assert box.spacing_edit.text() == ""


def test_hanging_on_a_profile_without_heights_is_warned_about(
        qgis_app, make_dialog, project_store, tmp_path):
    from groundwork_geophysics.ui.add_data_dialog import NO_HEIGHTS
    path = write_dzt(tmp_path / "a.dzt", _radargram(), 64.0, scans_per_metre=10.0)
    st, prj = project_store
    p = _profile(st)
    dlg = make_dialog(st, p.id, project=prj)
    dlg.set_file(path)
    _type(dlg.radar_box.velocity_edit, "0,1")
    dlg.radar_box.set_zero("ground")
    assert NO_HEIGHTS["ground"] in dlg.warning_label.text()
    assert dlg.add_button.isEnabled()


def test_several_radar_files_each_take_their_own_time_zero(
        qgis_app, make_dialog, project_store, tmp_path, warnings_shown):
    from groundwork_geophysics.ui.add_data_files import READY
    st, prj = project_store
    p1, p2 = _profile(st, name="L1"), _profile(st, name="L2")
    a = write_dzt(tmp_path / "L1.dzt", _radargram(arrival=10), 64.0, scans_per_metre=10.0)
    b = write_dzt(tmp_path / "L2.dzt", _radargram(arrival=20), 64.0, scans_per_metre=10.0)
    dlg = make_dialog(st, project=prj)
    dlg.set_files([a, b])
    box = dlg.files_box
    _type(dlg.radar_box.velocity_edit, "0,1")
    dlg.radar_box.set_zero("ground")
    assert [box.status(i) for i in range(2)] == [READY, READY]
    assert [box.time_zero_text(i) for i in range(2)] == ["10 ns (estimated)",
                                                          "20 ns (estimated)"]
    assert not box.table.isColumnHidden(box.TIME_ZERO)
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    zeros = {d.profile_id: d.reader_options for d in st.datasets(p1.id) + st.datasets(p2.id)}
    assert zeros[p1.id]["time_zero"] == pytest.approx(10 * NS)
    assert zeros[p2.id]["time_zero"] == pytest.approx(20 * NS)
    assert zeros[p1.id]["velocity"] == zeros[p2.id]["velocity"] == pytest.approx(1.0e8)


def test_the_time_zero_column_is_only_for_radar(qgis_app):
    from groundwork_geophysics.ui.add_data_files import FilesBox
    box = FilesBox()
    box.set_files(["a.csv", "b.csv"], [], False)
    assert box.table.isColumnHidden(box.TIME_ZERO)
    box.deleteLater()
