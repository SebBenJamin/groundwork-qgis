"""Profile Properties: name, surveyed positions (keep the line or move it), spacing and the
reference height of an existing profile. Driven programmatically (offscreen)."""
import shutil
from pathlib import Path

import numpy as np
import pytest

from tests.conftest import FIXTURES

WILD = FIXTURES / "wild"
POSITIONS = WILD / "positions_sparse.csv"


@pytest.fixture
def make_dialog(qgis_app, fake_iface):
    from qgis.core import QgsProject

    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.ui.profile_properties_dialog import ProfilePropertiesDialog

    made = []

    def make(store, profile_id):
        provider = SectionDataProvider(store)
        dlg = ProfilePropertiesDialog(fake_iface, store, profile_id, provider, QgsProject())
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
def drawn(tmp_path):
    """A drawn-line profile along the positions file's direction, with a model (no stations)."""
    from groundwork_geophysics.core.model import (Dataset, file_fingerprint,
                                                 profile_from_polyline)
    from groundwork_geophysics.store.gpkg_store import ProjectStore

    st = ProjectStore.create(tmp_path / "d.gpkg", "EPSG:25832")
    line = np.array([[437700.0, 5850700.0], [437800.0, 5850757.7]])
    p = profile_from_polyline("Drawn", "EPSG:25832", line)
    st.save_profile(p)
    src = tmp_path / "f001_res.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("d1", p.id, "", "ert_model", str(src), mt, sha, "r2_res_dat",
                            {"z_kind": "depth"}, {}, name="model"))
    return st, p


def _bounds(st, pid):
    from groundwork_geophysics.section.data import SectionDataProvider
    layer = SectionDataProvider(st).layers(pid)[0]
    return layer.mesh.bounds()[:2]


def test_menu_entry_text(qgis_app, fake_iface):
    from groundwork_geophysics import classFactory
    plugin = classFactory(fake_iface)
    plugin.initGui()
    try:
        assert plugin.rename_action.text() == "Profile Properties…"
    finally:
        plugin.unload()


def test_rename_only(qgis_app, make_dialog, store_with_model, warnings_shown):
    st, p, _ = store_with_model
    before = st.station_sets(p.id)[0]
    dlg = make_dialog(st, p.id)
    assert not dlg.set_positions.isChecked() and dlg.spacing_edit.text() == ""
    dlg.name_edit.setText("Line A")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    assert st.profile(p.id).name == "Line A"
    assert "electrode_spacing" not in st.profile(p.id).metadata
    assert np.allclose(st.profile(p.id).xy, p.xy)
    after = st.station_sets(p.id)[0]
    assert after.id == before.id and np.allclose(after.xyz, before.xyz)


def test_duplicate_name_is_refused(qgis_app, make_dialog, store_with_model, warnings_shown):
    from groundwork_geophysics.core.model import Profile
    st, p, _ = store_with_model
    st.save_profile(Profile("p2", "Line B", p.xy + 100.0, st.crs_authid))
    dlg = make_dialog(st, p.id)
    dlg.name_edit.setText("line b")
    dlg.accept()
    assert dlg.result() == 0 and "already" in warnings_shown[-1]
    assert st.profile(p.id).name == p.name


def test_keep_line_attaches_positions_and_pins(qgis_app, make_dialog, drawn, warnings_shown):
    st, p = drawn
    unpinned = _bounds(st, p.id)
    dlg = make_dialog(st, p.id)
    assert dlg.set_combo.currentText() == "New set" and dlg.keep_line.isChecked()
    dlg.set_positions.setChecked(True)
    dlg.placement.set_positions_file(POSITIONS)
    dlg.spacing_edit.setText("5")
    qgis_app.processEvents()
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    assert np.allclose(st.profile(p.id).xy, p.xy)                  # the line is kept
    [s] = st.station_sets(p.id)
    assert s.numbers.tolist() == [1, 5, 10, 16, 20] and s.name == "Drawn" and s.method == "ert"
    assert st.profile(p.id).metadata["electrode_spacing"] == 5.0
    assert _bounds(st, p.id) != pytest.approx(unpinned)             # the model follows the survey


