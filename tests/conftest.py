import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

import pytest

# Make the repo root importable so `import geophysics_workbench` works.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="session")
def qgis_app():
    from qgis.core import QgsApplication

    app = QgsApplication([], True)
    app.initQgis()
    yield app
    app.exitQgis()
