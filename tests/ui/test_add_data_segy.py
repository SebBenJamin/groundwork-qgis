"""Add Data with a SEG-Y file: the SEG-Y Section group instead of the table and Z rows, the
section placed by a trace spacing or by the positions in its headers, and segyio installed on
the user's click when it is missing. Driven programmatically (offscreen)."""
import time

import numpy as np
import pytest

from segy_files import require_segyio

require_segyio()

from segy_files import write_segy  # noqa: E402

#: trace positions (EPSG:25832) along a line with one bend
LINE = [(500000, 5700000), (500010, 5700000), (500020, 5700000), (500030, 5700010),
        (500040, 5700020), (500050, 5700030)]


@pytest.fixture(autouse=True)
def no_remembered_settings(qgis_app):
    from qgis.core import QgsSettings

    from groundwork_geophysics.ui.add_data_dialog import SEGY_SETTINGS_KEY, SETTINGS_KEY
    for key in (SETTINGS_KEY, SEGY_SETTINGS_KEY):
        QgsSettings().remove(key)
    yield
    for key in (SETTINGS_KEY, SEGY_SETTINGS_KEY):
        QgsSettings().remove(key)


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
    """A selected memory line (EPSG:25832) from (1000, 2000) to (1100, 2000)."""
    from qgis.core import QgsFeature, QgsGeometry, QgsVectorLayer

    layer = QgsVectorLayer("LineString?crs=EPSG:25832", "survey_lines", "memory")
    f = QgsFeature()
    f.setGeometry(QgsGeometry.fromWkt("LineString (1000 2000, 1100 2000)"))
    layer.dataProvider().addFeatures([f])
    layer.selectAll()
    fake_iface.setActiveLayer(layer)
    yield layer
    fake_iface.setActiveLayer(None)


def _amplitudes(n=3, ns=4):
    return np.arange(n * ns, dtype=np.float32).reshape(n, ns) - 5.0


def _type(edit, text):
    edit.setText(text)
    edit.editingFinished.emit()


def _wait(qgis_app, done, seconds=20.0):
    end = time.monotonic() + seconds
    while not done() and time.monotonic() < end:
        qgis_app.processEvents()
        time.sleep(0.01)
    assert done()


def test_a_spacing_file_on_a_new_line_is_a_reflection_section(
        qgis_app, make_dialog, project_store, selected_line, tmp_path, warnings_shown):
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    assert dlg.format_combo.currentData() == "segy"
    assert dlg.segy_box.isVisible() and not dlg.z_combo.isVisible()
    assert not dlg.columns_group.isVisible() and not dlg.table_options.isVisible()
    assert dlg.method_combo.currentData() == "refl"
    assert "Enter the trace spacing in metres." in dlg.missing_label.text()
    _type(dlg.segy_box.spacing_edit, "2")
    _type(dlg.segy_box.velocity_edit, "1500")
    dlg.segy_box.set_zero("ground")
    assert dlg.placement.source() == "line"
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    [d] = st.datasets(p.id)
    assert d.kind == "refl_section" and d.reader == "segy" and d.quantity == "amplitude"
    o = d.reader_options
    assert (o["position"], o["spacing"], o["domain"], o["velocity"], o["zero"]) == \
        ("spacing", 2.0, "time", 1500.0, "ground")
    assert "sample_step" not in o and "datum" not in o


def test_another_method_still_gives_a_reflection_section(
        qgis_app, make_dialog, project_store, selected_line, tmp_path, warnings_shown):
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    _type(dlg.segy_box.spacing_edit, "2")
    _type(dlg.segy_box.velocity_edit, "1500")
    dlg.segy_box.set_zero("ground")
    dlg.method_combo.setCurrentIndex(dlg.method_combo.findData("ert"))
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    assert st.datasets(p.id)[0].kind == "refl_section"


