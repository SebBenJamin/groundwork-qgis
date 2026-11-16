"""Round 2, F3: contours at typed major and minor levels (values in the model's unit)."""
import pytest

from groundwork_geophysics.core.colors import ColorScale


def test_parse_levels():
    from groundwork_geophysics.core.numbers import parse_levels
    assert parse_levels("10;30; 100") == (10.0, 30.0, 100.0)
    assert parse_levels("") == () and parse_levels(" ; ") == ()
    with pytest.raises(ValueError, match="“abc” is not a number"):
        parse_levels("10;abc")


def test_parse_levels_german(qgis_app):
    from qgis.PyQt.QtCore import QLocale

    from groundwork_geophysics.core.numbers import parse_levels
    QLocale.setDefault(QLocale(QLocale.Language.German, QLocale.Country.Germany))
    try:
        assert parse_levels("1,5;20") == (1.5, 20.0)
    finally:
        QLocale.setDefault(QLocale.c())             # as conftest pins it


def test_levels_text(qgis_app):
    from groundwork_geophysics.core.numbers import levels_text
    assert levels_text((10.0, 30.0, 2.5)) == "10;30;2.5"
    assert levels_text(()) == ""


def test_auto_levels_unchanged():
    from groundwork_geophysics.core.gridding import contour_levels, default_levels
    sc = ColorScale("viridis", 1.0, 1000.0, True)
    assert contour_levels(sc, None, (), ()) == [(v, True) for v in default_levels(sc, None)]
    assert contour_levels(sc, 0.5, (), ()) == [(v, True) for v in default_levels(sc, 0.5)]


def test_major_wins():
    from groundwork_geophysics.core.gridding import contour_levels
    sc = ColorScale("viridis", 1.0, 1000.0, True)
    assert contour_levels(sc, None, (10, 100), (10, 50)) == \
        [(10.0, True), (50.0, False), (100.0, True)]


def test_levels_outside_range_and_duplicates():
    """Review Focus 3: outside the scale, repeated, unsorted: ignored or merged, no crash."""
    from groundwork_geophysics.core.gridding import contour_levels
    sc = ColorScale("viridis", 1.0, 1000.0, True)
    assert contour_levels(sc, None, (5000, 100, 100.0000000001, 0.5, -3), (20, 20)) == \
        [(20.0, False), (100.0, True)]
    assert contour_levels(sc, None, (5000,), ()) == []


def test_model_look_roundtrip():
    from dataclasses import asdict

    from groundwork_geophysics.core.plates import ModelLook, _model
    m = ModelLook("d1", mode="contours", contour_major=[10.0, 100.0], contour_minor=[50.0])
    back = _model(asdict(m))
    assert back.contour_major == [10.0, 100.0] and back.contour_minor == [50.0]
    bad = _model({"dataset_id": "d1", "contour_major": [1, "x", float("nan"), True]})
    assert bad.contour_major == [1.0]
