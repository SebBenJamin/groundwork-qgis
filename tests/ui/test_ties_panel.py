"""Profile ties panel: table of crossings, mismatch indication and the two-model plot."""
import shutil
import sys

import numpy as np
import pytest
from pytest import approx

from geophysics_workbench.core.model import Dataset, file_fingerprint, profile_from_stations
from geophysics_workbench.section.data import LayerStyle, SectionDataProvider

from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def _add(st, tmp_path, name, xy, scale=1.0):
    """Profile ``name`` with its own copy of f001_res.dat, resistivities times ``scale``."""
    p, s = profile_from_stations(name, "EPSG:25832", np.array(xy, dtype=float))
    st.save_profile(p); st.save_station_set(s)
    src = tmp_path / f"{name}_res.dat"
    rows = np.loadtxt(FIXTURES / "ert" / "f001_res.dat")
    rows[:, 2] *= scale
    rows[:, 3] += np.log10(scale)
    np.savetxt(src, rows)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset(f"d{name}", p.id, s.id, "ert_model", str(src), mt, sha,
                            "r2_res_dat", {"z_kind": "elevation"}, {}, name=f"{name} model"))
    return p


@pytest.fixture
def demo_like(store_with_model, tmp_path):
    """P1 (0,0)-(50,0) crossed by P2 at s=4 and by P3 at s=8 (inside the fixture model, 1 to 10 m); P3 reads twice as high."""
    st, p1, _ = store_with_model
    p2 = _add(st, tmp_path, "P2", [[4, -4, 100], [4, 46, 100]])
    p3 = _add(st, tmp_path, "P3", [[8, -8, 100], [8, 42, 100]], scale=2.0)
    return st, p1, p2, p3


class FakeDock:
    def __init__(self):
        self.calls = []

    def show(self):
        self.calls.append(("show",))

    def raise_(self):
        self.calls.append(("raise",))

    def open_profile(self, pid):
        self.calls.append(("open", pid))
        return True

    def show_cursor(self, s):
        self.calls.append(("cursor", s))


@pytest.fixture
def make_panel(qgis_app):
    from geophysics_workbench.ui.ties_panel import TiesPanel
    made = []

    def factory(store, near_miss=3.0):
        provider = SectionDataProvider(store)
        provider.near_miss = near_miss
        dock = FakeDock()
        panel = TiesPanel(provider, dock)
        panel.resize(700, 700)
        panel.show()
        qgis_app.processEvents()
        made.append(panel)
        return panel, provider, dock

    yield factory
    for panel in made:
        panel.detach()
        panel.close()
        panel.deleteLater()
    qgis_app.processEvents()


def _cells(panel):
    t = panel.table
    return [[t.item(r, c).text() for c in range(t.columnCount())] for r in range(t.rowCount())]


def test_backend_qtagg_imports_under_qgis(qgis_app):
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg  # noqa: F401
    assert "matplotlib.pyplot" not in sys.modules


def test_table_rows_for_demo_like_store(make_panel, demo_like):
    panel, _prov, _dock = make_panel(demo_like[0])
    rows = _cells(panel)
    assert [r[0] for r in rows] == ["P1 × P2", "P1 × P3"]
    assert [panel.table.horizontalHeaderItem(c).text() for c in range(5)] == [
        "Profiles", "At", "Distance", "Compared", "Mismatch"]
    assert rows[0][1] == "P1 4 m · P2 4 m" and rows[0][2] == "crossing"
    assert rows[0][3] == "P1 model · P2 model"
    assert rows[0][4].startswith("×1.0 (median,") and rows[1][4].startswith("×2.0 (median,")
    assert "indication" in panel.note.text()
    assert panel.note.text() == ("2D profiles in different directions are not expected to "
                                 "match exactly; the figure is an indication.")


def test_no_model_and_near_miss_rows(make_panel, demo_like):
    st, p1, p2, p3 = demo_like
    p3.xy = np.array([[8, 6.0], [8, 56.0]])           # 6 m short of P1
    st.save_profile(p3)
    panel, prov, _dock = make_panel(st, near_miss=10.0)
    prov.set_style("dP3", LayerStyle(visible=False))
    panel.refresh()
    rows = _cells(panel)
    assert rows[1][2] == "6 m (near miss)" and rows[1][4] == "no model at tie"
    assert rows[1][3] == "P1 model · –" and rows[0][4].startswith("×1.0")
    panel.table.selectRow(1)
    assert panel.plot.ax.get_title() == "P1 × P3 (6 m near miss)"
    assert len(panel.plot.ax.lines) == 1