def test_positions_in_the_file_make_a_profile_through_them(
        qgis_app, make_dialog, project_store, tmp_path, warnings_shown):
    path = write_segy(tmp_path / "line2.sgy", _amplitudes(len(LINE)), dt_us=2000, xy=LINE,
                      xy_field="source")
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    box = dlg.segy_box
    assert box.by_positions.isChecked() and box.field_combo.currentData() == "source"
    assert dlg.placement.source() == "file"
    assert dlg.placement.findChild(
        __import__("qgis.PyQt.QtWidgets", fromlist=["x"]).QRadioButton,
        "source_file").isEnabled()
    _type(box.velocity_edit, "1500")
    box.set_zero("ground")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    [p] = st.profiles()
    xy =np.asarray(p.chainage.xy, float)[:, :2]
    assert len(xy) == 3                                  # a crooked line stays a polyline
    assert np.allclose(xy[0], LINE[0]) and np.allclose(xy[-1], LINE[-1])
    [d] = st.datasets(p.id)
    o = d.reader_options
    assert (o["position"], o["xy_field"], o["crs"]) == ("map", "source", "EPSG:25832")
    assert "placement" not in o and o["chainage_offset"] == 0.0
    assert d.provenance["max_offset"] < 0.1                  # on the line made through them


def test_the_summary_line(qgis_app, make_dialog, project_store, selected_line, tmp_path):
    from groundwork_geophysics.core.numbers import fmt_count
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    _type(dlg.segy_box.spacing_edit, "2")
    dlg.segy_box.set_zero("ground")
    text = (f"{fmt_count(3)} traces × {fmt_count(4)} samples · 2 ms · 0 – 0.008 s")
    assert text == "3 traces × 4 samples · 2 ms · 0 – 0.008 s"
    # what is still missing to hang it follows below, in the warning style
    from groundwork_geophysics.ui.fit_line import WARNING_STYLE
    assert dlg.summary_label.text() == text
    assert dlg.missing_label.text() == "Enter the velocity in m/s."
    assert dlg.missing_label.styleSheet() == WARNING_STYLE and dlg.missing_label.isVisible()
    _type(dlg.segy_box.velocity_edit, "1500")
    # the last sample, 6 ms, at 1500 m/s: 4.5 m; below 10 m with one decimal, as the times
    assert dlg.summary_label.text() == text + " · to 4.5 m depth"
    assert dlg.missing_label.text() == "" and not dlg.missing_label.isVisible()
    dlg.segy_box.set_domain("depth")
    assert dlg.summary_label.text() == "3 traces × 4 samples · 2 m · 0 – 8 m"


def test_an_unstacked_file_is_warned_about(qgis_app, make_dialog, project_store,
                                           selected_line, tmp_path):
    path = write_segy(tmp_path / "gather.sgy", _amplitudes(), dt_us=2000,
                      offsets=[100, 200, 300])
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    _type(dlg.segy_box.spacing_edit, "2")
    assert "looks like unstacked records" in dlg.warning_label.text()
    assert dlg.add_button.isEnabled()


NO_HEIGHTS = {
    "ground": ("This profile has no heights yet. Choose an elevation model in Context Layers, "
               "or the section hangs flat."),
    "datum_ground": ("This profile has no heights yet. Choose an elevation model in Context "
                     "Layers first: a section corrected to the ground needs them."),
}


@pytest.mark.parametrize("zero", ["ground", "datum_ground"])
def test_a_ground_zero_on_a_new_profile_without_heights_is_warned_about(
        qgis_app, make_dialog, project_store, selected_line, tmp_path, zero):
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    _type(dlg.segy_box.spacing_edit, "2")
    _type(dlg.segy_box.velocity_edit, "1500")
    dlg.segy_box.set_zero(zero)
    _type(dlg.segy_box.datum_edit, "100")
    _type(dlg.segy_box.replacement_edit, "1800")
    assert dlg.placement.source() == "line"
    assert NO_HEIGHTS[zero] in dlg.warning_label.text()
    assert dlg.add_button.isEnabled()                       # a warning, not a block


