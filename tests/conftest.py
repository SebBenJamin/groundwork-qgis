import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import shutil

import numpy as np
import pytest

# Make the repo root importable so `import groundwork_geophysics` works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def store_with_model(tmp_path):
    """Store with one profile (0,0,100) -> (50,0,102), its station set and one R2 model
    dataset (a copy of f001_res.dat in tmp_path). Returns (store, profile, source_path)."""
    from groundwork_geophysics.core.model import Dataset, file_fingerprint, profile_from_stations
    from groundwork_geophysics.store.gpkg_store import ProjectStore

    src = tmp_path / "f001_res.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p, s = profile_from_stations("P1", "EPSG:25832", np.array([[0, 0, 100], [50, 0, 102.0]]))
    st.save_profile(p); st.save_station_set(s)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("d1", p.id, s.id, "ert_model", str(src), mt, sha, "r2_res_dat",
                            {"z_kind": "elevation"}, {}, name="P1 model"))
    return st, p, src


_BOXES = ("warning", "question", "information", "critical")
#: Qt's static pickers run their own event loop in C++, past a patched ``exec``
_PICKERS = {"QFileDialog": ("getOpenFileName", "getOpenFileNames", "getSaveFileName",
                            "getExistingDirectory"),
            "QInputDialog": ("getText", "getItem", "getInt", "getDouble", "getMultiLineText"),
            "QColorDialog": ("getColor",), "QFontDialog": ("getFont",)}


@pytest.fixture(autouse=True)
def no_modal_boxes():
    """Fail the test at once when it would open a real modal box (a static
    QMessageBox.warning/question/information/critical, QMessageBox.exec, QDialog.exec, or a
    static file, input, colour or font picker) that the test did not stub: offscreen, such a
    box blocks the whole suite. Autouse
    fixtures run first, so a test's own stubs (``warnings_shown``, monkeypatches of a
    dialog's ``exec``) replace these; the guard has its own MonkeyPatch, so a test's
    ``monkeypatch.undo()`` does not lift it. Unstubbed calls are also failed at teardown,
    in case a slot swallowed the first failure. Yields the list of boxes refused."""
    from qgis.PyQt import QtWidgets
    from qgis.PyQt.QtWidgets import QDialog, QMessageBox

    opened = []

    def refuse(what):
        def call(*args, **kwargs):
            opened.append(what)
            pytest.fail(f"a real modal {what} would open: stub it in the test "
                        f"(warnings_shown, or monkeypatch)", pytrace=False)
        return call

    with pytest.MonkeyPatch.context() as guard:
        for name in _BOXES:
            guard.setattr(QMessageBox, name, staticmethod(refuse(f"QMessageBox.{name}")))
        guard.setattr(QMessageBox, "exec", refuse("QMessageBox.exec"))
        guard.setattr(QDialog, "exec", refuse("QDialog.exec"))
        for owner, names in _PICKERS.items():
            cls = getattr(QtWidgets, owner)
            for name in names:
                guard.setattr(cls, name, staticmethod(refuse(f"{owner}.{name}")))
        yield opened
    if opened:
        pytest.fail(f"real modal boxes were opened: {opened}", pytrace=False)


@pytest.fixture(autouse=True)
def models_read_at_once(request, monkeypatch):
    """The plugin reads models in a QGIS task; a test about something else gets them at
    once (as if the task had finished). Tests marked ``background_reads`` use the task."""
    if request.node.get_closest_marker("background_reads"):
        yield
        return
    from groundwork_geophysics.section.data import run_job
    from groundwork_geophysics.section.model_reading import ModelReader

    def at_once(self, profile_ids, done):
        jobs = [j for j in self.provider.unread(profile_ids)
                if (j.dataset_id, j.key) not in self._failed]
        if not jobs:
            return False
        for job in jobs:
            try:
                self.provider.take(job, run_job(job))
            except Exception:
                self._failed.add((job.dataset_id, job.key))
        done(True)
        return True
    monkeypatch.setattr(ModelReader, "request", at_once)
    from groundwork_geophysics.ui import view3d_prepare
    real_pending = view3d_prepare.pending_3d

    def prepared_at_once(*args):
        for job in real_pending(*args):
            view3d_prepare.run_job3d(job)
        return []
    monkeypatch.setattr(view3d_prepare, "pending_3d", prepared_at_once)
    yield


@pytest.fixture(scope="session")
def qgis_app():
    from qgis.core import QgsApplication

    app = QgsApplication([], True)
    app.initQgis()
    from qgis.PyQt.QtCore import QLocale
    QLocale.setDefault(QLocale.c())     # numbers as "24.5" whatever the machine's locale
    import qgis.testing
    qgis.testing.QGISAPP = app          # so qgis.testing helpers never build a second app
    yield app
    app.exitQgis()


class FakeIface:
    """Just enough of QgisInterface for the section dock, map link, dialogs and plugin."""

    def __init__(self):
        from qgis.gui import QgsMapCanvas, QgsMessageBar
        from qgis.PyQt.QtWidgets import QMainWindow

        self._window = QMainWindow()
        self._window.resize(1200, 800)
        self._canvas = QgsMapCanvas(self._window)
        self._window.setCentralWidget(self._canvas)
        self._bar = QgsMessageBar(self._window)
        self._active_layer = None
        self._window.show()

    def mainWindow(self):
        return self._window

    def mapCanvas(self):
        return self._canvas

    def messageBar(self):
        return self._bar

    def activeLayer(self):
        return self._active_layer

    def setActiveLayer(self, layer):
        self._active_layer = layer

    def addDockWidget(self, area, dock):
        self._window.addDockWidget(area, dock)

    def removeDockWidget(self, dock):
        self._window.removeDockWidget(dock)


@pytest.fixture
def fake_iface(qgis_app):
    iface = FakeIface()
    yield iface
    iface.mainWindow().close()
    iface.mainWindow().deleteLater()
    qgis_app.processEvents()
