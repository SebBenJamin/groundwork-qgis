"""Usability round 1, Task 7: one number format, from QGIS's locale."""
import pytest


def test_fmt_german(qgis_app):
    from qgis.PyQt.QtCore import QLocale

    from groundwork_geophysics.core.numbers import fmt
    de = QLocale(QLocale.Language.German, QLocale.Country.Germany)
    assert fmt(24.5, 1, de) == "24,5"
    assert fmt(1234.5, 1, de) == "1234,5"                  # no thousands separator
    assert fmt(3.0, 0, de, sign=True) == "+3"


def test_no_negative_zero(qgis_app):
    from qgis.PyQt.QtCore import QLocale

    from groundwork_geophysics.core.numbers import fmt
    c = QLocale.c()
    assert fmt(-0.04, 1, c) == "0.0"
    assert fmt(-0.4, 0, c, sign=True) == "0"
    assert fmt(-2.0, 1, c, sign=True) == "−2.0"


def test_parse_both_separators():
    from groundwork_geophysics.core.numbers import parse
    assert parse("0,5") == 0.5 and parse("0.5") == 0.5
    assert parse("1.234,5") == pytest.approx(1234.5) and parse("1,234.5") == pytest.approx(1234.5)
    assert parse("−2,5") == -2.5
    with pytest.raises(ValueError):
        parse("abc")


def test_readout_uses_locale(qgis_app):
    from qgis.PyQt.QtCore import QLocale

    from groundwork_geophysics.section.readout import format_readout
    old = QLocale()
    QLocale.setDefault(QLocale(QLocale.Language.German, QLocale.Country.Germany))
    try:
        assert format_readout(5.0, 180.24).startswith("s = 5,0 m · z = 180,2")
    finally:
        QLocale.setDefault(old)


def test_offset_labels_never_say_minus_zero(qgis_app):
    from groundwork_geophysics.section.context_render import offset_text
    assert offset_text(-0.3) == "(0 m)"
    assert offset_text(2.4) == "(+2 m)" and offset_text(-3.0) == "(−3 m)"


def test_fmt_trim(qgis_app):
    from qgis.PyQt.QtCore import QLocale

    from groundwork_geophysics.core.numbers import fmt_trim
    de = QLocale(QLocale.Language.German, QLocale.Country.Germany)
    assert fmt_trim(2.0, 2, de) == "2" and fmt_trim(1.25, 2, de) == "1,25"
    assert fmt_trim(115.0, 1, QLocale.c()) == "115"
