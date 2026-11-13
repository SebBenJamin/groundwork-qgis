"""The suite-wide guard (tests/conftest.py): a real modal box fails the test instead of
blocking the offscreen run."""
import pytest


def test_an_unstubbed_box_fails_the_test_at_once(qgis_app, no_modal_boxes):
    from qgis.PyQt.QtWidgets import QDialog, QMessageBox

    for name in ("warning", "question", "information", "critical"):
        with pytest.raises(pytest.fail.Exception, match=f"QMessageBox.{name}"):
            getattr(QMessageBox, name)(None, "Title", "Text")
    with pytest.raises(pytest.fail.Exception, match="QMessageBox.exec"):
        QMessageBox().exec()
    with pytest.raises(pytest.fail.Exception, match="QDialog.exec"):
        QDialog().exec()
    assert len(no_modal_boxes) == 6
    no_modal_boxes.clear()                    # recorded on purpose: not a failure here


def test_a_stubbed_box_is_left_to_the_test(qgis_app, warnings_shown):
    from qgis.PyQt.QtWidgets import QMessageBox

    QMessageBox.warning(None, "Title", "Text")
    assert warnings_shown == ["Text"]


def test_monkeypatch_undo_in_a_test_keeps_the_guard(qgis_app, monkeypatch, no_modal_boxes):
    from qgis.PyQt.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    monkeypatch.undo()
    with pytest.raises(pytest.fail.Exception, match="QMessageBox.warning"):
        QMessageBox.warning(None, "Title", "Text")
    no_modal_boxes.clear()
