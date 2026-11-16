from groundwork_geophysics.core.context import collar_height


def test_collar_order_field_then_dem_then_surface():
    assert collar_height(25.0, 24.0, 23.0) == (25.0, "field")
    assert collar_height(None, 24.0, 23.0) == (24.0, "dem")
    assert collar_height(None, None, 23.0) == (23.0, "surface")
    assert collar_height(None, None, None) == (None, "")
