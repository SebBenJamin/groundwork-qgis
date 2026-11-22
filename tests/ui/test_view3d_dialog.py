"""Show in 3D…: one tick per model and per profile's boreholes, following the saved choice."""
import shutil
from pathlib import Path

import numpy as np
import pytest

from groundwork_geophysics.core.model import Dataset, file_fingerprint, profile_from_polyline
from groundwork_geophysics.store.gpkg_store import ProjectStore

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CRS = "EPSG:25832"


@pytest.fixture
def store(qgis_app, tmp_path):
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    for name in ("P1", "P2"):
        p = profile_from_polyline(name, CRS, np.array([[0.0, 0.0], [60.0, 0.0]]))
        p.id = name.lower()
        st.save_profile(p)
    src = tmp_path / "m.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("m1", "p1", "", "ert_model", str(src), mt, sha, "r2_res_dat",
                            {"z_kind": "elevation"}, {}, name="Model one"))
    st.save_dataset(Dataset("r1", "p1", "", "ert_measured", str(src), mt, sha, "r2_res_dat",
                            {}, {}, name="Readings"))
    return st


def _items(dialog):
    from qgis.PyQt.QtCore import Qt
    tree = dialog.tree
    out = {}
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        out[top.text(0)] = {top.child(k).text(0): top.child(k).checkState(0) == Qt.CheckState.Checked
                            for k in range(top.childCount())}
    return out


def test_profiles_list_their_models_and_boreholes_but_not_measured_data(store):
    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    d = View3dDialog(store, Choice())
    assert _items(d) == {"P1": {"Model one": False, "Boreholes": False},
                         "P2": {"Boreholes": False}}


def test_ticks_follow_the_choice_and_give_it_back(store):
    from qgis.PyQt.QtCore import Qt

    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    d = View3dDialog(store, Choice(frozenset({"m1", "gone"}), frozenset({"p2"})))
    assert _items(d)["P1"]["Model one"] and _items(d)["P2"]["Boreholes"]
    assert d.choice() == Choice(frozenset({"m1"}), frozenset({"p2"}))
    d.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)     # the whole of P1
    assert d.choice() == Choice(frozenset({"m1"}), frozenset({"p1", "p2"}))
    d.tree.topLevelItem(1).setCheckState(0, Qt.CheckState.Unchecked)
    assert d.choice() == Choice(frozenset({"m1"}), frozenset({"p1"}))


def test_a_profile_with_some_ticks_is_partly_checked(store):
    from qgis.PyQt.QtCore import Qt

    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    d = View3dDialog(store, Choice(frozenset({"m1"}), frozenset()))
    assert d.tree.topLevelItem(0).checkState(0) == Qt.CheckState.PartiallyChecked


def test_the_dialog_has_ok_cancel_and_help(store):
    from qgis.PyQt.QtWidgets import QDialogButtonBox

    from groundwork_geophysics.ui.view3d_dialog import TITLE, View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    d = View3dDialog(store, Choice())
    assert d.windowTitle() == TITLE == "Show in 3D"
    box = d.findChild(QDialogButtonBox)
    for b in (QDialogButtonBox.StandardButton.Ok, QDialogButtonBox.StandardButton.Cancel,
              QDialogButtonBox.StandardButton.Help):
        assert box.button(b) is not None


def test_the_menu_entry_waits_for_a_groundwork_project(qgis_app, fake_iface):
    from groundwork_geophysics.plugin import WorkbenchPlugin
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        action = next(a for a in plugin.actions if a.text() == "Show in 3D…")
        assert not action.isEnabled()
        assert "Groundwork project" in action.toolTip()
    finally:
        plugin.unload()


def test_a_profile_without_real_heights_says_why_it_cannot_be_shown(store):
    from groundwork_geophysics.ui.view3d_dialog import LOCAL_TIP, View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    d = View3dDialog(store, Choice(), local={"p2"})
    p1, p2 = d.tree.topLevelItem(0), d.tree.topLevelItem(1)
    assert p1.flags() & p1.flags().ItemIsEnabled
    assert not p2.flags() & p2.flags().ItemIsEnabled
    assert p2.toolTip(0) == LOCAL_TIP and "reference height" in LOCAL_TIP.lower()


