import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import shutil

import numpy as np
import pytest

# Make the repo root importable so `import geophysics_workbench` works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def store_with_model(tmp_path):
    """Store with one profile (0,0,100) -> (50,0,102), its station set and one R2 model
    dataset (a copy of f001_res.dat in tmp_path). Returns (store, profile, source_path)."""
    from geophysics_workbench.core.model import Dataset, file_fingerprint, profile_from_stations
    from geophysics_workbench.store.gpkg_store import ProjectStore

    src = tmp_path / "f001_res.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p, s = profile_from_stations("P1", "EPSG:25832", np.array([[0, 0, 100], [50, 0, 102.0]]))
    st.save_profile(p); st.save_station_set(s)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("d1", p.id, s.id, "ert_model", str(src), mt, sha, "r2_res_dat",
                            {"z_kind": "elevation"}, {}, name="P1 model"))
    return st, p, src


@pytest.fixture(scope="session")
def qgis_app():
    from qgis.core import QgsApplication

    app = QgsApplication([], True)
    app.initQgis()
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
