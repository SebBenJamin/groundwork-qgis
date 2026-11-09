"""Plate layout items: a tunable colour bar and a borehole legend."""
import pytest


def test_colour_bar_ticks_auto_step_list():
    from geophysics_workbench.plates.items import colour_bar_ticks
    assert colour_bar_ticks(1.0, 1000.0, True, "auto") == [1.0, 10.0, 100.0, 1000.0]
    assert colour_bar_ticks(0.0, 100.0, False, "step:25") == [0.0, 25.0, 50.0, 75.0, 100.0]
    assert colour_bar_ticks(1.0, 1000.0, True, "list:5, 50,500, 5000") == [5.0, 50.0, 500.0]
    assert colour_bar_ticks(0.0, 10.0, False, "auto") == [0.0, 2.0, 4.0, 6.0, 8.0, 10.0]
    assert colour_bar_ticks(5.0, 5.0, False, "auto") == [5.0]


def test_colour_bar_renders_log_scale_tick_labels(qgis_app):
    from geophysics_workbench.plates.items import default_settings, tick_labels
    assert tick_labels([1.0, 10.0, 100.0, 1000.0], default_settings()) == [
        "1", "10", "100", "1000"]                     # never "1.000" (German locale)


def _layout():
    from qgis.core import QgsPrintLayout, QgsProject
    layout = QgsPrintLayout(QgsProject.instance())
    layout.initializeDefaults()
    return layout


def test_colour_bar_settings_survive_write_read(qgis_app):
    from qgis.core import QgsReadWriteContext
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtXml import QDomDocument

    from geophysics_workbench.plates.items import ColourBarItem, register_items
    register_items()
    layout = _layout()
    bar = ColourBarItem(layout)
    bar.setId("wb_colourbar_1_1")
    bar.frame_id, bar.dataset_id = "f1", "d1"
    bar.ticks, bar.title, bar.unit = "list:1,10,100", "Resistivity", "Ω·m"
    bar.settings.setOrientation(Qt.Orientation.Horizontal)
    layout.addLayoutItem(bar)
    doc = QDomDocument()
    elem = layout.writeXml(doc, QgsReadWriteContext())
    doc.appendChild(elem)
    other = _layout()
    other.readXml(doc.documentElement(), doc, QgsReadWriteContext())
    got = other.itemById("wb_colourbar_1_1")
    assert isinstance(got, ColourBarItem)
    assert (got.frame_id, got.dataset_id, got.ticks, got.title, got.unit) == (
        "f1", "d1", "list:1,10,100", "Resistivity", "Ω·m")
    assert got.settings.orientation() == Qt.Orientation.Horizontal


def test_borehole_legend_lists_only_classes_present(qgis_app):
    from qgis.core import QgsCategorizedSymbolRenderer, QgsFields, QgsField, QgsFeature
    from qgis.core import QgsFillSymbol, QgsRendererCategory
    from qgis.PyQt.QtCore import QMetaType

    from geophysics_workbench.core.context import LogInterval
    from geophysics_workbench.plates.items import legend_rows
    fields = QgsFields()
    fields.append(QgsField("lithology", QMetaType.Type.QString))
    renderer = QgsCategorizedSymbolRenderer("lithology", [
        QgsRendererCategory(v, QgsFillSymbol.createSimple({}), v)
        for v in ("sand", "clay", "peat")])

    def iv(text):
        f = QgsFeature(fields)
        f["lithology"] = text
        return LogInterval(0.0, 1.0, text, None, f)

    rows = legend_rows([iv("clay"), iv("sand"), iv("sand")], renderer, fields)
    assert [label for label, _sym in rows] == ["sand", "clay"]          # style order
    rows = legend_rows([iv("loam")], None, fields)                      # unstyled: neutral
    assert [label for label, _sym in rows] == ["loam"]


def test_items_registered_once(qgis_app):
    from qgis.core import QgsApplication

    from geophysics_workbench.plates.items import (BOREHOLE_LEGEND_TYPE, COLOUR_BAR_TYPE,
                                                   register_items)
    register_items()
    register_items()
    reg = QgsApplication.layoutItemRegistry()
    assert reg.itemMetadata(COLOUR_BAR_TYPE) is not None
    assert reg.itemMetadata(BOREHOLE_LEGEND_TYPE) is not None


def test_borehole_legend_lists_curves_shown(qgis_app):
    """Spec: the borehole legend also lists the curves shown (name, unit, line style)."""
    import numpy as np

    from geophysics_workbench.core.borehole_curves import CurveStyle
    from geophysics_workbench.core.context import BoreholeView, Curve, ProjectedPoint
    from geophysics_workbench.plates.items import curve_rows

    def curve(key, name, unit):
        return Curve(key, name, unit, np.array([0.0, 1.0]), np.array([1.0, 2.0]))

    a = ProjectedPoint(1.0, 0.0, "B1", "borehole", entry=0,
                       curves=[curve("k:gr", "GR", "API"), curve("k:res", "Res", "")])
    b = ProjectedPoint(2.0, 0.0, "B2", "borehole", entry=0, curves=[curve("k:gr", "GR", "API")])
    styles = {"k:gr": CurveStyle(colour="#ff0000", dash="dot")}
    rows = curve_rows([a, b], {0: BoreholeView(curve_keys=("k:gr",))}, styles)
    assert [label for label, _ in rows] == ["GR (API)"]          # only shown, once
    assert rows[0][1].dash == "dot"
    assert curve_rows([a], {}, styles) == []                      # entry not drawn
