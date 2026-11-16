"""Write the four shipped plate templates (A4/A3, landscape/portrait) into
``groundwork_geophysics/plates/templates``. Run with QGIS's Python:

    python-qgis.bat scripts/make_plate_templates.py

Every template carries the fixed item IDs the plate builder fills (see docs/user/plates.md):
the section area the builder divides among the frames, the mini-map with north arrow and
bar scale, the interpretation and borehole legends, the field-notes list and the stamp area (the builder rules it into the title block).
Positions and fonts are a starting point; users restyle them in QGIS's layout designer."""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)

from qgis.core import (Qgis, QgsApplication, QgsFillSymbol, QgsLayoutItemLabel,  # noqa: E402
                       QgsLayoutItemLegend, QgsLayoutItemMap, QgsLayoutItemPicture,
                       QgsLayoutItemScaleBar, QgsLayoutItemShape, QgsLayoutMeasurement,
                       QgsLayoutPoint, QgsLayoutSize, QgsPrintLayout, QgsProject,
                       QgsReadWriteContext, QgsTextFormat, QgsUnitTypes)
from qgis.PyQt.QtCore import Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QFont  # noqa: E402

MM = QgsUnitTypes.LayoutMillimeters
PAGES = {"A4_landscape": (297.0, 210.0), "A4_portrait": (210.0, 297.0),
         "A3_landscape": (420.0, 297.0), "A3_portrait": (297.0, 420.0)}
MARGIN = 10.0
GAP = 4.0
STAMP_MIN_W = 80.0   # mm: the stamp's cells stay readable (captions 5.5 pt, five date-row cells)
STAMP_MIN_H = 60.0


def _place(item, x, y, w, h):
    item.attemptMove(QgsLayoutPoint(x, y, MM))
    item.attemptResize(QgsLayoutSize(w, h, MM))


def _fmt(size, bold=False):
    fmt = QgsTextFormat()
    font = QFont("Arial")
    font.setBold(bold)
    fmt.setFont(font)
    fmt.setSize(size)
    fmt.setColor(QColor(30, 30, 30))
    return fmt


def _label(layout, item_id, text, x, y, w, h, size=8.0, bold=False):
    label = QgsLayoutItemLabel(layout)
    label.setId(item_id)
    label.setText(text)
    label.setTextFormat(_fmt(size, bold))
    label.setVAlign(Qt.AlignmentFlag.AlignTop)
    layout.addLayoutItem(label)
    _place(label, x, y, w, h)
    return label


def _box(layout, item_id, x, y, w, h, stroke="80,80,80", width="0.3", export=True):
    shape = QgsLayoutItemShape(layout)
    shape.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
    shape.setId(item_id)
    shape.setSymbol(QgsFillSymbol.createSimple({"style": "no", "outline_color": stroke,
                                                "outline_width": width,
                                                "outline_style": "solid" if export else "dash"}))
    shape.setExcludeFromExports(not export)
    layout.addLayoutItem(shape)
    _place(shape, x, y, w, h)
    return shape


def _minimap(layout, x, y, w, h):
    m = QgsLayoutItemMap(layout)
    m.setId("wb_minimap")
    m.setFrameEnabled(True)
    m.setFrameStrokeWidth(QgsLayoutMeasurement(0.3, MM))
    layout.addLayoutItem(m)
    _place(m, x, y, w, h)
    arrow = QgsLayoutItemPicture(layout)
    arrow.setId("wb_north")
    arrow.setPicturePath(os.path.join(QgsApplication.pkgDataPath(), "svg", "arrows",
                                      "NorthArrow_02.svg"))
    arrow.setLinkedMap(m)
    arrow.setNorthMode(QgsLayoutItemPicture.NorthMode.GridNorth)
    arrow.setBackgroundEnabled(False)
    layout.addLayoutItem(arrow)
    _place(arrow, x + w - 11, y + 2, 9, 11)
    _label(layout, "wb_north_text", "Grid north", x + w - 16, y + 13.5, 15, 4, 6.0)
    bar = QgsLayoutItemScaleBar(layout)
    bar.setId("wb_map_scalebar")
    bar.setStyle("Single Box")
    bar.setLinkedMap(m)
    bar.applyDefaultSize(QgsUnitTypes.DistanceMeters)
    bar.setNumberOfSegmentsLeft(0)
    bar.setNumberOfSegments(2)
    bar.setHeight(1.5)
    bar.setTextFormat(_fmt(6.0))
    bar.setBackgroundEnabled(True)
    layout.addLayoutItem(bar)
    _place(bar, x + 2, y + h - 10, min(45.0, w * 0.5), 8)


