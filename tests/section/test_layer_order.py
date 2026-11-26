"""The user orders a section's layers: the Layers list reads like the QGIS layer tree (the top
row is drawn on top), rows move by dragging or from their menu, and the order is kept per
profile in the project, beside the section styles."""
import shutil
from dataclasses import replace

import pytest


@pytest.fixture
def three(store_with_model):
    """``store_with_model`` with two more models on P1 (copies of the same file): d1, d2, d3
    in the order they were added. Returns (store, profile)."""
    from groundwork_geophysics.core.model import Dataset, file_fingerprint
    st, p, src = store_with_model
    set_id = st.station_sets(p.id)[0].id
    for did in ("d2", "d3"):
        copy = src.with_name(f"{did}.dat")
        shutil.copy(src, copy)
        mt, sha = file_fingerprint(copy)
        st.save_dataset(Dataset(did, p.id, set_id, "ert_model", str(copy), mt, sha,
                                "r2_res_dat", {"z_kind": "elevation"}, {},
                                name=f"P1 model {did}"))
    return st, p


def _ids(layers):
    return [la.dataset.id for la in layers]


def test_without_a_stored_order_layers_come_in_the_order_they_were_added(three):
    from groundwork_geophysics.section.data import SectionDataProvider
    st, p = three
    assert _ids(SectionDataProvider(st).layers(p.id)) == ["d1", "d2", "d3"]


def test_the_provider_hands_out_layers_in_the_stored_order(three):
    from groundwork_geophysics.section.data import SectionDataProvider
    st, p = three
    prov = SectionDataProvider(st, orders={p.id: ["d3", "d1", "d2"]})
    assert _ids(prov.layers(p.id)) == ["d3", "d1", "d2"]
    assert _ids(prov.snapshot(p.id).layers) == ["d3", "d1", "d2"]


def test_unknown_ids_are_ignored_and_missing_ones_come_on_top_in_added_order(three):
    from groundwork_geophysics.section.data import SectionDataProvider
    st, p = three
    prov = SectionDataProvider(st, orders={p.id: ["gone", "d3"]})
    assert _ids(prov.layers(p.id)) == ["d3", "d1", "d2"]


def test_setting_the_order_redraws_and_is_told_to_the_style_keepers(three):
    from groundwork_geophysics.section.data import SectionDataProvider
    st, p = three
    prov = SectionDataProvider(st)
    told, drawn = [], []
    prov.on_style.append(lambda: told.append(1))
    prov.on_change.append(lambda: drawn.append(1))
    prov.set_layer_order(p.id, ["d2", "d3", "d1"])
    assert _ids(prov.layers(p.id)) == ["d2", "d3", "d1"]
    assert prov.layer_orders() == {p.id: ["d2", "d3", "d1"]}
    assert told and drawn


def test_removing_a_dataset_drops_it_from_the_order(three):
    from groundwork_geophysics.section.data import SectionDataProvider
    st, p = three
    prov = SectionDataProvider(st, orders={p.id: ["d3", "d2", "d1"]})
    prov.remove_dataset("d2")
    assert prov.layer_orders() == {p.id: ["d3", "d1"]}
    assert _ids(prov.layers(p.id)) == ["d3", "d1"]


