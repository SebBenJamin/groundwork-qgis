"""A reference height shifts a local section (a profile without heights) to real elevations;
the interpretation drawn on it follows, and is re-hung once when real heights arrive."""
import numpy as np
import pytest

from groundwork_geophysics.core.interpretation import InterpFeature, InterpPiece, new_id
from groundwork_geophysics.core.model import attach_station_set, profile_from_polyline
from groundwork_geophysics.section.data import SectionDataProvider
from groundwork_geophysics.store.gpkg_store import ProjectStore

CRS = "EPSG:25832"
LINE = [(10.0, -3.0), (30.0, -3.0)]


def _local_store(tmp_path, piece=True):
    """A drawn profile D (0,0)-(60,0) without heights or models: a flat local section, and
    one line piece 3 m below its surface."""
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("D", CRS, np.array([[0.0, 0.0], [60.0, 0.0]]))
    st.save_profile(p)
    if piece:
        st.ensure_interpretation()
        v = st.current_version().id
        f = InterpFeature(new_id(), v, type="clay", name="A")
        st.save_feature(f)
        st.save_piece(InterpPiece(new_id(), v, f.id, p.id, "line", list(LINE)))
    return st, p


def _z(st, pid):
    [piece] = st.pieces(st.current_version().id, pid)
    return [z for _s, z in piece.vertices]


def _heights(st, p):
    """Attach a station set with elevations 100 .. 102 over the profile."""
    xyz = np.array([[0.0, 0.0, 100.0], [30.0, 0.0, 101.0], [60.0, 0.0, 102.0]])
    st.save_station_set(attach_station_set(st.profile(p.id), "S", "ert", xyz))


def test_reference_height_moves_pieces_and_undo_restores(qgis_app, fake_iface, tmp_path,
                                                          make_dock):
    st, p = _local_store(tmp_path, piece=False)
    dock = make_dock(st, fake_iface.mainWindow())
    dock.open_profile(p.id)
    dock.interp.form_factory = lambda f, s, names: f
    dock.interp._finished("line", list(LINE))           # drawn on the local section
    assert st.profile(p.id).metadata["local_pieces"] is True
    assert _z(st, p.id) == [-3.0, -3.0]
    dock.set_reference_height(20.0, 57.5)
    assert st.profile(p.id).metadata["reference_height"] == {"s": 20.0, "z": 57.5}
    assert _z(st, p.id) == [pytest.approx(54.5), pytest.approx(54.5)]
    with st._ds() as ds:
        zs = {round(pt[2], 6) for f in ds.GetLayerByName("interp_lines_3d")
              for pt in f.GetGeometryRef().GetPoints()}
    assert zs == {54.5}                                  # the 3D layers follow
    dock.set_reference_height(20.0, 57.5)                # the same again: no step
    assert dock.interp.undo.stack.count() == 2
    dock.interp.undo.stack.undo()
    assert "reference_height" not in st.profile(p.id).metadata
    assert _z(st, p.id) == [pytest.approx(-3.0), pytest.approx(-3.0)]
    dock.interp.undo.stack.redo()
    assert _z(st, p.id) == [pytest.approx(54.5), pytest.approx(54.5)]


def test_changing_the_reference_moves_by_the_difference(tmp_path):
    st, p = _local_store(tmp_path)
    provider = SectionDataProvider(st)
    assert provider.set_reference_height(p.id, 20.0, 57.5) == pytest.approx(57.5)
    assert _z(st, p.id) == [pytest.approx(54.5)] * 2
    assert provider.set_reference_height(p.id, 20.0, 60.0) == pytest.approx(2.5)
    assert _z(st, p.id) == [pytest.approx(57.0)] * 2
    assert provider.set_reference_height(p.id, 20.0, 60.0) == 0.0
    assert provider.set_reference_height(p.id, None, None) == pytest.approx(-60.0)
    assert _z(st, p.id) == [pytest.approx(-3.0)] * 2
    assert "reference_height" not in st.profile(p.id).metadata
    frozen = st.freeze_current("F")                      # frozen versions never move
    provider.set_reference_height(p.id, 20.0, 57.5)
    assert [z for _s, z in st.pieces(frozen.id, p.id)[0].vertices] == [-3.0, -3.0]


def test_settle_after_real_heights_arrive(tmp_path):
    st, p = _local_store(tmp_path)
    profile = st.profile(p.id)
    profile.metadata["local_pieces"] = True
    st.save_profile(profile)
    provider = SectionDataProvider(st)
    assert not provider.settle_local_interpretation(p.id)     # still local: nothing to do
    _heights(st, p)
    assert provider.surface(p.id).kind == "stations"
    assert provider.settle_local_interpretation(p.id)
    surface = np.interp([10.0, 30.0], [0.0, 30.0, 60.0], [100.0, 101.0, 102.0])
    assert _z(st, p.id) == pytest.approx((surface - 3.0).tolist())
    assert "local_pieces" not in st.profile(p.id).metadata
    assert not provider.settle_local_interpretation(p.id)     # once only


