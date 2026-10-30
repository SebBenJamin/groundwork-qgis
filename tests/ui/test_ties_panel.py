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
    assert dock.calls == [("open", demo_like[1].id), ("cursor", approx(8.0))]


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
        action = next(a for a in plugin.actions if a.text() == "Profile ties…")
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
