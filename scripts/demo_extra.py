"""Additions to the demo builder (scripts/build_demo.py stays under ~400 lines).

- ``make_p4``: a fourth line, P4, for the release note's "create a profile from a CSV"
  walkthrough. Only its station file is written (``data/stations/P4_electrodes.csv``); it
  is not in the demo store, so the user's new profile duplicates nothing.
- ``set_author`` / ``strip_save_user``: keep personal data out of ``demo_project.qgz``.
  QGIS writes the OS account and full name of whoever saves a project into the
  ``saveUser`` / ``saveUserFull`` attributes and, for new projects, the metadata author.
- ``powerline_layer`` / ``add_context``: the project's powerline and context layers (pylons,
  boreholes and logs, geology, DEM) with their styles and 'Context layers…' settings. These
  need QGIS; the files come from demo_context.py.
"""
from __future__ import annotations

import math
import re
import zipfile
from configparser import ConfigParser
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METADATA = ROOT / "geophysics_workbench" / "metadata.txt"
P4_SHIFT = -140.0          # m along P1's direction: P3 lies 70 m on one side, P4 70 m on the other
P4_LENGTH = 235.0
_SAVE_USER = re.compile(rb'(saveUser(?:Full)?)="[^"]*"')
VOLTAGE_LABEL = ("CASE WHEN to_int(\"voltage\") > 0 "
                 "THEN format('%1 kV', to_int(\"voltage\") // 1000) END")
GEOLOGY_OPACITY = 0.4


# ---------------------------------------------------------------- P4
def make_p4(p1, p3):
    """P4: parallel to P3, mirrored to the other side of the powerline, crossing P1 and P2.
    ``p1``/``p3`` are build_demo ``Profile`` objects; the result is one too."""
    u = (math.cos(p1.azimuth), math.sin(p1.azimuth))
    v = (math.cos(p3.azimuth), math.sin(p3.azimuth))
    cx = p3.x0 + v[0] * p3.length / 2 + P4_SHIFT * u[0]
    cy = p3.y0 + v[1] * p3.length / 2 + P4_SHIFT * u[1]
    return replace(p3, name="P4", x0=cx - v[0] * P4_LENGTH / 2, y0=cy - v[1] * P4_LENGTH / 2,
                   length=P4_LENGTH)


# ---------------------------------------------------------------- personal data
def plugin_author(path: Path = METADATA) -> str:
    cp = ConfigParser()
    cp.read(path, encoding="utf-8")
    return cp["general"]["author"]


def set_author(project, author: str | None = None) -> None:
    """Project metadata author = the plugin author (not the account that runs the build)."""
    md = project.metadata()
    md.setAuthor(author or plugin_author())
    project.setMetadata(md)


def strip_save_user(qgz: Path) -> None:
    """Blank the ``saveUser`` / ``saveUserFull`` attributes of the .qgs inside ``qgz``."""
    qgz = Path(qgz)
    with zipfile.ZipFile(qgz) as zf:
        entries = [(info, zf.read(info.filename)) for info in zf.infolist()]
    tmp = qgz.with_suffix(".qgz.part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for info, data in entries:
            if info.filename.lower().endswith(".qgs"):
                data = _SAVE_USER.sub(rb'\1=""', data)
            zf.writestr(info, data)
    tmp.replace(qgz)


# ---------------------------------------------------------------- project layers (QGIS)
def _labels(layer, expression: str, size: float, rgb, line: bool = False) -> None:
    from qgis.core import QgsPalLayerSettings, QgsTextFormat, QgsVectorLayerSimpleLabeling
    from qgis.PyQt.QtGui import QColor

    settings = QgsPalLayerSettings()
    settings.isExpression = True
    settings.fieldName = expression
    if line:
        settings.placement = QgsPalLayerSettings.Placement.Line
    fmt = QgsTextFormat()
    fmt.setSize(size)
    fmt.setColor(QColor(*rgb))
    buffer = fmt.buffer()
    buffer.setEnabled(True)
    fmt.setBuffer(buffer)
    settings.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(settings))
    layer.setLabelsEnabled(True)


