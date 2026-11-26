"""About Groundwork: the installed version, the QGIS version and where to find help."""
from __future__ import annotations

from qgis.core import Qgis
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout

from ..ids import NAME, SUBTITLE
from .help import REPO, SITE, plugin_version, release_note_url


def _links(version: str) -> str:
    rows = (("Documentation", SITE),
            (f"What's new in {version}", release_note_url(version)),
            ("Report a problem", REPO + "/issues"),
            ("Source code", REPO),
            ("Licence: GPL-2.0-or-later", REPO + "/blob/master/LICENSE"))
    return "<br>".join(f'<a href="{url}">{text}</a>' for text, url in rows)


def _library(name: str) -> str:
    """An optional library's line: "segyio 1.9.15", or "segyio: not installed"."""
    from .. import libs
    if not libs.available(name):
        return f"{name}: not installed"
    return f"{name} {libs.version(name)}".strip()


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"About {NAME}")
        version = plugin_version()
        title = QLabel(f"<h2>{NAME}</h2><p>{SUBTITLE[:1].upper() + SUBTITLE[1:]}.</p>")
        info = QLabel(f"Version {version}<br>QGIS {Qgis.version()}<br>{_library('segyio')}")
        info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        links = QLabel(_links(version))
        links.setOpenExternalLinks(True)
        links.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        for widget in (title, info, links):
            layout.addWidget(widget)
        layout.addSpacing(6)
        layout.addWidget(buttons)
        self.setMinimumWidth(320)