def test_keep_line_lists_points_off_the_line(qgis_app, make_dialog, drawn, monkeypatch):
    from groundwork_geophysics.ui import profile_actions
    st, p = drawn
    far = st.profile(p.id)
    far.xy = far.xy + np.array([0.0, 40.0])                       # the line lies 40 m away
    st.save_profile(far)
    asked = []
    answer = [False]
    monkeypatch.setattr(profile_actions, "confirm_off_line",
                        lambda parent, warnings: asked.append(list(warnings)) or answer[0])
    dlg = make_dialog(st, p.id)
    dlg.set_positions.setChecked(True)
    dlg.placement.set_positions_file(POSITIONS)
    dlg.accept()
    assert dlg.result() == 0 and "m off line" in asked[0][0] and st.station_sets(p.id) == []
    answer[0] = True
    dlg.accept()
    assert dlg.result() == 1 and len(st.station_sets(p.id)) == 1


def test_move_line_asks_first_and_cancel_changes_nothing(qgis_app, make_dialog, drawn,
                                                         monkeypatch, warnings_shown):
    from groundwork_geophysics.ui import profile_actions
    st, p = drawn
    asked = []
    answer = [False]
    monkeypatch.setattr(profile_actions, "confirm_move",
                        lambda parent, name, counts: asked.append((name, counts)) or answer[0])
    dlg = make_dialog(st, p.id)
    dlg.set_positions.setChecked(True)
    dlg.placement.set_positions_file(POSITIONS)
    dlg.move_line.setChecked(True)
    dlg.name_edit.setText("Renamed")
    dlg.accept()
    assert dlg.result() == 0 and asked[0][0] == "Drawn"
    assert st.profile(p.id).name == "Drawn" and np.allclose(st.profile(p.id).xy, p.xy)
    assert st.station_sets(p.id) == []
    answer[0] = True
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    moved = st.profile(p.id)
    assert moved.name == "Renamed" and len(moved.xy) == 5
    assert np.allclose(moved.xy[0], [437700.0, 5850700.0])
    [s] = st.station_sets(p.id)
    assert np.allclose(s.offset, 0.0, atol=1e-6)


def test_spacing_typed_on_a_0_8_profile_pins_it(qgis_app, make_dialog, store_with_model,
                                                warnings_shown):
    st, p, _ = store_with_model
    dlg = make_dialog(st, p.id)
    dlg.spacing_edit.setText("5")
    dlg.accept()
    assert dlg.result() == 1, warnings_shown
    assert st.profile(p.id).metadata["electrode_spacing"] == 5.0
    dlg = make_dialog(st, p.id)
    assert dlg.spacing_edit.text() == "5"                         # what is stored, no guess
    dlg.spacing_edit.setText("")
    dlg.accept()
    assert "electrode_spacing" not in st.profile(p.id).metadata
    dlg = make_dialog(st, p.id)
    dlg.spacing_edit.setText("-2")
    dlg.accept()
    assert dlg.result() == 0 and "greater than 0" in warnings_shown[-1]


def test_reference_height_button_applies_at_once(qgis_app, make_dialog, drawn, store_with_model):
    st, p = drawn
    dlg = make_dialog(st, p.id)
    assert dlg.reference_button.text() == "Reference Height…" and dlg.reference_button.isEnabled()
    dlg.ask_reference = lambda parent, electrodes, length, current: (10.0, 57.5)
    dlg.reference_button.click()
    assert st.profile(p.id).metadata["reference_height"] == {"s": 10.0, "z": 57.5}
    dlg.reject()                                                  # applied without OK
    assert st.profile(p.id).metadata["reference_height"]["z"] == 57.5
    st2, p2, _ = store_with_model                                 # a profile with real heights
    assert not make_dialog(st2, p2.id).reference_button.isEnabled()


def test_dialog_opens_at_its_content_and_does_not_shrink(qgis_app, make_dialog, drawn):
    dlg = make_dialog(drawn[0], drawn[1].id)
    closed = dlg.size()
    dlg.set_positions.setChecked(True)
    dlg.placement.set_positions_file(POSITIONS)
    qgis_app.processEvents()
    grown = dlg.size()
    assert grown.height() > closed.height() and grown.height() <= 580   # content, scrolls above that
    dlg.set_positions.setChecked(False)
    qgis_app.processEvents()
    assert dlg.size().height() == grown.height()


