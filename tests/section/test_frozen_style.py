"""Usability round 1, Task 3: frozen and compare versions are drawn in their QGIS style
(faded for compare), not in a solid default fill that hides the model."""
from tests.section.test_interp_edit import ctl  # noqa: F401  (fixture)


def _poly_setup(c, store):
    from qgis.core import QgsProject

    from groundwork_geophysics.core.interpretation import InterpFeature, InterpPiece, new_id
    from groundwork_geophysics.ui.interp_layers import interp_layers
    v = store.current_version()
    f = InterpFeature(new_id(), v.id, type="clay lens", name="K")
    store.save_feature(f)
    pid = c.dock.current_profile_id()
    p = InterpPiece(new_id(), v.id, f.id, pid, "polygon",
                    [(2.0, -1.0), (8.0, -1.0), (8.0, -3.0), (2.0, -3.0)])
    store.save_piece(p)
    c.changed(v.id)
    c.dock.provider.interp_layers = lambda: interp_layers(store, QgsProject.instance())
    return f, p, pid


def _colour(entry):
    sym, _feature = entry
    return sym.color().name(), sym.symbolLayer(0).brushStyle() \
        if hasattr(sym.symbolLayer(0), "brushStyle") else None


def test_frozen_piece_uses_layer_symbol(ctl):
    c, store, _p = ctl
    f, p, pid = _poly_setup(c, store)
    prov = c.dock.provider
    current = prov.snapshot(pid).interp_symbols[p.id]
    frozen = store.freeze_current("delivered")
    prov.interp_version_id = frozen.id
    snap = prov.snapshot(pid)
    [fp] = [q for q in snap.interpretation if q.kind == "polygon"]
    assert _colour(snap.interp_symbols[fp.id]) == _colour(current)


def test_frozen_piece_without_twin_never_hides_the_model(ctl):
    from qgis.PyQt.QtCore import Qt
    c, store, _p = ctl
    f, p, pid = _poly_setup(c, store)
    prov = c.dock.provider
    frozen = store.freeze_current("delivered")
    store.delete_piece(p.id)                    # gone from the current version
    c.changed(store.current_version().id)
    prov.interp_version_id = frozen.id
    snap = prov.snapshot(pid)
    [fp] = [q for q in snap.interpretation if q.kind == "polygon"]
    sym, _ = snap.interp_symbols[fp.id]
    assert sym.symbolLayer(0).brushStyle() == Qt.BrushStyle.NoBrush


def test_compare_overlay_is_faded():
    from groundwork_geophysics.section.interp_render import COMPARE_OPACITY
    assert COMPARE_OPACITY == 0.35
