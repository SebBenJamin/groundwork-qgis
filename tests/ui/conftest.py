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
