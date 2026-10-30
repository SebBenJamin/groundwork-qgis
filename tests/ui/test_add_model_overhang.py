"""Add ERT model warns when the model reaches far beyond the stations (0.1.1, F1)."""
import shutil
from pathlib import Path

import numpy as np
import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "ert"


@pytest.fixture
def questions(monkeypatch):
    """Record QMessageBox.question calls; answer with ``questions.answer``."""
    from qgis.PyQt.QtWidgets import QMessageBox

    class Recorder(list):
        answer = QMessageBox.StandardButton.No

    asked = Recorder()

    def fake(parent, title, text, buttons=None, default=None):
        asked.append((text, buttons, default))
        return asked.answer

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake))
    return asked


@pytest.fixture
def p4(qgis_app, tmp_path):
    """Store with profile P4: 11 stations every 5 m (chainage 0 .. 50), and a copy of the
    Zond fixture (cell centres x 1 .. 9, cells 0 .. 10 m)."""
    from geophysics_workbench.core.model import profile_from_stations
    from geophysics_workbench.store.gpkg_store import ProjectStore

    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    xyz = np.column_stack([np.arange(11) * 5.0, np.zeros(11), np.full(11, 100.0)])
    p, s = profile_from_stations("P4", "EPSG:25832", xyz)
    st.save_profile(p)
    st.save_station_set(s)
    src = tmp_path / "zond_model.dat"
    shutil.copy(FIXTURES / "zond_model.dat", src)
    return st, p, src


def _dialog(fake_iface, st, p, src, offset):
    from geophysics_workbench.ui.add_model_dialog import AddModelDialog

    dlg = AddModelDialog(fake_iface, st, p.id)
    dlg.set_file(src)
    dlg.z_combo.setCurrentIndex(dlg.z_combo.findData("elevation"))
    dlg.offset_spin.setValue(offset)
    return dlg


def _close(dialog, qgis_app):
    dialog.close()
    dialog.deleteLater()
    qgis_app.processEvents()


def test_overhang_beyond_the_limit_warns_and_asks(qgis_app, fake_iface, p4, questions,
                                                  warnings_shown):
    from qgis.PyQt.QtWidgets import QMessageBox

    st, p, src = p4
    dlg = _dialog(fake_iface, st, p, src, 55.0)        # model 55 .. 65 m, stations 0 .. 50
    try:
        text = dlg.warning.text()
        assert dlg.warning.isVisibleTo(dlg)
        assert "P4" in text and "55–65 m" in text and "0–50 m" in text
        assert "15 m beyond the last station" in text
        dlg.accept()                                    # answered No: nothing saved
        assert len(questions) == 1 and questions[0][2] == QMessageBox.StandardButton.No
        assert "P4" in questions[0][0]
        assert dlg.result() == 0 and st.datasets(p.id) == []
        questions.answer = QMessageBox.StandardButton.Yes
        dlg.accept()
        assert len(questions) == 2 and dlg.result() == 1 and len(st.datasets(p.id)) == 1
    finally:
        _close(dlg, qgis_app)


def test_overhang_at_the_start_names_the_first_station(qgis_app, fake_iface, p4, questions):
    st, p, src = p4
    dlg = _dialog(fake_iface, st, p, src, -20.0)       # model -20 .. -10 m
    try:
        assert "20 m before the first station" in dlg.warning.text()
    finally:
        _close(dlg, qgis_app)


def test_overhang_within_the_limit_stays_silent(qgis_app, fake_iface, p4, questions):
    st, p, src = p4
    dlg = _dialog(fake_iface, st, p, src, 50.0)        # model 50 .. 60: 10 m = the limit
    try:
        assert not dlg.warning.isVisibleTo(dlg) and dlg.warning.text() == ""
        dlg.accept()
        assert questions == [] and dlg.result() == 1 and len(st.datasets(p.id)) == 1
    finally:
        _close(dlg, qgis_app)
