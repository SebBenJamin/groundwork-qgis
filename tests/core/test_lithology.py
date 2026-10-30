from geophysics_workbench.core.lithology import lithology_colour


def test_lithology_colours_known_terms_and_stable_fallback():
    assert lithology_colour("Feinsand, schluffig") == lithology_colour("sand")
    assert lithology_colour("Ton") != lithology_colour("Sand")
    assert lithology_colour("Xyzit") == lithology_colour("xyzit")   # case-insensitive and stable