def test_an_unusual_velocity_is_warned_about_in_add_data(qgis_app, make_dialog, project_store,
                                                        selected_line, tmp_path):
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    _type(dlg.segy_box.spacing_edit, "2")
    _type(dlg.segy_box.velocity_edit, "150")
    dlg.segy_box.set_zero("ground")
    assert "unusual for seismic data. Check the unit (m/s)." in dlg.warning_label.text()
    assert dlg.add_button.isEnabled()


def test_a_fixed_height_is_not_warned_about(qgis_app, make_dialog, project_store,
                                            selected_line, tmp_path):
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    _type(dlg.segy_box.spacing_edit, "2")
    _type(dlg.segy_box.velocity_edit, "1500")
    dlg.segy_box.set_zero("datum")
    _type(dlg.segy_box.datum_edit, "100")
    assert "no heights" not in dlg.warning_label.text()


def test_a_new_profile_with_an_elevation_model_is_not_warned_about(
        qgis_app, make_dialog, project_store, selected_line, tmp_path):
    from qgis.core import QgsRasterLayer

    from groundwork_geophysics.core.context_settings import ContextSettings
    from groundwork_geophysics.ui.context_dialog import write_settings
    from osgeo import gdal
    gdal.UseExceptions()
    tif = str(tmp_path / "dem.tif")
    ds = gdal.GetDriverByName("GTiff").Create(tif, 4, 4, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((900, 100, 0, 2100, 0, -100))
    ds.GetRasterBand(1).Fill(50.0)
    ds = None
    st, prj = project_store
    dem = QgsRasterLayer(tif, "dem")
    prj.addMapLayer(dem)
    write_settings(prj, ContextSettings(dem_layer_id=dem.id()))
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    _type(dlg.segy_box.spacing_edit, "2")
    _type(dlg.segy_box.velocity_edit, "1500")
    dlg.segy_box.set_zero("ground")
    assert "no heights" not in dlg.warning_label.text()


@pytest.mark.parametrize("heights", [True, False])
def test_an_existing_profile_is_warned_about_only_without_station_heights(
        qgis_app, make_dialog, project_store, tmp_path, heights):
    from groundwork_geophysics.core.model import attach_station_set, profile_from_polyline
    from groundwork_geophysics.section.data import SectionDataProvider
    st, prj = project_store
    p = profile_from_polyline("L1", st.crs_authid, np.array([[0.0, 0.0], [100.0, 0.0]]))
    st.save_profile(p)
    if heights:
        st.save_station_set(attach_station_set(p, "S", "refl", np.column_stack(
            [np.arange(6) * 20.0, np.zeros(6), np.full(6, 100.0)])))
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    dlg = make_dialog(st, p.id, project=prj, provider=SectionDataProvider(st))
    dlg.set_file(path)
    _type(dlg.segy_box.spacing_edit, "2")
    _type(dlg.segy_box.velocity_edit, "1500")
    for zero in ("ground", "datum_ground"):
        dlg.segy_box.set_zero(zero)
        _type(dlg.segy_box.datum_edit, "120")
        _type(dlg.segy_box.replacement_edit, "1800")
        assert dlg.placement.source() == "existing"
        assert (NO_HEIGHTS[zero] in dlg.warning_label.text()) is not heights


def test_a_3d_volume_cannot_be_added(qgis_app, make_dialog, project_store, tmp_path):
    path = write_segy(tmp_path / "cube.sgy", _amplitudes(4), dt_us=2000,
                      inline=[1, 1, 2, 2], crossline=[1, 2, 1, 2])
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    assert "this is a 3D volume (2 inlines × 2 crosslines)" in dlg.summary_label.text()
    assert not dlg.add_button.isEnabled()


@pytest.fixture
def no_segyio(monkeypatch):
    from groundwork_geophysics import libs
    state = {"installed": False, "calls": 0}
    monkeypatch.setattr(libs, "available", lambda name: state["installed"])
    return state


def test_without_segyio_the_install_button_is_offered(
        qgis_app, make_dialog, project_store, tmp_path, no_segyio):
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    assert dlg.summary_label.text() == ("Reading SEG-Y needs the free library segyio "
                                        "(0.4 MB), which is not installed.")
    assert dlg.install_button.isVisible() and dlg.install_button.text() == "Install segyio"
    assert not dlg.add_button.isEnabled()
    assert not dlg.segy_box.isVisible()


def test_a_failed_install_shows_the_message(qgis_app, make_dialog, project_store, tmp_path,
                                            no_segyio, monkeypatch):
    from groundwork_geophysics import libs
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    monkeypatch.setattr(libs, "install", lambda name, **_options: (False, "no network\n<command>"))
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    dlg.install_button.click()
    _wait(qgis_app, lambda: dlg.install_button.text() == "Install segyio")
    text = dlg.summary_label.text()
    assert "no network" in text and "<command>" in text and "segyio" in text
    assert dlg.summary_label.textInteractionFlags() & \
        __import__("qgis.PyQt.QtCore", fromlist=["x"]).Qt.TextInteractionFlag.TextSelectableByMouse
    assert dlg.install_button.isEnabled() and not dlg.add_button.isEnabled()


def test_after_the_install_the_file_is_read(qgis_app, make_dialog, project_store, tmp_path,
                                            no_segyio, monkeypatch):
    from groundwork_geophysics import libs
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    seen = []

    def install(name, **_options):
        seen.append(name)
        no_segyio["installed"] = True
        return True, "segyio 1.9.15 is installed."
    monkeypatch.setattr(libs, "install", install)
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    dlg.install_button.click()
    assert dlg.install_button.text() == "Installing…" and not dlg.install_button.isEnabled()
    _wait(qgis_app, lambda: dlg.install_button.isHidden())
    assert seen == ["segyio"] and dlg.segy_box.isVisible()
    assert "Enter the trace spacing in metres." in dlg.missing_label.text()


def test_closing_the_dialog_while_installing_is_safe(qgis_app, make_dialog, project_store,
                                                     tmp_path, no_segyio, monkeypatch):
    from groundwork_geophysics import libs
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    finished = []

    def install(name, **_options):
        time.sleep(0.3)
        finished.append(name)
        return True, "segyio is installed."
    monkeypatch.setattr(libs, "install", install)
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    dlg.install_button.click()
    dlg.reject()
    dlg.deleteLater()
    _wait(qgis_app, lambda: bool(finished))
    for _ in range(20):
        qgis_app.processEvents()
        time.sleep(0.01)


def test_the_last_segy_settings_are_offered_again(qgis_app, make_dialog, project_store,
                                                  selected_line, tmp_path, warnings_shown):
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    box = dlg.segy_box
    _type(box.spacing_edit, "2")
    _type(box.velocity_edit, "1500")
    box.set_zero("datum")
    _type(box.datum_edit, "120")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    again = make_dialog(st, project=prj)
    again.set_file(write_segy(tmp_path / "line3.sgy", _amplitudes(), dt_us=2000))
    o = again.segy_box.options()
    assert o["zero"] == "datum" and "datum" not in o        # the height is the file's own
    assert "velocity" not in o and "spacing" not in o       # file-specific: not remembered


def test_an_old_remembered_crs_and_height_are_ignored(qgis_app, make_dialog, project_store,
                                                     tmp_path):
    import json

    from qgis.core import QgsSettings

    from groundwork_geophysics.ui.add_data_dialog import SEGY_SETTINGS_KEY
    QgsSettings().setValue(SEGY_SETTINGS_KEY, json.dumps(
        {"zero": "datum", "datum": 120.0, "crs": "EPSG:2056", "position": "map",
         "velocity_kind": "interval", "domain": "time"}))
    path = write_segy(tmp_path / "line2.sgy", _amplitudes(len(LINE)), dt_us=2000, xy=LINE)
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    o = dlg.segy_box.options()
    assert o["zero"] == "datum" and "datum" not in o
    assert o["crs"] == "EPSG:25832"                         # the project's, not the old one
    assert dlg.segy_box.kind_combo.currentData() == "interval"


def test_time_zero_starts_at_a_fixed_height_to_be_typed(qgis_app, make_dialog, project_store,
                                                        selected_line, tmp_path):
    path = write_segy(tmp_path / "line1.sgy", _amplitudes(), dt_us=2000)
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    box = dlg.segy_box
    assert box.zero() == "datum" and box.datum_edit.text() == ""
    _type(box.spacing_edit, "2")
    _type(box.velocity_edit, "1500")
    assert "Enter the height of time zero." in dlg.missing_label.text()
    assert "Enter the height of time zero." in box.problems()


LV03 = [(525014, 161279), (524500, 159000), (522995, 153108)]
OUTSIDE = ("These positions lie outside the area where CH1903+ / LV95 is used. Check the "
           "position fields and the CRS.")


def _ask(monkeypatch, answer):
    from qgis.PyQt.QtWidgets import QMessageBox
    asked = []

    def question(parent, title, text, *a, **k):
        asked.append(text)
        return answer
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return asked


def test_positions_outside_the_crs_area_are_warned_about_and_asked(
        qgis_app, make_dialog, project_store, tmp_path, monkeypatch, warnings_shown):
    from qgis.core import QgsCoordinateReferenceSystem
    from qgis.PyQt.QtWidgets import QMessageBox
    path = write_segy(tmp_path / "vaud.sgy", _amplitudes(len(LV03)), dt_us=2000, xy=LV03,
                      xy_field="group")
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    box = dlg.segy_box
    assert box.by_positions.isChecked()
    box.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:2056"))
    _type(box.velocity_edit, "3000")
    box.set_zero("ground")
    assert OUTSIDE in dlg.warning_label.text()
    assert dlg.add_button.isEnabled()                       # a warning, not a block
    asked = _ask(monkeypatch, QMessageBox.StandardButton.No)
    dlg.accept()
    assert asked == [OUTSIDE[:-1] + ". Add it anyway?"] and dlg.result() == 0
    assert st.profiles() == []
    box.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:21781"))     # LV03: right
    assert "outside the area" not in dlg.warning_label.text()


def test_line_metres_in_a_utm_zone_are_outside_its_area(qgis_app, make_dialog, project_store,
                                                        tmp_path):
    from qgis.core import QgsCoordinateReferenceSystem
    xy = [(4, 0), (100, 0), (560, 0)]
    path = write_segy(tmp_path / "carfax.sgy", _amplitudes(3), dt_us=2000, xy=xy)
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    box = dlg.segy_box
    assert box.by_spacing.isChecked()                       # not proposed
    assert box.position_note.text().startswith("The positions in this file look like distances")
    box.by_positions.setChecked(True)
    box.crs_widget.setCrs(QgsCoordinateReferenceSystem("EPSG:32632"))
    _type(box.velocity_edit, "1500")
    box.set_zero("ground")
    text = dlg.warning_label.text()
    assert "look like distances along the line" in text
    assert "outside the area where WGS 84 / UTM zone 32N is used" in text


def test_several_segy_files_take_the_box_settings(qgis_app, make_dialog, project_store,
                                                  tmp_path, warnings_shown):
    from groundwork_geophysics.core.model import profile_from_polyline
    from groundwork_geophysics.ui.add_data_files import READY
    st, prj = project_store
    p = profile_from_polyline("L1", st.crs_authid, np.array([[0.0, 0.0], [100.0, 0.0]]))
    st.save_profile(p)
    a = write_segy(tmp_path / "a.sgy", _amplitudes(), dt_us=2000)
    b = write_segy(tmp_path / "b.sgy", _amplitudes(), dt_us=2000)
    dlg = make_dialog(st, project=prj)
    dlg.set_files([a, b])
    _type(dlg.segy_box.spacing_edit, "2")
    _type(dlg.segy_box.velocity_edit, "1500")
    dlg.segy_box.set_zero("ground")
    for row in range(2):
        dlg.files_box.set_target(row, p.id)
    assert [dlg.files_box.status(r) for r in range(2)] == [READY, READY]
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    ds = st.datasets(p.id)
    assert sorted(d.name for d in ds) == ["a", "b"]
    assert all(d.kind == "refl_section" and d.reader_options["spacing"] == 2.0 for d in ds)


def test_a_file_without_the_chosen_positions_is_left_for_its_row(
        qgis_app, make_dialog, project_store, tmp_path):
    from groundwork_geophysics.ui.add_data_files import READY
    st, prj = project_store
    a = write_segy(tmp_path / "a.sgy", _amplitudes(len(LINE)), dt_us=2000, xy=LINE)
    b = write_segy(tmp_path / "b.sgy", _amplitudes(), dt_us=2000)
    dlg = make_dialog(st, project=prj)
    dlg.set_files([a, b])
    _type(dlg.segy_box.velocity_edit, "1500")
    dlg.segy_box.set_zero("ground")
    assert dlg.segy_box.by_positions.isChecked()
    assert dlg.files_box.status(0) == READY
    assert "no positions" in dlg.files_box.status(1)


def test_new_profile_offers_seismic_reflection(qgis_app, fake_iface, project_store):
    from groundwork_geophysics.ui.new_profile_dialog import NewProfileDialog
    st, prj = project_store
    dlg = NewProfileDialog(fake_iface, st, prj, None)
    combo = next(c for c in dlg.findChildren(
        __import__("qgis.PyQt.QtWidgets", fromlist=["x"]).QComboBox) if c.findData("refl") >= 0)
    assert combo.itemText(combo.findData("refl")) == "Seismic reflection"
    dlg.deleteLater()


def test_read_for_places_a_section_by_its_header_positions(qgis_app, project_store, tmp_path):
    from groundwork_geophysics.core.model import profile_from_polyline
    from groundwork_geophysics.ui.project_actions import read_for
    st, _prj = project_store
    path = write_segy(tmp_path / "line2.sgy", _amplitudes(len(LINE)), dt_us=2000, xy=LINE)
    p = profile_from_polyline("L", st.crs_authid, np.array(LINE, float))
    result = read_for(st, p, path, "segy", {"position": "map", "xy_field": "source",
                                            "crs": "EPSG:25832", "velocity": 1500.0})
    assert result.mesh is None and result.traces.x[-1] == pytest.approx(p.chainage.length)


def test_traces_sharing_positions_are_warned_about(qgis_app, make_dialog, project_store,
                                                   selected_line, tmp_path):
    """A shot record (traces repeating positions) gets a warning; Add stays possible."""
    from groundwork_geophysics.ui.add_data_dialog import REPEATS
    line = [(500000 + 4 * i, 5700000) for i in range(20)]
    xy = line + line[-5:] * 4
    path = write_segy(tmp_path / "shot.sgy", np.zeros((len(xy), 4), np.float32), dt_us=2000,
                      xy=xy, cdp=list(range(1, len(xy) + 1)))
    st, prj = project_store
    dlg = make_dialog(st, project=prj)
    dlg.set_file(path)
    _type(dlg.segy_box.spacing_edit, "2")
    assert REPEATS in dlg.warning_label.text()
    assert REPEATS == ("Many traces of this file share a position or run back along the "
                       "line. It looks like a shot record or several passes, not one section "
                       "along a line.")
    assert dlg.add_button.isEnabled()