def powerline_layer(path: Path):
    from qgis.core import QgsLineSymbol, QgsSingleSymbolRenderer, QgsVectorLayer

    layer = QgsVectorLayer(str(path), "Powerline (OSM)", "ogr")
    symbol = QgsLineSymbol.createSimple({"color": "220,0,0", "width": "0.7",
                                         "line_style": "dash"})
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    _labels(layer, VOLTAGE_LABEL, 9.0, (180, 0, 0), line=True)
    return layer


def _point_layer(source: str, name: str, shape: str, rgb, size: float, label: str):
    from qgis.core import QgsMarkerSymbol, QgsSingleSymbolRenderer, QgsVectorLayer

    layer = QgsVectorLayer(source, name, "ogr")
    symbol = QgsMarkerSymbol.createSimple({"name": shape, "color": ",".join(map(str, rgb)),
                                           "outline_color": "40,40,40", "size": str(size)})
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    _labels(layer, f'"{label}"', 8.0, (40, 40, 40))
    return layer


def _geology_layer(path: Path):
    """40 % opaque, one category per ``unit`` in its lithology colour."""
    from qgis.core import (QgsCategorizedSymbolRenderer, QgsFillSymbol, QgsRendererCategory,
                           QgsVectorLayer)

    from geophysics_workbench.core.lithology import lithology_colour

    layer = QgsVectorLayer(str(path), "Surface geology (synthetic)", "ogr")
    units = sorted(layer.uniqueValues(layer.fields().indexOf("unit")))
    categories = []
    for unit in units:
        symbol = QgsFillSymbol.createSimple({
            "color": ",".join(map(str, lithology_colour(unit))), "outline_color": "90,90,90",
            "outline_width": "0.2"})
        categories.append(QgsRendererCategory(unit, symbol, unit))
    layer.setRenderer(QgsCategorizedSymbolRenderer("unit", categories))
    layer.setOpacity(GEOLOGY_OPACITY)
    return layer


def add_context(project, context_dir: Path, powerline) -> None:
    """Context layers around ``powerline`` in the layer tree (pylons, boreholes and logs above
    it; geology and the hidden DEM below) and the context settings that use them."""
    from qgis.core import QgsRasterLayer, QgsVectorLayer

    from geophysics_workbench.core.context_settings import (BandSetting, BoreholeSetting,
                                                            ContextSettings, LineLayerSetting,
                                                            PointLayerSetting)
    from geophysics_workbench.ui.context_dialog import write_settings

    gpkg = context_dir / "boreholes.gpkg"
    pylons = _point_layer(str(context_dir / "pylons.geojson"), "Pylons (from OSM)", "triangle",
                          (60, 60, 60), 3.2, "name")
    boreholes = _point_layer(f"{gpkg}|layername=boreholes", "Boreholes", "circle",
                             (30, 90, 200), 2.6, "id")
    logs = QgsVectorLayer(f"{gpkg}|layername=borehole_logs", "Borehole logs", "ogr")
    geology = _geology_layer(context_dir / "geology.geojson")
    dem = QgsRasterLayer(str(context_dir / "dem.tif"), "DEM (synthetic)", "gdal")
    root = project.layerTreeRoot()
    at = root.children().index(root.findLayer(powerline.id()))
    for layer, index in ((pylons, at), (boreholes, at + 1), (logs, at + 2),
                         (geology, at + 4), (dem, at + 5)):
        if not layer.isValid():
            raise RuntimeError(f"demo layer {layer.name()} is not valid")
        project.addMapLayer(layer, False)
        root.insertLayer(index, layer)
    root.findLayer(dem.id()).setItemVisibilityChecked(False)
    write_settings(project, ContextSettings(
        line_layers=[LineLayerSetting(powerline.id(), "voltage", powerline=True)],
        point_layers=[PointLayerSetting(pylons.id(), "name")],
        borehole=BoreholeSetting(boreholes.id(), "id", "elevation", logs.id(), "borehole_id",
                                 "top", "bottom", "lithology"),
        band=BandSetting(geology.id(), "unit"),
        dem_layer_id=dem.id(), buffer=25.0, near_miss=10.0, dem_tolerance=1.0))