def test_show_in_section_opens_profile_and_cursor(make_panel, demo_like):
    panel, _prov, dock = make_panel(demo_like[0])
    panel.table.selectRow(1)
    panel.show_button.click()
    assert dock.calls == [("show",), ("raise",), ("open", demo_like[1].id),
                          ("cursor", approx(8.0))]


def test_show_in_section_brings_a_closed_section_panel_back(qgis_app, fake_iface, demo_like):
    """R19a: the section panel may have been closed; "Show in section" reopens it."""
    from geophysics_workbench.plugin import WorkbenchPlugin
    st, p1, _p2, _p3 = demo_like
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.set_store(st)
        next(a for a in plugin.actions if a.text() == "Profile Ties…").trigger()
        panel, dock = plugin.ties_panel, plugin.dock
        dock.close()
        qgis_app.processEvents()
        assert dock.isHidden()
        panel.table.selectRow(1)
        panel.show_button.click()
        qgis_app.processEvents()
        assert not dock.isHidden()
        assert dock.current_profile_id() == p1.id and dock.cursor_chainage() == approx(8.0)
    finally:
        plugin.unload()


def test_plot_has_two_lines_and_log_axis(make_panel, demo_like):
    panel, _prov, _dock = make_panel(demo_like[0])
    panel.table.selectRow(0)
    ax = panel.plot.ax
    assert len(ax.lines) == 2 and ax.get_xscale() == "log"
    assert ax.get_title() == "P1 × P2 (crossing)"
    assert ax.get_ylabel() == "Elevation (m)" and "Ω·m" in ax.get_xlabel()
    assert len(ax.patches) == 1                          # shaded overlap
    assert "matplotlib.pyplot" not in sys.modules


def test_refresh_keeps_selection_and_follows_changes(make_panel, demo_like):
    panel, prov, _dock = make_panel(demo_like[0])
    panel.table.selectRow(1)
    prov.notify_changed()
    panel.refresh()
    assert panel.table.currentRow() == 1 and panel.plot.ax.get_title().startswith("P1 × P3")
    prov.set_style("dP2", LayerStyle(visible=False))
    panel.refresh()
    assert _cells(panel)[0][4] == "no model at tie"


def test_detach_removes_listener(make_panel, demo_like):
    panel, prov, _dock = make_panel(demo_like[0])
    assert len(prov.on_change) == 1
    panel.detach()
    assert prov.on_change == []


def test_plugin_menu_action_and_lifecycle(qgis_app, fake_iface, store_with_model):
    from geophysics_workbench.plugin import WorkbenchPlugin
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        action = next(a for a in plugin.actions if a.text() == "Profile Ties…")
        assert not action.isEnabled()
        plugin.set_store(store_with_model[0])
        assert action.isEnabled()
        action.trigger()
        panel = plugin.ties_panel
        assert panel is not None and panel.objectName() == "GeophysicsWorkbenchTiesPanel"
        action.trigger()
        assert plugin.ties_panel is panel
        plugin.set_store(None)
        assert plugin.ties_panel is None and not action.isEnabled()
    finally:
        plugin.unload()


def test_double_crossing_gives_two_rows_with_own_columns(make_panel, store_with_model, tmp_path):
    st, p1, _ = store_with_model
    p2 = _add(st, tmp_path, "P2", [[3, -2, 100], [3, 1, 100], [4, 1, 100], [4, -2, 100]])
    top = tmp_path / "P2_top.dat"                       # second visible layer, drawn last
    rows_in = np.loadtxt(FIXTURES / "ert" / "f001_res.dat")
    rows_in[:, 2] *= 3
    rows_in[:, 3] += np.log10(3)
    np.savetxt(top, rows_in)
    mt, sha = file_fingerprint(top)
    st.save_dataset(Dataset("dP2top", p2.id, st.station_sets(p2.id)[0].id, "ert_model", str(top),
                            mt, sha, "r2_res_dat", {"z_kind": "elevation"}, {}, name="P2 top"))
    panel, prov, _dock = make_panel(st)
    rows = [r for r in panel.rows if r.a_name == "P1" and r.b_name == "P2"]
    assert len(rows) == 2 and len(panel.rows) == 2
    assert [(r.s_a, r.s_b) for r in rows] == [(approx(3.0), approx(2.0)), (approx(4.0), approx(5.0))]
    ats = [c[1] for c in _cells(panel)]
    assert len(set(ats)) == 2
    from geophysics_workbench.section.ties_data import tie_column
    for r in rows:
        for col, pid, pos in ((r.col_a, p1.id, r.s_a), (r.col_b, p2.id, r.s_b)):
            expect = tie_column(prov.layers(pid)[-1], pos)       # topmost = last drawn
            assert col.values.tolist() == expect.values.tolist() and col.values.size
    assert all(r.col_b.dataset_name == "P2 top" for r in rows)
    assert rows[0].col_b.values.tolist() != rows[1].col_b.values.tolist()


