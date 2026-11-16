"""The stamp grid: boxes, captions, value labels and the logo picture, built once into the
layout's ``wb_stamp_area``."""
import pytest

AREA = (10.0, 10.0, 80.0, 64.4)


@pytest.fixture
def layout(qgis_app, tmp_path):
    from qgis.core import (QgsLayoutItemShape, QgsLayoutPoint, QgsLayoutSize, QgsPrintLayout,
                           QgsProject, QgsUnitTypes)
    project = QgsProject.instance()
    project.clear()
    project.setFileName(str(tmp_path / "p.qgz"))
    lay = QgsPrintLayout(project)
    lay.initializeDefaults()
    area = QgsLayoutItemShape(lay)
    area.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
    area.setId("wb_stamp_area")
    lay.addLayoutItem(area)
    mm = QgsUnitTypes.LayoutMillimeters
    area.attemptMove(QgsLayoutPoint(AREA[0], AREA[1], mm))
    area.attemptResize(QgsLayoutSize(AREA[2], AREA[3], mm))
    yield lay
    project.clear()


def _rect(item):
    from groundwork_geophysics.plates.stamp import item_rect
    return item_rect(item)


def _inside(inner, outer, tol=0.01):
    x, y, w, h = inner
    ox, oy, ow, oh = outer
    return x >= ox - tol and y >= oy - tol and x + w <= ox + ow + tol and y + h <= oy + oh + tol


def _stamp_ids(lay):
    return {i.id() for i in lay.items() if hasattr(i, "id") and i.id().startswith("wb_stamp_")}


def test_build_stamp_creates_every_cell(layout):
    from groundwork_geophysics.plates.stamp import CELLS, build_stamp
    build_stamp(layout, layout.itemById("wb_stamp_area"))
    for cell in CELLS:
        if cell.key == "logo":
            assert layout.itemById("wb_stamp_logo") is not None
            continue
        assert layout.itemById(f"wb_stamp_{cell.key}") is not None, cell.key
        caption = layout.itemById(f"wb_stamp_{cell.key}_caption")
        assert (caption is not None) == bool(cell.caption), cell.key
        if cell.caption:
            assert caption.text() == cell.caption
    assert layout.itemById("wb_stamp_survey_caption").text() == "SURVEY DETAILS"
    assert layout.itemById("wb_stamp_author_caption").text() == "DRAWN"


def test_boxes_inside_area_no_overlap(layout):
    from groundwork_geophysics.plates.stamp import build_stamp
    build_stamp(layout, layout.itemById("wb_stamp_area"))
    boxes = [_rect(i) for i in layout.items()
             if hasattr(i, "id") and i.id().endswith("_box")]
    assert len(boxes) == 12
    for b in boxes:
        assert _inside(b, AREA), b
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            w = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
            h = min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1])
            assert w <= 0.01 or h <= 0.01, (a, b)


def test_labels_inside_their_boxes(layout):
    from groundwork_geophysics.plates.stamp import CELLS, build_stamp
    build_stamp(layout, layout.itemById("wb_stamp_area"))
    for cell in CELLS:
        box_key = cell.box_key
        box = _rect(layout.itemById(f"wb_stamp_{box_key}_box"))
        ids = [f"wb_stamp_{cell.key}"] + ([f"wb_stamp_{cell.key}_caption"] if cell.caption else [])
        for item_id in ids:
            assert _inside(_rect(layout.itemById(item_id)), box), item_id


def test_caption_size_not_below_5pt(layout):
    from groundwork_geophysics.plates.stamp import CELLS, build_stamp
    build_stamp(layout, layout.itemById("wb_stamp_area"))
    for cell in CELLS:
        if cell.caption:
            item = layout.itemById(f"wb_stamp_{cell.key}_caption")
            assert item.textFormat().size() >= 5.0


def test_build_stamp_once(layout):
    from groundwork_geophysics.plates.stamp import build_stamp
    build_stamp(layout, layout.itemById("wb_stamp_area"))
    first = len(layout.items())
    build_stamp(layout, layout.itemById("wb_stamp_area"))
    assert len(layout.items()) == first


def test_stamp_logo_missing_file(layout, tmp_path):
    from qgis.core import QgsLayoutExporter

    from groundwork_geophysics.plates.build import set_plate_logo
    from groundwork_geophysics.plates.stamp import build_stamp
    set_plate_logo(layout.project(), str(tmp_path / "gone.png"))
    build_stamp(layout, layout.itemById("wb_stamp_area"))
    picture = layout.itemById("wb_stamp_logo")
    picture.refresh()
    assert picture.evaluatedPath() == ""
    result = QgsLayoutExporter(layout).exportToImage(
        str(tmp_path / "plate.png"), QgsLayoutExporter.ImageExportSettings())
    assert result == QgsLayoutExporter.ExportResult.Success


def test_stamp_logo_shows_existing_file(layout, tmp_path):
    from pathlib import Path

    from qgis.PyQt.QtGui import QImage

    from groundwork_geophysics.plates.build import set_plate_logo
    from groundwork_geophysics.plates.stamp import build_stamp
    img = QImage(8, 8, QImage.Format.Format_RGB32)
    img.fill(0)
    img.save(str(tmp_path / "logo.png"))
    set_plate_logo(layout.project(), str(tmp_path / "logo.png"))
    build_stamp(layout, layout.itemById("wb_stamp_area"))
    picture = layout.itemById("wb_stamp_logo")
    picture.refresh()
    assert Path(picture.evaluatedPath()) == tmp_path / "logo.png"