def test_settle_starts_from_the_referenced_local_surface(tmp_path):
    st, p = _local_store(tmp_path)
    provider = SectionDataProvider(st)
    provider.set_reference_height(p.id, 20.0, 57.5)           # piece now at 54.5
    profile = st.profile(p.id)
    profile.metadata["local_pieces"] = True
    st.save_profile(profile)
    _heights(st, p)
    assert provider.settle_local_interpretation(p.id)
    surface = np.interp([10.0, 30.0], [0.0, 30.0, 60.0], [100.0, 101.0, 102.0])
    assert _z(st, p.id) == pytest.approx((surface - 3.0).tolist())


def test_local_switch_state(qgis_app, tmp_path, make_dock):
    st, p = _local_store(tmp_path, piece=False)
    dock = make_dock(st)
    dock.open_profile(p.id)
    combo, button = dock.topo_combo, dock.topo.reference_button
    assert [combo.itemData(i) for i in range(combo.count())] == ["stations", "dem", "local"]
    assert combo.currentText() == "Local" and combo.currentData() == "local"
    assert [combo.model().item(i).isEnabled() for i in range(3)] == [False, False, True]
    assert button.isEnabled() and button.text() == "Reference Height…"
    _heights(st, p)
    dock.provider.notify_changed()
    qgis_app.processEvents()
    assert combo.currentData() == "stations"
    assert not combo.model().item(2).isEnabled() and combo.view().isRowHidden(2)
    assert not button.isEnabled() and button.toolTip()


def test_dock_settles_on_open_and_says_so(qgis_app, tmp_path, make_dock):
    st, p = _local_store(tmp_path)
    profile = st.profile(p.id)
    profile.metadata["local_pieces"] = True
    st.save_profile(profile)
    _heights(st, p)
    dock = make_dock(st)
    dock.open_profile(p.id)
    assert dock.readout.text() == "Interpretation on D moved onto the real surface: 1 piece(s)"
    assert _z(st, p.id)[0] == pytest.approx(np.interp(10.0, [0, 30], [100, 101]) - 3.0)


def test_reference_button_asks_and_sets(qgis_app, tmp_path, make_dock):
    st, p = _local_store(tmp_path)
    dock = make_dock(st)
    dock.open_profile(p.id)
    asked = []
    dock.topo.ask_reference = lambda parent, electrodes, length, current: (
        asked.append((electrodes, length, current)), (20.0, 57.5))[1]
    dock.topo.reference_button.click()
    assert asked == [(None, pytest.approx(60.0), None)]
    assert _z(st, p.id) == [pytest.approx(54.5)] * 2
    dock.topo.ask_reference = lambda *a: False                # "Remove"
    dock.topo.reference_button.click()
    assert _z(st, p.id) == [pytest.approx(-3.0)] * 2
    dock.topo.ask_reference = lambda *a: None                 # cancel: nothing changes
    dock.topo.reference_button.click()
    assert dock.interp.undo.stack.count() == 2


def test_reference_height_dialog(qgis_app):
    from qgis.PyQt.QtWidgets import QDialogButtonBox

    from groundwork_geophysics.core.layout import Electrodes
    from groundwork_geophysics.ui.reference_height_dialog import ReferenceHeightDialog
    electrodes = Electrodes(np.arange(1, 13), np.arange(12) * 5.0, "spacing")
    dlg = ReferenceHeightDialog(electrodes, 60.0, None)
    assert dlg.windowTitle() == "Reference Height" and dlg.remove_button is None
    ok = dlg.buttons.button(QDialogButtonBox.StandardButton.Ok)
    assert not ok.isEnabled()                             # no height typed yet
    dlg.electrode.setValue(5)
    dlg.height_edit.setText("57,5")
    assert ok.isEnabled() and dlg.value() == (20.0, 57.5)
    dlg.by_distance.setChecked(True)
    dlg.distance_edit.setText("61")
    assert not ok.isEnabled() and dlg.message.text()      # beyond the profile
    dlg.distance_edit.setText("12.5")
    assert ok.isEnabled() and dlg.value() == (12.5, 57.5)
    dlg.deleteLater()
    dlg = ReferenceHeightDialog(None, 60.0, {"s": 20.0, "z": 57.5})
    assert dlg.remove_button is not None and dlg.value() == (20.0, 57.5)
    assert dlg.by_electrode.isHidden() and dlg.by_distance.isChecked()
    dlg.deleteLater()


def test_export_settles_profiles_that_gained_heights(qgis_app, tmp_path, make_dock):
    from osgeo import ogr
    st, p = _local_store(tmp_path)                          # L: piece 3 m below flat 0
    profile = st.profile(p.id)
    profile.metadata["local_pieces"] = True
    st.save_profile(profile)
    other = profile_from_polyline("M", CRS, np.array([[0.0, 50.0], [60.0, 50.0]]))
    st.save_profile(other)
    dock = make_dock(st)
    dock.open_profile(other.id)                             # L is not open
    _heights(st, p)                                         # L gains station heights
    ctl = dock.interp
    out = tmp_path / "out.gpkg"
    ctl.ask_path = lambda: str(out)
    said = []
    ctl.info = said.append
    assert ctl.export() == 1
    assert "local_pieces" not in st.profile(p.id).metadata
    with ogr.ExceptionMgr():
        ds = ogr.Open(str(out))
        zs = [pt[2] for f in ds.GetLayerByName("lines_3d")
              for pt in f.GetGeometryRef().GetPoints()]
        ds = None
    surface = np.interp([10.0, 30.0], [0.0, 30.0, 60.0], [100.0, 101.0, 102.0])
    assert zs == pytest.approx((surface - 3.0).tolist())
    assert "no heights" not in said[0]


