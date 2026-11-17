"""Help links: every page the plugin opens exists on the site with its heading; the version
comes from metadata.txt and has a release note; opening a page never fails in QGIS."""
import configparser
from pathlib import Path

import pytest

from tests.docs.test_docs_site import DOCS, headings, nav_pages

REPO = Path(__file__).resolve().parent.parent.parent


def test_help_pages_exist_in_nav_with_their_headings():
    from groundwork_geophysics.ui.help import HELP_PAGES
    nav = set(nav_pages())
    for key, target in HELP_PAGES.items():
        path, _, anchor = target.partition("#")
        page = path.rstrip("/") + ".md"
        assert page in nav, (key, page)
        if anchor:
            assert anchor in headings(page), (key, anchor)


def test_help_url():
    from groundwork_geophysics.ui.help import SITE, help_url
    assert SITE == "https://sebbenjamin.github.io/groundwork-qgis/"
    assert help_url("plates") == SITE + "user/howto/plates/"
    assert help_url() == SITE


def test_plugin_version_matches_metadata():
    from groundwork_geophysics.ui.help import plugin_version
    meta = configparser.ConfigParser()
    meta.read(REPO / "groundwork_geophysics" / "metadata.txt", encoding="utf-8")
    assert plugin_version() == meta["general"]["version"] == "0.12.0"


def test_release_note_for_installed_version_exists():
    from groundwork_geophysics.ui.help import SITE, plugin_version, release_note_url
    version = plugin_version()
    assert (DOCS / "releases" / f"{version}.md").is_file()
    assert release_note_url(version) == SITE + f"releases/{version}/"


@pytest.fixture
def opened(monkeypatch):
    from qgis.PyQt.QtGui import QDesktopServices
    urls = []
    monkeypatch.setattr(QDesktopServices, "openUrl",
                        staticmethod(lambda url: urls.append(url.toString()) or True))
    return urls


def test_add_help_button_opens_page(qgis_app, opened):
    from qgis.PyQt.QtWidgets import QDialogButtonBox

    from groundwork_geophysics.ui.help import add_help_button, help_url
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
    add_help_button(box, "add_data")
    button = box.button(QDialogButtonBox.StandardButton.Help)
    assert button is not None
    button.click()
    assert opened == [help_url("add_data")]


@pytest.mark.parametrize("behaviour", ["false", "raise"])
def test_open_help_failure_is_quiet(qgis_app, monkeypatch, behaviour):
    from qgis.PyQt.QtGui import QDesktopServices

    from groundwork_geophysics.ui.help import open_help

    def fail(url):
        if behaviour == "raise":
            raise RuntimeError("no browser")
        return False
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(fail))
    open_help("plates")                     # nothing raised
