"""The borehole viewer window: the current profile's boreholes side by side."""
import numpy as np
import pytest

from test_context_render import _close


class _Profile:
    def __init__(self, pid, name):
        self.id, self.name = pid, name


def _bh(s, label, z_top, intervals, entry=0, **kw):
    from geophysics_workbench.core.context import LogInterval, ProjectedPoint
    from geophysics_workbench.section.borehole_style import default_symbol
    log = []
    for top, bottom, text, rgb in intervals:
        sym = default_symbol(text)
        if rgb is not None:
            from qgis.PyQt.QtGui import QColor
            sym.setColor(QColor(*rgb))
        log.append(LogInterval(top, bottom, text, sym))
    return ProjectedPoint(s, 1.0, label, "borehole", z_top, log, entry=entry, **kw)


@pytest.fixture
def fake_dock(qgis_app):
    from qgis.PyQt.QtCore import QObject, pyqtSignal

    from geophysics_workbench.core.context import ContextItems, ProjectedPoint

    class Provider:
        def __init__(self):
            self.on_change = []
            self.items = {
                "p1": ContextItems(points=[
                    _bh(10.0, "RK15", 25.0, [(0, 2, "sand", (200, 20, 20))]),
                    _bh(40.0, "RK16", 24.0, [(0, 3, "clay", (20, 20, 200))], entry=1),
                    _bh(80.0, "RK19", None, [(0, 1, "peat", None)]),
                    ProjectedPoint(50.0, 0.0, "pylon", "point")]),
                "p2": ContextItems(points=[_bh(5.0, "X1", 30.0, [(0, 1, "a", None)])])}
            self.changed = 0

        def context(self, pid):
            return self.items.get(pid)

        def topography(self, pid):
            return None

        def notify_changed(self):
            self.changed += 1

        def set_borehole_views(self, views):
            self.views = views

    class Dock(QObject):
        profile_changed = pyqtSignal(object)

        def __init__(self):
            super().__init__()
            self.provider = Provider()
            self.profile = _Profile("p1", "Transect 3")

        def current_profile(self):
            return self.profile

    return Dock()


@pytest.fixture
def viewer(fake_dock, qgis_app):
    from qgis.core import QgsProject

    from geophysics_workbench.section.borehole_viewer import BoreholeViewer
    v = BoreholeViewer(fake_dock, QgsProject.instance())
    v.resize(900, 600)
    v.show_profile("p1", (1, "RK16"))
    v.show()
    qgis_app.processEvents()
    yield v
    v.close()
    v.deleteLater()


def test_viewer_lists_every_borehole_entry_of_the_profile(viewer):
    assert [p.label for p in viewer.boreholes] == ["RK15", "RK16", "RK19"]   # no pylon
    assert "Transect 3" in viewer.windowTitle()


def test_heightless_borehole_listed_not_drawn_in_elevation(viewer):
    viewer.set_axis("elevation")
    viewer.canvas.render_image()
    drawn = [p.label for p, _r in viewer.canvas.column_rects]
    assert drawn == ["RK15", "RK16"] and "RK19" in viewer.status.text()
    viewer.set_axis("depth")
    viewer.canvas.render_image()
    assert [p.label for p, _r in viewer.canvas.column_rects] == ["RK15", "RK16", "RK19"]


def test_highlighted_borehole_drawn_with_frame(viewer):
    from geophysics_workbench.section.borehole_draw import HIGHLIGHT_RGB
    img = viewer.canvas.render_image()
    rect = dict((p.label, r) for p, r in viewer.canvas.column_rects)["RK16"]
    y = int(rect.center().y())
    edge = [img.pixel(int(rect.left()) - 1 + dx, y) for dx in range(3)]
    assert any(_close(px, HIGHLIGHT_RGB, tol=40) for px in edge)


def test_mode_switch_changes_column_x_positions(viewer):
    viewer.set_mode("even")
    viewer.canvas.render_image()
    even = [r.center().x() for _p, r in viewer.canvas.column_rects]
    gaps = np.diff(even)
    assert np.allclose(gaps, gaps[0], atol=1.0)                    # equal spacing
    viewer.set_axis("depth")                                       # all three drawn
    viewer.set_mode("true")
    viewer.canvas.render_image()
    true = [r.center().x() for _p, r in viewer.canvas.column_rects]
    # chainages 10, 40, 80: gaps in the ratio 30 : 40
    assert (true[1] - true[0]) / (true[2] - true[1]) == pytest.approx(0.75, rel=0.01)