def test_reference_shift_marks_pieces_for_settling(tmp_path):
    st, p = _local_store(tmp_path)                          # a piece, no "local_pieces"
    assert "local_pieces" not in st.profile(p.id).metadata
    SectionDataProvider(st).set_reference_height(p.id, 20.0, 57.5)
    assert st.profile(p.id).metadata["local_pieces"] is True


# -- store errors never leave a slot or an undo step (fix wave, I3) -------------------------
def _read_only(st, monkeypatch):
    """Every write transaction of ``st`` fails as GDAL does on a locked or read-only file."""
    def refuse():
        raise RuntimeError("attempt to write a readonly database")
    monkeypatch.setattr(st, "_tx", refuse)


def test_a_failed_reference_height_changes_nothing_and_says_so(qgis_app, tmp_path, make_dock,
                                                               monkeypatch):
    st, p = _local_store(tmp_path)
    dock = make_dock(st)
    dock.open_profile(p.id)
    _read_only(st, monkeypatch)
    dock.topo.ask_reference = lambda *a: (20.0, 57.5)
    dock.topo.reference_button.click()                      # the slot does not raise
    assert "readonly" in dock.readout.text() and "reference height" in dock.readout.text()
    assert "reference_height" not in st.profile(p.id).metadata
    assert _z(st, p.id) == [-3.0, -3.0]
    stack = dock.interp.undo.stack
    assert stack.count() == 0 and not stack.canUndo() and not stack.canRedo()


def test_a_failed_undo_of_a_reference_height_leaves_no_false_step(qgis_app, tmp_path,
                                                                  make_dock, monkeypatch):
    st, p = _local_store(tmp_path)
    dock = make_dock(st)
    dock.open_profile(p.id)
    dock.set_reference_height(20.0, 57.5)
    stack = dock.interp.undo.stack
    assert stack.count() == 1
    _read_only(st, monkeypatch)
    stack.undo()                                            # cannot write: nothing undone
    assert "readonly" in dock.readout.text()
    assert st.profile(p.id).metadata["reference_height"] == {"s": 20.0, "z": 57.5}
    assert _z(st, p.id) == [pytest.approx(54.5)] * 2
    assert not stack.canRedo()                              # no step claims it was undone


def test_a_failed_settle_does_not_break_the_refresh(qgis_app, tmp_path, make_dock,
                                                    monkeypatch):
    st, p = _local_store(tmp_path)
    profile = st.profile(p.id)
    profile.metadata["local_pieces"] = True
    st.save_profile(profile)
    _heights(st, p)
    _read_only(st, monkeypatch)
    dock = make_dock(st)
    assert dock.open_profile(p.id)                          # opens; the settle failed
    assert "readonly" in dock.readout.text() and "D" in dock.readout.text()
    assert st.profile(p.id).metadata["local_pieces"] is True
    assert _z(st, p.id) == [-3.0, -3.0]
    dock.provider.notify_changed()
    dock._refresh_now()                                     # a refresh says it again
    assert "readonly" in dock.readout.text()


def test_a_failed_settle_before_export_stops_the_export(qgis_app, tmp_path, make_dock,
                                                        monkeypatch):
    st, p = _local_store(tmp_path)
    profile = st.profile(p.id)
    profile.metadata["local_pieces"] = True
    st.save_profile(profile)
    other = profile_from_polyline("M", CRS, np.array([[0.0, 50.0], [60.0, 50.0]]))
    st.save_profile(other)
    dock = make_dock(st)
    dock.open_profile(other.id)
    _heights(st, p)
    _read_only(st, monkeypatch)
    ctl = dock.interp
    out = tmp_path / "out.gpkg"
    ctl.ask_path = lambda: str(out)
    said = []
    ctl.info = said.append
    assert ctl.export() == 0
    assert said and said[-1].startswith("Export failed") and "readonly" in said[-1]
    assert not out.exists() and st.profile(p.id).metadata["local_pieces"] is True


def test_the_view_follows_a_reference_height(qgis_app, tmp_path, make_dock):
    """Set or removed (also by undo), the section zooms to its full extent, so the data
    moved to real elevations stay in view."""
    st, p = _local_store(tmp_path)
    dock = make_dock(st)
    dock.open_profile(p.id)

    def shown(z):
        e = dock.canvas.visibleElevationRange()
        return e.lower() <= z <= e.upper()

    assert shown(0.0) and not shown(57.5)                # the flat local surface
    dock.set_reference_height(20.0, 57.5)
    assert shown(57.5) and not shown(0.0)
    dock.interp.undo.stack.undo()
    assert shown(0.0) and not shown(57.5)
