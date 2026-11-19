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


def test_the_look_is_offered_and_kept(store):
    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    dialog = View3dDialog(store, Choice(frozenset({"m1"}), frozenset(), "pictures"))
    assert dialog.pictures.isChecked() and not dialog.layers.isChecked()
    assert dialog.choice().look == "pictures"
    dialog.layers.setChecked(True)
    assert dialog.choice() == Choice(frozenset({"m1"}), frozenset(), "layers")
    assert View3dDialog(store, Choice()).layers.isChecked()