def test_sorting_is_numeric(make_panel, store_with_model, tmp_path):
    from qgis.PyQt.QtCore import Qt
    st, p1, _ = store_with_model
    p1.xy = np.array([[0, 0.0], [150, 0.0]])
    st.save_profile(p1)
    _add(st, tmp_path, "P2", [[120, -4, 100], [120, 46, 100]])
    _add(st, tmp_path, "P3", [[47, -4, 100], [47, 46, 100]])
    panel, _prov, _dock = make_panel(st)
    panel.table.sortItems(1, Qt.SortOrder.AscendingOrder)
    assert [r[1] for r in _cells(panel)][:2] == ["P1 47 m · P3 4 m", "P1 120 m · P2 4 m"]
    panel.table.sortItems(1, Qt.SortOrder.DescendingOrder)
    assert _cells(panel)[0][1].startswith("P1 120 m")


def _plot_labels(values, qgis_app):
    from geophysics_workbench.core.ties import TieColumn
    from geophysics_workbench.ui.ties_panel import TieRow
    from geophysics_workbench.ui.ties_plot import TiesPlot
    v = np.array(values, dtype=float)
    z = np.linspace(0.0, -2.0 * len(v) / 2, len(v) + 1)
    col = TieColumn("m", z[:-1], z[1:], v, None, "resistivity", "ohm.m")
    plot = TiesPlot()
    plot.show_row(TieRow("a", "b", "A", "B", 1.0, 1.0, 0.0, col, col, None, ""))
    plot.draw()
    lo, hi = plot.ax.get_xlim()
    minor = [t.get_text() for t, x in zip(plot.ax.xaxis.get_minorticklabels(),
                                          plot.ax.xaxis.get_minorticklocs()) if lo <= x <= hi]
    major = [t.get_text() for t, x in zip(plot.ax.xaxis.get_majorticklabels(),
                                          plot.ax.xaxis.get_majorticklocs()) if lo <= x <= hi]
    return minor, major


def test_log_ticks_minor_labels_only_on_short_axis(qgis_app):
    minor, major = _plot_labels([8, 30, 150, 600], qgis_app)       # two decades
    assert minor and all(t == "" for t in minor)
    assert major and all(t in ("10", "100") for t in major)
    minor, major = _plot_labels([200, 300, 450, 600], qgis_app)    # under a decade
    assert any(t != "" for t in minor)


def test_no_ties_while_local(make_panel, demo_like):
    from geophysics_workbench.core.model import profile_from_polyline
    st, p1, _p2, _p3 = demo_like
    local = profile_from_polyline("L9", "EPSG:25832", np.array([[20.0, -10.0], [20.0, 30.0]]))
    st.save_profile(local)                              # crosses P1 at 20 m, no heights
    panel, prov, _dock = make_panel(st)
    assert prov.is_local(local.id)
    assert prov.ties(local.id) == []
    assert all(t.other_id != local.id for t in prov.ties(p1.id))
    assert all("L9" not in r[0] for r in _cells(panel))
    sentence = "Profile L9 has no heights yet: set a reference height to compare and export it."
    assert panel.held_back.text() == sentence and not panel.held_back.isHidden()
    prov.set_reference_height(local.id, 20.0, 101.0)
    panel.refresh()
    assert [t.other_id for t in prov.ties(local.id)] == [p1.id]
    assert any(r[0] == "L9 × P1" for r in _cells(panel)) and panel.held_back.isHidden()
