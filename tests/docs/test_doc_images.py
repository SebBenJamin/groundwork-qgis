"""The annotated dialog pictures of the docs (scripts/render_doc_images.py): every widget a
picture marks is named in the plugin, a widget that cannot be marked stops the script, the
markers sit in a gutter beside the grab, and no private path can reach a picture."""
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))


def test_every_marked_widget_is_named_in_the_plugin():
    import render_doc_images as r
    source = "\n".join(p.read_text(encoding="utf-8")
                       for p in (REPO / "groundwork_geophysics" / "ui").glob("*.py"))
    names = set(re.findall(r'setObjectName\("(\w+)"\)', source))
    assert r.PICTURES, "no pictures"
    for picture in r.PICTURES:
        assert picture.targets, picture.name
        for target in picture.targets:
            assert target in names, (picture.name, target)


def test_add_data_picture_targets():
    import render_doc_images as r
    (picture,) = [p for p in r.PICTURES if p.name == "add-data"]
    assert picture.targets == ("table_options", "columns_group", "placement",
                               "preview_group", "status_block")


def _dialog(qgis_app):
    from qgis.PyQt.QtWidgets import QDialog, QLabel, QVBoxLayout
    dialog = QDialog()
    layout = QVBoxLayout(dialog)
    for name in ("a", "b"):
        label = QLabel(name)
        label.setObjectName(name)
        label.setMinimumHeight(60)
        layout.addWidget(label)
    dialog.resize(300, 200)
    dialog.show()
    qgis_app.processEvents()
    return dialog


def test_marker_tops_in_order(qgis_app):
    import render_doc_images as r
    dialog = _dialog(qgis_app)
    tops = r.marker_tops(dialog, ("a", "b"))
    assert len(tops) == 2 and 0 <= tops[0] < tops[1] < dialog.height()


@pytest.mark.parametrize("state", ["missing", "hidden"])
def test_marker_tops_names_the_widget_it_cannot_mark(qgis_app, state):
    import render_doc_images as r
    dialog = _dialog(qgis_app)
    if state == "hidden":
        from qgis.PyQt.QtWidgets import QLabel
        dialog.findChild(QLabel, "b").hide()
        qgis_app.processEvents()
    with pytest.raises(RuntimeError, match="b" if state == "hidden" else "nope"):
        r.marker_tops(dialog, ("a", "b" if state == "hidden" else "nope"))


def test_annotate_adds_gutter_with_markers(qgis_app):
    from qgis.PyQt.QtGui import QColor, QImage

    import render_doc_images as r
    image = QImage(200, 300, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    out = r.annotate(image, [10, 150])
    assert (out.width(), out.height()) == (200 + r.GUTTER, 300)
    cx = r.GUTTER // 2
    for top in (10, 150):                        # just inside the circle's left edge
        assert out.pixelColor(cx - r.MARK_D // 2 + 2, top + r.MARK_D // 2) == QColor(r.MARK_COLOR)
    assert out.pixelColor(r.GUTTER + 5, 5) == QColor("white")        # the grab is untouched
    assert out.pixelColor(cx, 290) != QColor(r.MARK_COLOR)           # gutter is empty elsewhere


def test_annotate_keeps_close_markers_apart(qgis_app):
    from qgis.PyQt.QtGui import QColor, QImage

    import render_doc_images as r
    image = QImage(200, 300, QImage.Format.Format_ARGB32)
    image.fill(QColor("white"))
    out = r.annotate(image, [10, 14])
    x = r.GUTTER // 2 - r.MARK_D // 2 + 2
    assert out.pixelColor(x, 10 + r.MARK_D // 2) == QColor(r.MARK_COLOR)
    assert out.pixelColor(x, 10 + r.MARK_D + 2 + r.MARK_D // 2) == QColor(r.MARK_COLOR)
    assert out.pixelColor(x, 10 + r.MARK_D + 1) != QColor(r.MARK_COLOR)     # a gap between


def test_no_private_path_passes_and_fails(qgis_app, tmp_path):
    from qgis.PyQt.QtWidgets import QLineEdit

    import render_doc_images as r
    dialog = _dialog(qgis_app)
    r.check_no_private_path(dialog, [str(tmp_path)])
    edit = QLineEdit(str(tmp_path / "x.csv").replace("\\", "/").upper(), dialog)
    edit.show()
    with pytest.raises(RuntimeError, match="path"):
        r.check_no_private_path(dialog, [str(tmp_path)])