def _legend(layout, item_id, title, x, y, w, h):
    legend = QgsLayoutItemLegend(layout)
    legend.setId(item_id)
    legend.setTitle(title)
    legend.setSyncMode(Qgis.LegendSyncMode.Manual)
    legend.model().rootGroup().removeAllChildren()
    legend.setResizeToContents(False)
    legend.setFrameEnabled(False)
    layout.addLayoutItem(legend)
    _place(legend, x, y, w, h)


def _borehole_legend(layout, x, y, w, h):
    from groundwork_geophysics.plates.items import BoreholeLegendItem
    _label(layout, "wb_legend_boreholes_title", "Boreholes", x, y, w, 5, 9.0, True)
    item = BoreholeLegendItem(layout)
    item.setId("wb_legend_boreholes")
    layout.addLayoutItem(item)
    _place(item, x, y + 6, w, h - 6)


def _stamp_area(layout, x, y, w, h):
    """The stamp's area: the builder rules it into cells when a plate is made."""
    _box(layout, "wb_stamp_area", x, y, w, h)


def build(name):
    page_w, page_h = PAGES[name]
    portrait = page_h > page_w
    layout = QgsPrintLayout(QgsProject.instance())
    layout.initializeDefaults()
    layout.pageCollection().page(0).setPageSize(QgsLayoutSize(page_w, page_h, MM))
    layout.setName(name)
    inner_w, inner_h = page_w - 2 * MARGIN, page_h - 2 * MARGIN
    area_h = inner_h * (0.58 if portrait else 0.64)
    _box(layout, "wb_section_area", MARGIN, MARGIN, inner_w, area_h, "150,150,150", "0.2",
         export=False)
    y0 = MARGIN + area_h + GAP
    strip_h = page_h - MARGIN - y0
    if portrait:
        bottom_h = max(strip_h * 0.45 - GAP, STAMP_MIN_H)
        top_h = strip_h - GAP - bottom_h
        cols = (inner_w - 2 * GAP) * 0.42, (inner_w - 2 * GAP) * 0.30, (inner_w - 2 * GAP) * 0.28
        x = MARGIN
        _minimap(layout, x, y0, cols[0], top_h)
        x += cols[0] + GAP
        _legend(layout, "wb_legend_interp", "Interpretation", x, y0, cols[1], top_h)
        x += cols[1] + GAP
        _borehole_legend(layout, x, y0, cols[2], top_h)
        y1 = y0 + top_h + GAP
        notes_w = (inner_w - GAP) * 0.52
        _label(layout, "wb_field_notes", "Field notes", MARGIN, y1, notes_w, bottom_h, 7.0)
        _stamp_area(layout, MARGIN + notes_w + GAP, y1, inner_w - notes_w - GAP, bottom_h)
    else:
        parts = (0.25, 0.19, 0.17, 0.19)          # mini-map, legends, field notes
        free = inner_w - 4 * GAP
        stamp_w = max(free * 0.20, STAMP_MIN_W)
        widths = [(free - stamp_w) * p / sum(parts) for p in parts] + [stamp_w]
        x = MARGIN
        _minimap(layout, x, y0, widths[0], strip_h)
        x += widths[0] + GAP
        _legend(layout, "wb_legend_interp", "Interpretation", x, y0, widths[1], strip_h)
        x += widths[1] + GAP
        _borehole_legend(layout, x, y0, widths[2], strip_h)
        x += widths[2] + GAP
        _label(layout, "wb_field_notes", "Field notes", x, y0, widths[3], strip_h, 7.0)
        x += widths[3] + GAP
        _stamp_area(layout, x, y0, widths[4], strip_h)
    return layout


def main(out_dir=None):
    from groundwork_geophysics.plates.items import register_items
    register_items()
    out_dir = out_dir or os.path.join(ROOT, "groundwork_geophysics", "plates", "templates")
    os.makedirs(out_dir, exist_ok=True)
    for name in PAGES:
        layout = build(name)
        path = os.path.join(out_dir, f"{name}.qpt")
        if not layout.saveAsTemplate(path, QgsReadWriteContext()):
            raise SystemExit(f"could not write {path}")
        print("wrote", path)


if __name__ == "__main__":
    app = QgsApplication([], False)
    app.initQgis()
    main(sys.argv[1] if len(sys.argv) > 1 else None)
    sys.stdout.flush()
    os._exit(0)
