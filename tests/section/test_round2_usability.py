"""Round 2 usability review: typed levels survive OK, hidden boreholes always have a way
back, level input mistakes are named, the duplicate-name hint is per profile, hiding a
borehole says so and can be undone."""
import pytest

from test_interp_tools import dock  # noqa: F401


def _bh(s=5.0, label="RK1", bid="RK1"):
    from geophysics_workbench.core.context import LogInterval, ProjectedPoint
    return ProjectedPoint(s, 1.5, label, "borehole", 0.0, [LogInterval(0.0, 3.0, "sand")],
                          entry=0, bid=bid, layer_id="L1")


def _visible(qgis_app, dock):
    dock.fit.user_navigated()
    dock.canvas.setVisiblePlotRange(0.0, 20.0, -10.0, 5.0)
    qgis_app.processEvents()


def test_typed_levels_survive_ok(qgis_app, dock, monkeypatch):
    """Critical 1: Display… OK kept the automatic levels (fields not copied)."""
    from geophysics_workbench.section import layer_list as ll
    from geophysics_workbench.section.scale_dialog import DisplayDialog
    pid = dock.current_profile_id()
    dataset_id = dock.provider.layers(pid)[0].dataset.id

    def run(dlg):
        dlg.mode_combo.setCurrentIndex(dlg.mode_combo.findData("contours"))
        dlg.major_edit.setText("100")
        dlg.minor_edit.setText("200")         # inside the model's scale (81-314 ohm.m)
        dlg.accept()

    monkeypatch.setattr(DisplayDialog, "exec", run)
    dock.layer_list.edit_scale(dataset_id)
    style = dock.provider.style(dataset_id)
    assert style.contour_major == (100.0,) and style.contour_minor == (200.0,)
    assert "contour_major" in ll.DISPLAY_FIELDS


def test_show_hidden_from_anywhere_in_section(qgis_app, dock, monkeypatch):
    """Critical 2: with every borehole hidden there was no way back from the section."""
    from qgis.PyQt.QtWidgets import QMenu

    from geophysics_workbench.core.context import ContextItems
    from geophysics_workbench.section.dock import show_hidden_text
    pid = dock.current_profile_id()
    dock.provider.context_source = lambda profile: ContextItems(points=[_bh()])
    dock.provider.set_boreholes_hidden(pid, [("L1", "RK1")], True)
    _visible(qgis_app, dock)
    dock._ctx = (dock.provider.context(pid), None)
    seen = []

    def run(menu, *_a):
        seen.append([a.text() for a in menu.actions()])
        menu.actions()[-1].trigger()

    monkeypatch.setattr(QMenu, "exec", run)
    assert dock.handle_right_click(15.0, -2.0, None)            # empty space
    assert seen == [[show_hidden_text(1)]] and show_hidden_text(1) == "Show Hidden Boreholes (1)"
    assert dock.provider.hidden_keys(pid) == set()
    assert not dock.handle_right_click(15.0, -2.0, None)        # nothing hidden: no menu


def test_hide_says_so_and_is_undoable(qgis_app, dock, monkeypatch):
    """Important 7: no feedback, no undo."""
    from qgis.PyQt.QtWidgets import QMenu

    from geophysics_workbench.core.context import ContextItems
    pid = dock.current_profile_id()
    dock.provider.context_source = lambda profile: ContextItems(points=[_bh()])
    dock.provider.notify_changed()
    _visible(qgis_app, dock)
    dock._ctx = (ContextItems(points=[_bh()]), None)
    monkeypatch.setattr(QMenu, "exec", lambda menu, *a: menu.actions()[0].trigger())
    dock.handle_right_click(5.0, -2.0, None)
    assert dock.provider.hidden_keys(pid) == {("L1", "RK1")}
    assert "RK1 hidden in this section" in dock.tool_hint_text()
    dock.interp.undo.stack.undo()
    assert dock.provider.hidden_keys(pid) == set()
    dock.interp.undo.stack.redo()
    assert dock.provider.hidden_keys(pid) == {("L1", "RK1")}


@pytest.mark.parametrize("text,message", [
    ("10 30 100", "Separate values with “;”"),
])
def test_space_separated_levels_named(qgis_app, text, message):
    """Important 4: "10 30 100" became one level 1030100 without a word."""
    from geophysics_workbench.core.numbers import parse_levels
    with pytest.raises(ValueError, match=message):
        parse_levels(text)


def test_levels_outside_scale_named(qgis_app, store_with_model):
    """Important 4: levels outside the colour scale were dropped silently."""
    from dataclasses import replace

    from geophysics_workbench.core.colors import ColorScale
    from geophysics_workbench.section.scale_dialog import DisplayDialog
    from tests.section.test_display_dialog import _layer
    _prov, layer = _layer(store_with_model)
    layer = replace(layer, style=replace(layer.style, mode="contours",
                                         scale=ColorScale("viridis", 22.0, 427.0, True)))
    dlg = DisplayDialog(None, layer)
    dlg.major_edit.setText("100;5000")
    dlg.accept()
    assert dlg.result() != dlg.DialogCode.Accepted
    assert "5000 is outside the colour scale" in dlg.message.text()


def test_duplicate_name_hint_only_on_this_profile(qgis_app, dock):
    """Important 6: interpretation is per profile; a name on another profile is no clash."""
    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id
    store = dock.provider.store
    store.ensure_interpretation()
    v = store.current_version()
    other = InterpFeature(new_id(), v.id, type="clay", name="Clay A")
    store.save_feature(other)
    store.save_piece(InterpPiece(new_id(), v.id, other.id, "elsewhere", "line",
                                 [(0, -1), (5, -2)]))
    here = InterpFeature(new_id(), v.id, type="clay", name="Clay B")
    store.save_feature(here)
    store.save_piece(InterpPiece(new_id(), v.id, here.id, dock.current_profile_id(), "line",
                                 [(0, -1), (5, -2)]))
    seen = []
    dock.interp.form_factory = lambda f, s, names: seen.append(set(names)) or None
    dock.interp.edit_feature(here.id)
    assert seen and "Clay A" not in seen[0]
