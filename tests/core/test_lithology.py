from groundwork_geophysics.core.lithology import lithology_colour


def test_lithology_colours_known_terms_and_stable_fallback():
    assert lithology_colour("Feinsand, schluffig") == lithology_colour("sand")
    assert lithology_colour("Ton") != lithology_colour("Sand")
    assert lithology_colour("Xyzit") == lithology_colour("xyzit")   # case-insensitive and stable


def test_sandstein_is_rock_not_sand():
    """R5: "sandstein" contains "sand", so it must be matched first."""
    assert lithology_colour("Sandstein") == lithology_colour("Fels")
    assert lithology_colour("Sandstein, verwittert") != lithology_colour("Sand")
    assert lithology_colour("Feinsand") == lithology_colour("Sand")
