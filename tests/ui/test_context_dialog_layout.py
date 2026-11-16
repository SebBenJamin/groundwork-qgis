"""Usability round 1, Task 9 (D1): Context Layers… in tabs that fit a laptop screen."""
import pytest


@pytest.fixture
def dialog(qgis_app, fake_iface):
    from qgis.core import QgsProject, QgsVectorLayer

    from groundwork_geophysics.ui.context_dialog import ContextDialog
    prj = QgsProject.instance()
    prj.clear()
    pts = QgsVectorLayer("Point?crs=EPSG:25833&field=id:string&field=depth:double", "wells",
                         "memory")
    prj.addMapLayer(pts)
    d = ContextDialog(fake_iface, prj)
    yield d
    d.close()
    prj.removeAllMapLayers()


def test_tabs(dialog):
    from qgis.PyQt.QtWidgets import QScrollArea
    tabs = dialog.tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == [
        "Lines", "Points", "Boreholes", "Band and DEM"]
    for i in range(tabs.count()):
        assert isinstance(tabs.widget(i), QScrollArea), tabs.tabText(i)


def test_fits_laptop():
    from qgis.PyQt.QtCore import QRect

    from groundwork_geophysics.ui.context_dialog import initial_size
    size = initial_size(QRect(0, 0, 1366, 728))           # 1366×768 minus the taskbar
    assert size.height() <= 580 and size.height() <= 0.8 * 728
    assert size.width() <= 0.8 * 1366
    small = initial_size(QRect(0, 0, 1280, 650))          # a laptop at 150 %
    assert small.height() <= 0.8 * 650


def test_point_rows_have_headers(dialog):
    from qgis.PyQt.QtWidgets import QLabel
    page = dialog.tabs.widget(1).widget()
    texts = {lab.text() for lab in page.findChildren(QLabel)}
    assert {"Layer", "Label field", "Depth field"} <= texts


def test_plain_labels(dialog):
    from qgis.PyQt.QtWidgets import QLabel
    texts = {lab.text() for lab in dialog.findChildren(QLabel)}
    assert "Search distance from the line (m)" in texts
    assert "Warn when station and DEM heights differ by more than (m)" in texts
    assert not any(t.startswith("Buffer") or t.startswith("DEM vs") for t in texts)


def test_size_is_remembered(dialog, qgis_app):
    from qgis.core import QgsSettings

    from groundwork_geophysics.ui.context_dialog import SIZE_KEY
    dialog.resize(700, 500)
    dialog.reject()
    assert QgsSettings().value(SIZE_KEY) is not None
    QgsSettings().remove(SIZE_KEY)


def test_hig_strings_in_the_strip_group(dialog):
    from qgis.core import QgsProject, QgsVectorLayer

    from groundwork_geophysics.core.context_settings import BandSetting
    from groundwork_geophysics.ui.strip_rows import StripRows
    from tests.ui.test_hig_strings import collect, problems
    prj = QgsProject.instance()
    geo = QgsVectorLayer("Polygon?crs=EPSG:25832&field=unit:string", "Geology", "memory")
    prj.addMapLayer(geo)
    strips = StripRows(prj, [geo])
    strips.load([BandSetting(geo.id(), "unit"), BandSetting("gone", "x")])
    assert strips.title() == "Surface Strips"
    assert not problems(collect(strips), "strips")
    assert {b.text() for b in (strips.add_button, strips.remove_button, strips.up_button,
                               strips.down_button)} == {"Add", "Remove", "Move Up", "Move Down"}
    strips.close()
