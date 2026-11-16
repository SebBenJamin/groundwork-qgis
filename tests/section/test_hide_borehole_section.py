"""Round 2, F4: a hidden borehole leaves the section and the plates of that profile; the
section's right-click on a column offers Hide in Section."""
import pytest

from test_interp_tools import dock  # noqa: F401


def _bh(s=5.0, label="RK1", bid="RK1", layer_id="L1"):
    from groundwork_geophysics.core.context import LogInterval, ProjectedPoint
    return ProjectedPoint(s, 1.5, label, "borehole", 0.0,
                          [LogInterval(0.0, 1.0, "peat"), LogInterval(1.0, 3.0, "sand")],
                          entry=0, bid=bid, layer_id=layer_id)


@pytest.fixture
def prov(store_with_model):
    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.section.data import SectionDataProvider
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    prov.context_source = lambda profile: ContextItems(points=[_bh(), _bh(9.0, "RK2", "RK2")])
    return prov, p


def test_borehole_key():
    from groundwork_geophysics.core.context import borehole_key
    assert borehole_key(_bh()) == ("L1", "RK1")
    assert borehole_key(_bh(bid="")) is None


def test_section_leaves_hidden_out(prov):
    prov, p = prov
    prov.set_boreholes_hidden(p.id, [("L1", "RK1")], True)
    assert [q.label for q in prov.context(p.id).points] == ["RK2"]
    assert [q.label for q in prov.context(p.id, include_hidden=True).points] == ["RK1", "RK2"]
    assert prov.hidden_keys(p.id) == {("L1", "RK1")}


def test_plate_snapshot_leaves_hidden_out(prov):
    from groundwork_geophysics.core.plates import FrameLook
    prov, p = prov
    prov.set_boreholes_hidden(p.id, [("L1", "RK2")], True)
    snap = prov.snapshot(p.id, look=FrameLook())
    assert [q.label for q in snap.context.points] == ["RK1"]
    assert [q.label for q in prov.snapshot(p.id).context.points] == ["RK1"]


def test_set_hidden_redraws(prov):
    prov, p = prov
    calls = []
    prov.on_change.append(lambda: calls.append(1))
    prov.set_boreholes_hidden(p.id, [("L1", "RK1")], True)
    assert calls


def _visible(qgis_app, dock):
    dock.fit.user_navigated()
    dock.canvas.setVisiblePlotRange(0.0, 20.0, -10.0, 5.0)
    qgis_app.processEvents()


def test_right_click_hides(qgis_app, dock, monkeypatch):
    from qgis.PyQt.QtWidgets import QMenu

    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.section.dock import HIDE_IN_SECTION
    dock.provider.context_source = lambda profile: ContextItems(points=[_bh()])
    dock.provider.notify_changed()
    _visible(qgis_app, dock)
    dock._ctx = (ContextItems(points=[_bh()]), None)
    shown = []

    def run(menu, *_args):
        shown.append([a.text() for a in menu.actions()])
        menu.actions()[0].trigger()

    monkeypatch.setattr(QMenu, "exec", run)
    assert not dock.handle_right_click(15.0, -2.0, None)      # no column, nothing hidden
    assert dock.handle_right_click(5.0, -2.0, None)
    assert shown == [[HIDE_IN_SECTION]] and HIDE_IN_SECTION == "Hide in Section"
    pid = dock.current_profile_id()
    assert dock.provider.snapshot(pid).context.points == []


def test_borehole_without_id_cannot_be_hidden(qgis_app, dock, monkeypatch):
    """Review Focus 5: an empty id falls back to the layer name - never hide by that."""
    from qgis.PyQt.QtWidgets import QMenu

    from groundwork_geophysics.core.context import ContextItems
    point = _bh(label="Bohrungen", bid="")
    _visible(qgis_app, dock)
    dock._ctx = (ContextItems(points=[point]), None)
    seen = []
    monkeypatch.setattr(QMenu, "exec", lambda menu, *a: seen.extend(
        (act.isEnabled(), act.toolTip()) for act in menu.actions()))
    dock.handle_right_click(5.0, -2.0, None)
    assert seen == [(False, "This borehole has no id in its layer, so it cannot be "
                            "hidden on its own.")]
