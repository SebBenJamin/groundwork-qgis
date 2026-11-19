"""Help and About Groundwork: the version, the links, the two menu entries."""
import configparser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent


def test_about_shows_version_and_links(qgis_app):
    from qgis.PyQt.QtWidgets import QLabel

    from groundwork_geophysics.ui.about_dialog import AboutDialog
    from groundwork_geophysics.ui.help import REPO as GH
    from groundwork_geophysics.ui.help import SITE, release_note_url
    dlg = AboutDialog()
    text = " ".join(label.text() for label in dlg.findChildren(QLabel))
    assert "Version 0.13.0" in text and "QGIS " in text
    for url in (SITE, release_note_url("0.13.0"), GH + "/issues", GH, GH + "/blob/master/LICENSE"):
        assert f'href="{url}"' in text, url
    assert dlg.windowTitle() == "About Groundwork"
    dlg.deleteLater()


def test_help_and_about_in_menu_and_removed_on_unload(qgis_app, fake_iface, monkeypatch):
    from qgis.core import QgsProject

    from groundwork_geophysics import classFactory
    from groundwork_geophysics.ui import help as help_module
    opened = []
    monkeypatch.setattr(help_module, "open_help", lambda key=None: opened.append(key))
    QgsProject.instance().clear()
    plug = classFactory(fake_iface)
    plug.initGui()
    try:
        actions = plug.menu.actions()
        assert [a.text() for a in actions[-2:]] == ["Help", "About Groundwork…"]
        assert actions[-3].isSeparator()
        plug.help_action.trigger()
        assert opened == [None]
    finally:
        plug.unload()
    assert plug.menu is None
    assert plug.help_action is None and plug.about_action is None


def test_metadata_homepage_is_site():
    from groundwork_geophysics.ui.help import SITE
    meta = configparser.ConfigParser(interpolation=None)
    meta.read(REPO / "groundwork_geophysics" / "metadata.txt", encoding="utf-8")
    assert meta["general"]["homepage"] == SITE
    assert meta["general"]["repository"].startswith("https://github.com/")


def test_help_and_about_keep_their_menu_place_on_macos(qgis_app, fake_iface):
    """Qt moves actions named "About…" into the macOS application menu, next to QGIS's own."""
    from qgis.core import QgsProject
    from qgis.PyQt.QtGui import QAction

    from groundwork_geophysics import classFactory
    QgsProject.instance().clear()
    plug = classFactory(fake_iface)
    plug.initGui()
    try:
        for action in (plug.help_action, plug.about_action):
            assert action.menuRole() == QAction.MenuRole.NoRole, action.text()
    finally:
        plug.unload()
