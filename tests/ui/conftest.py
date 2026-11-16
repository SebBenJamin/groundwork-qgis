"""UI test helpers (``fake_iface`` lives in tests/conftest.py)."""
import pytest


@pytest.fixture
def warnings_shown(monkeypatch):
    """Record QMessageBox.warning calls instead of blocking on a modal box."""
    from qgis.PyQt.QtWidgets import QMessageBox

    shown = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda parent, title, text, *a, **k: shown.append(text)))
    return shown


@pytest.fixture
def project_store(qgis_app, tmp_path):
    """(new workbench store w.gpkg in EPSG:25832, the QgsProject showing it)."""
    from qgis.core import QgsProject

    from groundwork_geophysics.ui.project_actions import new_store

    prj = QgsProject()
    return new_store(tmp_path / "w.gpkg", "EPSG:25832", prj), prj
