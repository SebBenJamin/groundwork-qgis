"""A section whose reader needs a library that is not installed (segyio): the layer row says so
and its right-click menu offers to install it; once installed the section is read again."""
import time

import numpy as np
import pytest

pytest.importorskip("segyio")

from groundwork_geophysics.core.model import (Dataset, file_fingerprint,  # noqa: E402
                                              profile_from_polyline)
from groundwork_geophysics.store.gpkg_store import ProjectStore  # noqa: E402
from segy_files import write_segy  # noqa: E402

INSTALL = "Install segyio…"


def _wait(qgis_app, done, seconds=20.0):
    end = time.monotonic() + seconds
    while not done() and time.monotonic() < end:
        qgis_app.processEvents()
        time.sleep(0.01)
    assert done()


@pytest.fixture
def no_segyio(monkeypatch):
    """The SEG-Y reader raises ``MissingLibrary("segyio")`` until ``state["installed"]``."""
    from groundwork_geophysics import libs
    from groundwork_geophysics.readers import segy
    real = segy._segyio
    state = {"installed": False}

    def fake():
        if not state["installed"]:
            raise libs.MissingLibrary("segyio")
        return real()
    monkeypatch.setattr(segy, "_segyio", fake)
    return state


@pytest.fixture
def world(qgis_app, tmp_path):
    """(provider, layer list, dataset id) of a profile holding one SEG-Y section and, as
    ``other``, a model whose file is missing."""
    from qgis.gui import QgsMessageBar

    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.section.layer_list import LayerList
    store = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p = profile_from_polyline("P1", "EPSG:25832", np.array([[0.0, 0.0], [100.0, 0.0]]))
    store.save_profile(p)
    path = write_segy(tmp_path / "line.sgy", np.ones((11, 20), np.float32), dt_us=1000)
    mt, sha = file_fingerprint(path)
    store.save_dataset(Dataset("s1", p.id, "", "refl_section", str(path), mt, sha, "segy",
                               {"position": "spacing", "spacing": 10.0, "velocity": 2000.0,
                                "zero": "datum", "datum": 100.0}, {}, name="Line 1"))
    store.save_dataset(Dataset("m1", p.id, "", "ert_model", str(tmp_path / "gone.dat"), 0.0,
                               "", "", {}, {}, name="Gone"))
    provider = SectionDataProvider(store)
    ll = LayerList()
    ll.message_bar = QgsMessageBar()
    provider.on_change.append(lambda: ll.set_layers(provider, provider.layers(p.id)))
    yield provider, ll, p.id
    ll.deleteLater()
    ll.message_bar.deleteLater()
    qgis_app.processEvents()


def _layer(provider, pid, did):
    return next(la for la in provider.layers(pid) if la.dataset.id == did)


def _texts(menu):
    return [a.text() for a in menu.actions() if a.text()]


def _bar_texts(bar):
    from qgis.PyQt.QtWidgets import QLabel
    out = []
    for item in bar.items():
        out += [item.title(), item.text()]
        out += [w.text() for w in item.findChildren(QLabel)]
    return " ".join(out)


@pytest.fixture
def answer_yes(monkeypatch):
    from qgis.PyQt.QtWidgets import QMessageBox
    asked = []

    def question(parent, title, text, buttons, default):
        asked.append((title, text, default))
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", staticmethod(question))
    return asked


def test_the_row_of_a_section_without_segyio_offers_the_install(world, no_segyio):
    provider, ll, pid = world
    layer = _layer(provider, pid, "s1")
    assert layer.error == "Reading SEG-Y needs the free library segyio, which is not installed."
    assert layer.missing_library == "segyio"
    ll.set_layers(provider, provider.layers(pid))
    menu = ll.row_menu("s1")
    assert _texts(menu)[0] == INSTALL


def test_the_panel_error_line_says_how_to_install(world, no_segyio):
    from groundwork_geophysics.section.layer_list import error_line
    provider, _ll, pid = world
    assert error_line(_layer(provider, pid, "s1")) == (
        "Line 1: Reading SEG-Y needs the free library segyio, which is not installed. "
        "Right-click the layer and choose Install segyio…")
    gone = _layer(provider, pid, "m1")
    assert error_line(gone) == f"Gone: {gone.error}"