def test_the_order_survives_saving_and_reopening(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.section.style_store import load_layer_orders, save_layer_orders
    prj = QgsProject()
    assert load_layer_orders(prj) == {}                         # an old project: no entry
    save_layer_orders(prj, {"p1": ["d2", "d1"], "p2": []})
    assert load_layer_orders(prj) == {"p1": ["d2", "d1"]}
    prj.setDirty(False)
    save_layer_orders(prj, {"p1": ["d2", "d1"]})
    assert not prj.isDirty()


def test_an_unusable_order_entry_gives_no_order(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.section.style_store import (ORDER_KEY, SCOPE,
                                                           load_layer_orders)
    prj = QgsProject()
    for text in ("not json", "[]", '{"p1": "d1"}', '{"p1": [1, 2]}'):
        prj.writeEntry(SCOPE, ORDER_KEY, text)
        assert load_layer_orders(prj) == {}


# -- the Layers list -------------------------------------------------------------------------
@pytest.fixture
def listed(qgis_app, three):
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.layer_list import LayerList
    st, p = three
    prov = SectionDataProvider(st)
    ll = LayerList()
    ll.resize(280, 300)
    ll.set_layers(prov, prov.layers(p.id))
    ll.show()
    qgis_app.processEvents()
    yield ll, prov, p
    ll.close()
    ll.deleteLater()
    qgis_app.processEvents()


def _rows_top_first(ll):
    rows = [ll._box_layout.itemAt(i).widget() for i in range(ll._box_layout.count())]
    return [r.dataset_id for r in rows if r is not None]


def test_the_top_row_is_the_layer_drawn_on_top(listed):
    ll, prov, p = listed
    assert _rows_top_first(ll) == ["d3", "d2", "d1"]
    assert _ids(prov.layers(p.id))[-1] == _rows_top_first(ll)[0]


def _action(menu, text):
    return next(a for a in menu.actions() if a.text() == text)


def test_the_move_entries_are_disabled_where_they_do_nothing(listed):
    from groundwork_geophysics.section.layer_list import (MOVE_BOTTOM_TEXT, MOVE_DOWN_TEXT,
                                                          MOVE_TOP_TEXT, MOVE_UP_TEXT)
    ll, prov, p = listed
    top = ll.row_menu("d3")
    assert not _action(top, MOVE_TOP_TEXT).isEnabled()
    assert not _action(top, MOVE_UP_TEXT).isEnabled()
    assert _action(top, MOVE_TOP_TEXT).toolTip()                  # says why
    assert _action(top, MOVE_DOWN_TEXT).isEnabled()
    assert _action(top, MOVE_BOTTOM_TEXT).isEnabled()
    bottom = ll.row_menu("d1")
    assert not _action(bottom, MOVE_DOWN_TEXT).isEnabled()
    assert not _action(bottom, MOVE_BOTTOM_TEXT).isEnabled()
    assert _action(bottom, MOVE_UP_TEXT).isEnabled()
    for menu in (top, bottom):
        menu.deleteLater()


@pytest.mark.parametrize("text, dataset_id, rows", [
    ("Move to Top", "d1", ["d1", "d3", "d2"]),
    ("Move Up", "d1", ["d3", "d1", "d2"]),
    ("Move Down", "d3", ["d2", "d3", "d1"]),
    ("Move to Bottom", "d3", ["d2", "d1", "d3"]),
])
def test_each_menu_entry_moves_the_row_and_the_drawing_order(listed, text, dataset_id, rows):
    ll, prov, p = listed
    saved = []
    prov.on_style.append(lambda: saved.append(prov.layer_orders()))
    menu = ll.row_menu(dataset_id)
    _action(menu, text).trigger()
    menu.deleteLater()
    assert _rows_top_first(ll) == rows
    assert _ids(prov.layers(p.id)) == rows[::-1]                  # bottom first
    assert saved and saved[-1] == {p.id: rows[::-1]}


def test_dropping_a_dragged_row_moves_it_there(listed, qgis_app):
    from qgis.PyQt.QtCore import QMimeData, QPointF, Qt
    from qgis.PyQt.QtGui import QDropEvent

    from groundwork_geophysics.section.layer_list import ROW_MIME
    ll, prov, p = listed
    rows = {r: ll._rows[r] for r in ll._rows}
    mime = QMimeData()
    mime.setData(ROW_MIME, b"d1")                               # the bottom row ...
    y = rows["d3"].geometry().top() + 2                         # ... dropped on the top one
    event = QDropEvent(QPointF(10, y), Qt.DropAction.MoveAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    # offscreen Qt delivers no drop outside a real drag: hand it to the box's filter
    assert ll.eventFilter(ll._box, event)
    qgis_app.processEvents()
    assert _rows_top_first(ll) == ["d1", "d3", "d2"]
    assert _ids(prov.layers(p.id)) == ["d2", "d3", "d1"]


def test_the_row_has_a_drag_handle_that_says_how(listed):
    ll, prov, p = listed
    handle = ll._rows["d2"].handle
    assert handle.isVisible() and "drag" in handle.toolTip().lower()


# -- everything that draws follows -------------------------------------------------------------
def _coloured(prov, p):
    """d1 drawn in one colour, d2 in another (fixed scales far apart), d3 hidden."""
    from groundwork_geophysics.core.colors import ColorScale
    prov.layers(p.id)
    prov.set_style("d1", replace(prov.style("d1"), mode="cells",
                                 scale=ColorScale("viridis", 1e6, 1e7, True)))     # all low end
    prov.set_style("d2", replace(prov.style("d2"), mode="cells",
                                 scale=ColorScale("viridis", 1e-7, 1e-6, True)))   # all high end
    prov.set_style("d3", replace(prov.style("d3"), visible=False))


def _middle_colour(prov, p):
    from groundwork_geophysics.section.picture import section_pictures
    layers = [la for la in prov.layers(p.id) if la.style.visible]
    picture = section_pictures(layers, prov.surface(p.id).line)[0]
    mesh = layers[0].mesh
    i = len(mesh.cells) // 2
    s, z = mesh.vertices[[k for k in mesh.cells[i] if k >= 0]].mean(axis=0)
    img = picture.image
    col = int((s - picture.s0) / (picture.s1 - picture.s0) * img.width())
    row = int((picture.z1 - z) / (picture.z1 - picture.z0) * img.height())
    c = img.pixelColor(col, row)
    return c.red(), c.green(), c.blue()


def test_the_section_picture_draws_the_top_layer_over_the_others(qgis_app, three):
    from groundwork_geophysics.section.data import SectionDataProvider
    st, p = three
    prov = SectionDataProvider(st)
    _coloured(prov, p)
    high = tuple(int(c) for c in prov.style("d2").scale.rgba([1.0])[0][:3])
    low = tuple(int(c) for c in prov.style("d1").scale.rgba([1.0])[0][:3])
    assert _middle_colour(prov, p) == pytest.approx(high, abs=3)     # d2 added later: on top
    prov.set_layer_order(p.id, ["d2", "d1"])
    assert _middle_colour(prov, p) == pytest.approx(low, abs=3)


def test_a_plate_frame_follows_the_order_with_its_colour_bars(qgis_app, three):
    from groundwork_geophysics.plates.build import frame_models
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.ui.plates_dialog import panel_look
    st, p = three
    prov = SectionDataProvider(st)
    _coloured(prov, p)
    look = panel_look(prov, p.id)
    snap = prov.snapshot(p.id, look=look)
    assert _ids(snap.layers) == ["d1", "d2"]
    assert [d.id for d in frame_models(st, p.id, look, snap)] == ["d1", "d2"]
    prov.set_layer_order(p.id, ["d2", "d3", "d1"])
    snap = prov.snapshot(p.id, look=look)
    assert _ids(snap.layers) == ["d2", "d1"]
    assert [d.id for d in frame_models(st, p.id, look, snap)] == ["d2", "d1"]
