"""Links to the documentation site: the pages the dialogs' Help buttons open, the installed
version and its release note. A moved page is one edit in ``HELP_PAGES`` (a test checks each
page and heading exists in docs/)."""
from __future__ import annotations

import configparser
from pathlib import Path

SITE = "https://sebbenjamin.github.io/groundwork-qgis/"
REPO = "https://github.com/SebBenJamin/groundwork-qgis"

#: dialog -> its page on the site (relative to SITE), with a heading's anchor where useful
HELP_PAGES = {
    "add_data": "user/howto/add-data/",
    "new_profile": "user/howto/add-data/#where-the-line-runs",
    "profile_properties": "user/howto/placement/#adding-surveyed-positions-later",
    "context_layers": "user/howto/boreholes/#context-layers-field-by-field",
    "plates": "user/howto/plates/",
    "plate_details": "user/howto/plates/#the-title-block",
    "view3d": "user/howto/3d-view/",
}

_METADATA = Path(__file__).resolve().parent.parent / "metadata.txt"


def help_url(key: str | None = None) -> str:
    """The page for ``key`` (a ``HELP_PAGES`` key); the site's start page for None."""
    return SITE + (HELP_PAGES[key] if key else "")


def open_help(key: str | None = None) -> None:
    """Open the page in the browser; a failure (no browser, offline) is only logged."""
    from qgis.core import Qgis, QgsMessageLog
    from qgis.PyQt.QtCore import QUrl
    from qgis.PyQt.QtGui import QDesktopServices

    from ..ids import NAME
    url = help_url(key)
    try:
        opened = QDesktopServices.openUrl(QUrl(url))
    except Exception as exc:                    # noqa: BLE001 - help must never break a dialog
        opened, reason = False, str(exc)
    else:
        reason = "the system could not open it"
    if not opened:
        QgsMessageLog.logMessage(f"Could not open the help page {url}: {reason}", NAME,
                                 Qgis.MessageLevel.Warning)


def add_help_button(box, key: str) -> None:
    """Add the standard Help button to the dialog's button box, opening ``key``'s page."""
    from qgis.PyQt.QtWidgets import QDialogButtonBox
    box.addButton(QDialogButtonBox.StandardButton.Help)
    box.helpRequested.connect(lambda: open_help(key))


def plugin_version() -> str:
    """The installed version, from the plugin's metadata.txt."""
    meta = configparser.ConfigParser(interpolation=None)
    meta.read(_METADATA, encoding="utf-8")
    return meta["general"]["version"]


def release_note_url(version: str) -> str:
    return SITE + f"releases/{version}/"