def test_a_failed_move_keeps_the_old_name_too(qgis_app, make_dialog, drawn, monkeypatch,
                                              warnings_shown):
    from groundwork_geophysics.ui import profile_actions
    st, p = drawn
    monkeypatch.setattr(profile_actions, "confirm_move", lambda parent, name, counts: True)
    dlg = make_dialog(st, p.id)
    dlg.set_positions.setChecked(True)
    dlg.placement.set_positions_file(POSITIONS)
    dlg.move_line.setChecked(True)
    dlg.name_edit.setText("Renamed")

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(st, "_write_station_set", boom)
    dlg.accept()
    assert dlg.result() == 0 and "disk full" in warnings_shown[-1]
    assert st.profile(p.id).name == "Drawn" and np.allclose(st.profile(p.id).xy, p.xy)


def test_a_failed_keep_line_save_keeps_the_old_name_too(qgis_app, make_dialog, drawn,
                                                        monkeypatch, warnings_shown):
    st, p = drawn
    dlg = make_dialog(st, p.id)
    dlg.set_positions.setChecked(True)
    dlg.placement.set_positions_file(POSITIONS)
    dlg.name_edit.setText("Renamed")

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(st, "_write_station_set", boom)
    dlg.accept()
    assert dlg.result() == 0 and st.profile(p.id).name == "Drawn"
    assert st.station_sets(p.id) == []


def test_a_failed_reference_height_is_shown_and_changes_nothing(qgis_app, make_dialog, drawn,
                                                                warnings_shown, monkeypatch):
    st, p = drawn

    def refuse():
        raise RuntimeError("attempt to write a readonly database")

    dlg = make_dialog(st, p.id)
    monkeypatch.setattr(st, "_tx", refuse)
    dlg.ask_reference = lambda parent, electrodes, length, current: (10.0, 57.5)
    dlg.reference_button.click()                                  # the slot does not raise
    assert "readonly" in warnings_shown[-1] and "reference height" in warnings_shown[-1]
    assert "reference_height" not in st.profile(p.id).metadata
    assert dlg.isVisible()


def test_a_refresh_failing_after_the_save_is_a_warning(qgis_app, fake_iface, make_dialog,
                                                       store_with_model, warnings_shown):
    st, p, _ = store_with_model
    dlg = make_dialog(st, p.id)

    def broken():
        raise RuntimeError("panel gone")

    dlg.provider.on_change.append(broken)
    dlg.name_edit.setText("Renamed")
    dlg.accept()
    assert dlg.result() == 1 and warnings_shown == []
    assert st.profile(p.id).name == "Renamed"
    assert dlg.last_warning == "Saved, but the view could not be refreshed: panel gone"
    assert any("panel gone" in i.text() for i in fake_iface.messageBar().items())


def test_the_fit_line_follows_the_spacing_and_positions(qgis_app, make_dialog, drawn,
                                                        store_with_model):
    """The same fit line as Add Data's, for what is being edited, live; nothing is saved."""
    from groundwork_geophysics.ui.fit_line import FIT_WARNING, WARNING_STYLE

    st, p = drawn
    dlg = make_dialog(st, p.id)
    assert not dlg.fit_label.isVisibleTo(dlg)            # no positions, no stations: nothing
    dlg.set_positions.setChecked(True)
    dlg.placement.set_positions_file(POSITIONS)
    dlg.spacing_edit.setText("5")
    qgis_app.processEvents()
    assert dlg.fit_label.isVisibleTo(dlg)
    assert dlg.fit_label.text().startswith("5 known points, largest shift")
    assert dlg.fit_label.styleSheet() == ""
    dlg.spacing_edit.setText("12")
    assert dlg.fit_label.styleSheet() == WARNING_STYLE
    assert dlg.fit_label.text().endswith(FIT_WARNING)
    assert st.station_sets(p.id) == []

    st2, p2, _ = store_with_model                         # stations 1 and 2, 50 m apart
    dlg = make_dialog(st2, p2.id)
    dlg.spacing_edit.setText("50")
    assert dlg.fit_label.text().startswith("2 known points, largest shift 0 m")
    assert dlg.fit_label.styleSheet() == ""
    dlg.spacing_edit.setText("5")
    assert dlg.fit_label.styleSheet() == WARNING_STYLE
    assert "electrode_spacing" not in st2.profile(p2.id).metadata
