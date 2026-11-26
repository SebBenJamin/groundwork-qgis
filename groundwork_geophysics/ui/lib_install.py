"""An optional library (``libs``) installed in a QGIS task, so QGIS stays responsive while pip
runs; only ever started by the user's click. The result reaches the caller on the main thread
through ``done(ok, message)``; a caller that is gone by then (a closed dialog) disconnects
first, and the install still completes."""
from __future__ import annotations

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import pyqtSignal

from .. import libs

TASK_TITLE = "Installing {name}"
INSTALL_TITLE = "Install {name}"
#: download size of each library, said before installing it
SIZES = {"segyio": "0.4 MB"}
QUESTION = "Install the free library {name}{size} into Groundwork's folder in the QGIS profile?"
DONE_TEXT = "{name} is installed."
FAILED_TEXT = "Installing {name} failed."
DETAILS_TEXT = "Details"
#: running tasks: Python must hold them until they finish, or QGIS calls into a deleted object
_RUNNING: set = set()


class InstallTask(QgsTask):
    """Runs ``libs.install(name)`` off the main thread."""

    #: (ok, message as ``libs.install`` gives it), emitted on the main thread
    done = pyqtSignal(bool, str)

    def __init__(self, name: str):
        super().__init__(TASK_TITLE.format(name=name))
        self.name = name
        self.ok, self.message = False, ""

    def run(self) -> bool:
        try:
            self.ok, self.message = libs.install(self.name)
        except Exception as exc:                # noqa: BLE001 - said to the user, never raised
            self.ok = False
            self.message = libs.failure_message(self.name, str(exc))
        return True

    def finished(self, result: bool) -> None:
        if not result and not self.message:     # stopped by QGIS before it ran
            self.message = f"Installing {self.name} was stopped."
        try:
            self.done.emit(bool(self.ok and result), self.message)
        finally:
            _RUNNING.discard(self)


def start_install(name: str) -> InstallTask:
    """Start installing ``name`` in QGIS's task manager; connect to ``done`` right away."""
    task = InstallTask(name)
    _RUNNING.add(task)
    QgsApplication.taskManager().addTask(task)
    return task


def ask_install(parent, name: str) -> bool:
    """Ask before installing ``name`` (Yes is the default); True on Yes."""
    from qgis.PyQt.QtWidgets import QMessageBox
    size = f" ({SIZES[name]})" if name in SIZES else ""
    answer = QMessageBox.question(
        parent, INSTALL_TITLE.format(name=name), QUESTION.format(name=name, size=size),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes)
    return answer == QMessageBox.StandardButton.Yes


def details_box(parent, name: str, message: str):
    """The whole install message (pip's output, the commands to install by hand) in a box
    whose text can be selected and copied."""
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtWidgets import QMessageBox
    box = QMessageBox(QMessageBox.Icon.Warning, INSTALL_TITLE.format(name=name), message,
                      QMessageBox.StandardButton.Close, parent)
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return box


def show_result(bar, name: str, ok: bool, message: str, parent=None) -> None:
    """Say how installing ``name`` went in the QGIS message bar ``bar`` (QGIS's own when
    None): a success line, or a warning whose Details button shows the whole ``message``."""
    from qgis.core import Qgis
    from qgis.PyQt.QtWidgets import QPushButton

    from ..ids import NAME
    if bar is None:
        from qgis.utils import iface
        bar = iface.messageBar() if iface is not None else None
    if bar is None:
        return
    if ok:
        bar.pushMessage(NAME, DONE_TEXT.format(name=name), Qgis.MessageLevel.Success, 5)
        return
    item = bar.createMessage(NAME, FAILED_TEXT.format(name=name))
    button = QPushButton(DETAILS_TEXT)
    button.clicked.connect(lambda: details_box(parent or bar, name, message).exec())
    item.layout().addWidget(button)
    bar.pushWidget(item, Qgis.MessageLevel.Warning)
