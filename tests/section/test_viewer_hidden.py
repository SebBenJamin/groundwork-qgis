"""Round 2, F4: the borehole viewer still shows boreholes hidden in the section, faded and
marked; select columns (Ctrl+click for several), right-click to hide or show them."""
import pytest
from qgis.PyQt.QtCore import QPointF, Qt

from test_borehole_viewer import _bh, fake_dock  # noqa: F401


@pytest.fixture
def viewer(fake_dock, qgis_app):  # noqa: F811
    from qgis.core import QgsProject

    from geophysics_workbench.core.context import ContextItems
    from geophysics_workbench.section.borehole_viewer import BoreholeViewer
    fake_dock.provider.items["p1"] = ContextItems(points=[
        _bh(10.0, "RK15", 25.0, [(0, 2, "sand", (200, 20, 20))], bid="RK15", layer_id="L1"),
        _bh(40.0, "RK16", 25.0, [(0, 2, "sand", (200, 20, 20))], bid="RK16", layer_id="L1"),
        _bh(70.0, "RK17", 25.0, [(0, 2, "sand", (200, 20, 20))], bid="RK17", layer_id="L1")])
    v = BoreholeViewer(fake_dock, QgsProject.instance())
    v.resize(900, 600)
    v.show_profile("p1")
    v.show()
    qgis_app.processEvents()
    yield v
    v.close()
    v.deleteLater()


def _rects(v):
    v.canvas.render_image()
    return {p.label: r for p, r in v.canvas.column_rects}


def _click(v, label, ctrl=False):
    v.canvas.click_at(_rects(v)[label].center(), ctrl)


def test_hidden_drawn_faded(viewer):
    viewer.dock.provider.set_boreholes_hidden("p1", [("L1", "RK16")], True)
    img = viewer.canvas.render_image()
    rects = {p.label: r for p, r in viewer.canvas.column_rects}
    assert set(rects) == {"RK15", "RK16", "RK17"}            # still in the viewer

    def green(label):
        r = rects[label]
        return img.pixelColor(int(r.center().x()), int(r.center().y())).green()
    assert green("RK16") > green("RK15") + 60                 # sand faded towards white
    lines = viewer.canvas._label_lines(viewer.boreholes[1], 25.0)
    assert lines[-1] == "hidden in section"
    assert "hidden in section" not in viewer.canvas._label_lines(viewer.boreholes[0], 25.0)


def test_ctrl_click_selects_several(viewer):
    _click(viewer, "RK15")
    assert viewer.selected == {("L1", "RK15")}
    _click(viewer, "RK17", ctrl=True)
    assert viewer.selected == {("L1", "RK15"), ("L1", "RK17")}
    _click(viewer, "RK15", ctrl=True)
    assert viewer.selected == {("L1", "RK17")}
    viewer.canvas.click_at(QPointF(5.0, 5.0), False)             # empty space
    assert viewer.selected == set()


def test_menu_hides_selection(viewer):
    from geophysics_workbench.section.dock import HIDE_IN_SECTION
    _click(viewer, "RK15")
    _click(viewer, "RK17", ctrl=True)
    menu = viewer.canvas.column_menu(_rects(viewer)["RK17"].center())
    [hide] = [a for a in menu.actions() if a.text() == HIDE_IN_SECTION]
    hide.trigger()
    assert viewer.dock.provider.hidden_keys("p1") == {("L1", "RK15"), ("L1", "RK17")}
    assert [p.label for p in viewer.dock.provider.context("p1").points] == ["RK16"]


def test_menu_on_unselected_column_acts_on_it_alone(viewer):
    from geophysics_workbench.section.dock import HIDE_IN_SECTION
    _click(viewer, "RK15")
    menu = viewer.canvas.column_menu(_rects(viewer)["RK16"].center())
    [hide] = [a for a in menu.actions() if a.text() == HIDE_IN_SECTION]
    hide.trigger()
    assert viewer.dock.provider.hidden_keys("p1") == {("L1", "RK16")}


def test_menu_shows_hidden(viewer):
    from geophysics_workbench.section.dock import HIDE_IN_SECTION, SHOW_IN_SECTION
    viewer.dock.provider.set_boreholes_hidden("p1", [("L1", "RK16")], True)
    menu = viewer.canvas.column_menu(_rects(viewer)["RK16"].center())
    assert [a.text() for a in menu.actions()] == [SHOW_IN_SECTION]
    menu.actions()[0].trigger()
    assert viewer.dock.provider.hidden_keys("p1") == set()
    menu = viewer.canvas.column_menu(_rects(viewer)["RK16"].center())
    assert [a.text() for a in menu.actions()] == [HIDE_IN_SECTION]
    assert viewer.canvas.column_menu(QPointF(5.0, 5.0)) is None


def test_option_hides_hidden_columns(viewer):
    viewer.dock.provider.set_boreholes_hidden("p1", [("L1", "RK16")], True)
    viewer.show_check["hidden"].setChecked(False)
    assert [p.label for p in viewer.boreholes] == ["RK15", "RK17"]
    assert viewer.show_check["hidden"].text() == "Hidden boreholes"


def test_option_persisted(viewer):
    viewer.show_check["hidden"].setChecked(False)
    assert viewer.options()["show"]["hidden"] is False