def test_depth_axis_hangs_all_columns_from_zero(viewer):
    viewer.set_axis("depth")
    viewer.canvas.render_image()
    tops = {round(r.top()) for _p, r in viewer.canvas.column_rects}
    assert len(tops) == 1


def test_elevation_axis_puts_columns_at_their_collar(viewer):
    viewer.set_axis("elevation")
    viewer.canvas.render_image()
    rects = dict((p.label, r) for p, r in viewer.canvas.column_rects)
    assert rects["RK15"].top() < rects["RK16"].top()                  # 25 m above 24 m


def test_no_correlation_lines_between_columns(viewer):
    viewer.set_mode("even")
    img = viewer.canvas.render_image()
    rects = [r for _p, r in viewer.canvas.column_rects]
    a, b = rects[0], rects[1]
    y = int((max(a.top(), b.top()) + min(a.bottom(), b.bottom())) / 2)
    gap = [img.pixel(x, y) for x in range(int(a.right()) + 3, int(b.left()) - 3)]
    assert gap and all(px == 0xFFFFFFFF for px in gap)


def test_follows_section_profile_change(viewer, fake_dock, qgis_app):
    fake_dock.profile = _Profile("p2", "Transect 4")
    fake_dock.profile_changed.emit("p2")
    qgis_app.processEvents()
    assert [p.label for p in viewer.boreholes] == ["X1"]
    assert "Transect 4" in viewer.windowTitle()


def test_refreshes_on_provider_change(viewer, fake_dock):
    fake_dock.provider.items["p1"].points.pop(0)
    for cb in list(fake_dock.provider.on_change):
        cb()
    assert [p.label for p in viewer.boreholes] == ["RK16", "RK19"]


def test_readout_names_borehole_depth_and_interval(viewer):
    viewer.set_axis("elevation")
    viewer.canvas.render_image()
    rect = dict((p.label, r) for p, r in viewer.canvas.column_rects)["RK15"]
    lines = viewer.canvas.readout_text(rect.center().x(), rect.top() + rect.height() * 0.25)
    assert lines[0].startswith("RK15") and any("sand" in ln for ln in lines)


def test_options_round_trip_through_project(viewer, fake_dock):
    from qgis.core import QgsProject

    from geophysics_workbench.section.borehole_viewer import BoreholeViewer
    viewer.set_mode("even")
    viewer.set_axis("depth")
    viewer.show_check["ticks"].setChecked(True)
    viewer.save_options()
    other = BoreholeViewer(fake_dock, QgsProject.instance())
    assert (other.mode, other.axis) == ("even", "depth")
    assert other.show_check["ticks"].isChecked()
    other.deleteLater()


def test_ve_spin_only_in_true_distance(viewer):
    viewer.set_mode("even")
    assert not viewer.ve_spin.isEnabled()
    viewer.set_mode("true")
    assert viewer.ve_spin.isEnabled()


def test_curve_style_dialog_saves_and_calls_back(qgis_app):
    from qgis.core import QgsProject

    from geophysics_workbench.section.borehole_style import curve_styles
    from geophysics_workbench.ui.curve_style_dialog import CurveStyleDialog
    calls = []
    dlg = CurveStyleDialog(QgsProject.instance(), {"t:gr": "gr API"}, lambda: calls.append(1))
    row = dlg.rows["t:gr"]
    row.log.setChecked(True)
    row.vmin.setText("1")
    row.vmax.setText("1000")
    row.fill.setCurrentText("left")
    dlg.accept()
    s = curve_styles(QgsProject.instance())["t:gr"]
    assert (s.log, s.vmin, s.vmax, s.fill) == (True, 1.0, 1000.0, "left")
    assert len(s.fill_colour) == 9 and calls == [1]


# -- the viewer is the one place for how boreholes look (the section follows) ------------
def _two_entries(project):
    from geophysics_workbench.core.context_settings import (BoreholeSetting, ContextSettings,
                                                            CurveField, CurveTableSetting)
    from geophysics_workbench.ui.context_dialog import write_settings
    write_settings(project, ContextSettings(boreholes=[
        BoreholeSetting("cores", "id", curve_tables=[CurveTableSetting(
            "t", "id", "d", [CurveField("gr", "API")])]),
        BoreholeSetting("state", "name")]))


def _curve_bh(qgis_app, fake_dock):
    from geophysics_workbench.core.context import Curve
    p = fake_dock.provider.items["p1"].points[0]
    p.curves = [Curve("t:gr", "gr", "API", np.array([0.0, 2.0]), np.array([10.0, 90.0]))]


