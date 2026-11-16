"""Plate look after user testing: the mini-map's scale bar, colour-bar size, filling the
frame, and items that still find the plugin's data after a plugin reinstall."""
import pytest

from tests.plates.test_build import _plate, env  # noqa: F401  (fixture)


def test_minimap_scalebar_has_a_valid_scale(env):
    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    layout = create_or_update_plate(prj, st, prov, _plate(st, p))
    bar = layout.itemById("wb_map_scalebar")
    assert bar.linkedMap() is layout.itemById("wb_minimap") or \
        bar.linkedMap().id() == "wb_minimap"
    assert bar.unitsPerSegment() > 0 and bar.mapUnitsPerScaleBarUnit() > 0
    assert layout.itemById("wb_minimap").scale() > 0


def test_new_colour_bar_is_a_compact_bar(env):
    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    layout = create_or_update_plate(prj, st, prov, _plate(st, p))
    bar = layout.itemById("wb_colourbar_1_1")
    assert bar.rect().width() <= 20.0 + 1e-6 and bar.rect().height() <= 80.0 + 1e-6


@pytest.mark.parametrize("range_m, width_mm", [(34.0, 290.0), (67.0, 290.0), (500.0, 380.0),
                                                (1234.0, 250.0)])
def test_fit_fills_at_least_three_quarters_of_the_width(range_m, width_mm):
    from groundwork_geophysics.core.plates import nice_scale
    scale, fits = nice_scale(range_m, width_mm)
    used = range_m * 1000.0 / scale
    assert fits and used <= width_mm and used >= 0.75 * width_mm, (scale, used)


def test_items_find_the_provider_after_a_plugin_reinstall(qgis_app):
    """QGIS keeps the first registered item classes until it restarts; after a reinstall
    they belong to the old module object. They read the provider from the module that is
    loaded now (sys.modules), not from their own module's globals."""
    import sys
    import types

    import groundwork_geophysics.plates.items as items
    name = items.__name__
    sentinel = object()
    reinstalled = types.SimpleNamespace(_provider=sentinel)
    sys.modules[name] = reinstalled
    try:
        assert items.current_provider() is sentinel
        assert items.BoreholeLegendItem.provider() is sentinel
        assert items.ColourBarItem.provider() is sentinel
    finally:
        sys.modules[name] = items