def test_display_and_apply_all_are_off_without_the_library(world, no_segyio):
    provider, ll, pid = world
    ll.set_layers(provider, provider.layers(pid))
    actions = {a.text(): a for a in ll.row_menu("s1").actions() if a.text()}
    assert not actions["Display…"].isEnabled()
    assert not actions["Apply Style to All Sections"].isEnabled()
    assert actions["Dataset info…"].isEnabled()
    assert {a.text(): a for a in ll.row_menu("m1").actions()}["Display…"].isEnabled()


def test_a_layer_with_another_error_has_no_install_entry(world, no_segyio):
    provider, ll, pid = world
    gone = _layer(provider, pid, "m1")
    assert gone.error and gone.missing_library is None
    ll.set_layers(provider, provider.layers(pid))
    assert not [t for t in _texts(ll.row_menu("m1")) if t.startswith("Install")]


def test_after_the_install_the_section_is_read(qgis_app, world, no_segyio, monkeypatch,
                                               answer_yes):
    from groundwork_geophysics import libs
    from qgis.PyQt.QtWidgets import QMessageBox
    provider, ll, pid = world
    seen = []

    def install(name, **_options):
        seen.append(name)
        no_segyio["installed"] = True
        return True, "segyio 1.9.15 is installed."
    monkeypatch.setattr(libs, "install", install)
    ll.set_layers(provider, provider.layers(pid))
    next(a for a in ll.row_menu("s1").actions() if a.text() == INSTALL).trigger()
    assert answer_yes == [("Install segyio", "Install the free library segyio (0.4 MB) into "
                           "Groundwork's folder in the QGIS profile?",
                           QMessageBox.StandardButton.Yes)]
    _wait(qgis_app, lambda: bool(ll.message_bar.items()))
    assert seen == ["segyio"]
    assert "segyio is installed." in _bar_texts(ll.message_bar)
    layer = _layer(provider, pid, "s1")
    assert layer.error is None and layer.traces is not None
    assert ll._layers["s1"].error is None                   # the row was told


def test_saying_no_installs_nothing(qgis_app, world, no_segyio, monkeypatch):
    from groundwork_geophysics import libs
    from qgis.PyQt.QtWidgets import QMessageBox
    provider, ll, pid = world
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a: QMessageBox.StandardButton.No))
    monkeypatch.setattr(libs, "install", lambda name, **_options: pytest.fail("installed"))
    ll.set_layers(provider, provider.layers(pid))
    ll.install_library("segyio")
    for _ in range(10):
        qgis_app.processEvents()
    assert not ll.message_bar.items()


def test_a_failed_install_shows_the_manual_command_and_keeps_the_error(
        qgis_app, world, no_segyio, monkeypatch, answer_yes):
    from groundwork_geophysics import libs
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QMessageBox, QPushButton
    provider, ll, pid = world
    message = ("Installing segyio failed:\nno network\n\nWith internet, you can also install it "
               f"by hand with:\n{libs.manual_command('segyio')}")
    monkeypatch.setattr(libs, "install", lambda name, **_options: (False, message))
    shown = []

    def exec_(box):
        shown.append((box.text(), box.textInteractionFlags()))
        return 0
    monkeypatch.setattr(QMessageBox, "exec", exec_)
    ll.set_layers(provider, provider.layers(pid))
    ll.install_library("segyio")
    _wait(qgis_app, lambda: bool(ll.message_bar.items()))
    [item] = ll.message_bar.items()
    assert item.level() == __import__("qgis.core", fromlist=["Qgis"]).Qgis.MessageLevel.Warning
    [details] = [b for b in item.findChildren(QPushButton) if b.text() == "Details"]
    details.click()
    [(text, flags)] = shown
    assert text == message and libs.manual_command("segyio") in text
    assert flags & Qt.TextInteractionFlag.TextSelectableByMouse
    layer = _layer(provider, pid, "s1")
    assert layer.error and layer.missing_library == "segyio"