def _combo(dialog, dataset_id):
    from groundwork_geophysics.ui.view3d_dialog import _ID
    tree = dialog.tree
    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        for k in range(top.childCount()):
            if top.child(k).data(0, _ID) == dataset_id:
                return tree.itemWidget(top.child(k), 1)
    return None


def test_each_model_has_its_representation_and_boreholes_none(store):
    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    dialog = View3dDialog(store, Choice(frozenset({"m1"}), frozenset(), {"m1": "picture"}))
    combo = _combo(dialog, "m1")
    assert [combo.itemText(i) for i in range(combo.count())] == [
        "As in the Section", "Point Cloud", "Section Picture"]
    assert combo.currentData() == "picture" and combo.toolTip()
    assert all(combo.itemData(i, 3) for i in range(combo.count()))      # a tooltip each
    assert dialog.choice().looks == {"m1": "picture"}
    combo.setCurrentIndex(combo.findData("cloud"))
    assert dialog.choice().looks == {"m1": "cloud"}
    combo.setCurrentIndex(combo.findData("section"))
    assert dialog.choice() == Choice(frozenset({"m1"}))
    assert _combo(dialog, "p1") is None                                   # Boreholes
    assert _combo(View3dDialog(store, Choice()), "m1").currentData() == "section"
    assert not dialog.tree.isHeaderHidden()


def test_a_local_profiles_representation_is_disabled_too(store):
    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    assert not _combo(View3dDialog(store, Choice(), local={"p1"}), "m1").isEnabled()


def test_pictures_show_the_interpretation_when_ticked(store):
    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    dialog = View3dDialog(store, Choice())
    assert not dialog.interpretation.isChecked() and dialog.interpretation.toolTip()
    dialog.interpretation.setChecked(True)
    assert dialog.choice().interpretation
    assert View3dDialog(store, Choice(interpretation=True)).interpretation.isChecked()


def test_sizes_are_auto_or_metres_and_say_the_auto_value(store):
    from qgis.PyQt.QtCore import QLocale

    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import (Choice, auto_borehole_width,
                                                        auto_station_size)
    dialog = View3dDialog(store, Choice())
    assert dialog.sizes.isCollapsed()
    for spin, auto in ((dialog.borehole_width, auto_borehole_width(store)),
                       (dialog.station_size, auto_station_size(store))):
        assert spin.text() == "Auto" and spin.suffix() == " m"
        assert f"Auto: {QLocale().toString(auto, 'f', 2)} m" in spin.toolTip()
    assert dialog.choice().borehole_width is None and dialog.choice().station_size is None
    dialog.borehole_width.setValue(1.5)
    dialog.station_size.setValue(0.25)
    choice = dialog.choice()
    assert (choice.borehole_width, choice.station_size) == (1.5, 0.25)
    again = View3dDialog(store, choice)
    assert (again.borehole_width.value(), again.station_size.value()) == (1.5, 0.25)
    again.borehole_width.clear()                                   # back to Auto
    assert again.choice().borehole_width is None


def test_restyling_the_interpretation_is_asked_for_each_time(store):
    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    dialog = View3dDialog(store, Choice())
    assert not dialog.restyle_interpretation() and dialog.restyle.toolTip()
    dialog.restyle.setChecked(True)
    assert dialog.restyle_interpretation()


def test_the_dialog_fits_a_laptop_screen(store):
    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    dialog = View3dDialog(store, Choice())
    hint = dialog.sizeHint()
    assert hint.height() <= 580 and hint.width() <= 1000


def test_select_all_and_deselect_all(store):
    from qgis.PyQt.QtCore import Qt

    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    dialog = View3dDialog(store, Choice(), local={"p2"})
    dialog.select_all.click()
    chosen = dialog.choice()
    assert chosen.models == {"m1"} and chosen.boreholes == {"p1"}   # P2 has no heights
    dialog.deselect_all.click()
    assert dialog.choice().models == frozenset() and dialog.choice().boreholes == frozenset()
    assert all(dialog.tree.topLevelItem(i).checkState(0) == Qt.CheckState.Unchecked
               for i in range(dialog.tree.topLevelItemCount()))