def test_viewer_layer_text_and_curves_reach_the_section_settings(fake_dock, qgis_app):
    from qgis.core import QgsProject

    from geophysics_workbench.section.borehole_viewer import BoreholeViewer
    from geophysics_workbench.ui.context_dialog import read_settings
    prj = QgsProject.instance()
    _two_entries(prj)
    _curve_bh(qgis_app, fake_dock)
    v = BoreholeViewer(fake_dock, prj)
    v.show_profile("p1")
    before = fake_dock.provider.changed
    v.show_check["text"].setChecked(True)
    v.curve_check("t:gr").setChecked(True)
    v.column_spin.setValue(24)
    v.opacity_spin.setValue(0.6)
    cores, state = read_settings(prj).boreholes
    assert cores.layer_text and state.layer_text
    assert cores.section_curves == ["t:gr"] and state.section_curves == []   # only its table
    assert (cores.column_px, state.column_px) == (24, 24)
    assert cores.opacity == pytest.approx(0.6)
    # the section redraws from the new look without gathering everything again (I4)
    assert fake_dock.provider.changed == before
    assert fake_dock.provider.views[0].column_px == 24 and fake_dock.provider.views[0].layer_text
    v.deleteLater()


def test_viewer_starts_from_the_section_settings(fake_dock, qgis_app):
    from qgis.core import QgsProject

    from geophysics_workbench.section.borehole_viewer import BoreholeViewer
    from geophysics_workbench.ui.context_dialog import read_settings, write_settings
    prj = QgsProject.instance()
    _two_entries(prj)
    s = read_settings(prj)
    s.boreholes[0].layer_text, s.boreholes[0].section_curves = True, ["t:gr"]
    s.boreholes[0].column_px = 30
    write_settings(prj, s)
    _curve_bh(qgis_app, fake_dock)
    v = BoreholeViewer(fake_dock, prj)
    v.show_profile("p1")
    assert v.show_check["text"].isChecked() and v.curve_check("t:gr").isChecked()
    assert v.column_spin.value() == 30
    v.deleteLater()



def test_section_curves_of_other_profiles_are_kept(fake_dock, qgis_app):
    """I3: a curve ticked for the section stays ticked when the look is changed while a
    profile without that curve is shown."""
    from qgis.core import QgsProject

    from geophysics_workbench.core.context_settings import CurveField, CurveTableSetting
    from geophysics_workbench.section.borehole_viewer import BoreholeViewer
    from geophysics_workbench.ui.context_dialog import read_settings, write_settings
    prj = QgsProject.instance()
    _two_entries(prj)
    s = read_settings(prj)
    s.boreholes[0].curve_tables = [CurveTableSetting("t", "id", "d", [CurveField("gr"),
                                                                     CurveField("res")])]
    s.boreholes[0].section_curves = ["t:res"]
    write_settings(prj, s)
    _curve_bh(qgis_app, fake_dock)                     # this profile only has "gr"
    v = BoreholeViewer(fake_dock, prj)
    v.show_profile("p1")
    v.column_spin.setValue(20)
    assert read_settings(prj).boreholes[0].section_curves == ["t:res"]
    v.curve_check("t:gr").setChecked(True)
    assert sorted(read_settings(prj).boreholes[0].section_curves) == ["t:gr", "t:res"]
    v.deleteLater()



def test_options_saved_when_changed_not_on_close(fake_dock, qgis_app):
    """Minor 1: options are written when they change; closing a detached viewer (project
    being cleared) writes nothing into whatever project is current then."""
    from qgis.core import QgsProject

    from geophysics_workbench.section.borehole_viewer import OPTIONS_KEY, SCOPE, BoreholeViewer
    prj = QgsProject.instance()
    prj.removeEntry(SCOPE, OPTIONS_KEY)
    v = BoreholeViewer(fake_dock, prj)
    v.set_mode("even")
    assert '"even"' in prj.readEntry(SCOPE, OPTIONS_KEY, "")[0]
    prj.removeEntry(SCOPE, OPTIONS_KEY)               # the project is cleared ...
    v.detach()
    v.close()                                         # ... then the viewer closes
    assert prj.readEntry(SCOPE, OPTIONS_KEY, "")[0] == ""
    v.deleteLater()


def test_settings_column_never_cut_off(viewer, qgis_app):
    """Usability review 2: the settings column was clipped (Font button a cut-off box)."""
    from qgis.PyQt.QtWidgets import QScrollArea
    scroll = next(w for w in viewer.findChildren(QScrollArea) if w.widget() is not None
                  and w.widget().findChild(type(viewer.font_button)) is not None)
    from qgis.PyQt.QtCore import Qt
    qgis_app.processEvents()
    assert scroll.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert scroll.minimumWidth() >= scroll.widget().minimumSizeHint().width()
