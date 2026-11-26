"""An optional library (``libs``) installed in a QGIS task, so QGIS stays responsive while pip
runs; only ever started by the user's click. The result reaches the caller on the main thread
through ``done(ok, message)``; a caller that is gone by then (a closed dialog) disconnects
first, and the install still completes."""
from __future__ import annotations

from qgis.core import QgsApplication, QgsTask
from qgis.PyQt.QtCore import pyqtSignal

from .. import libs

TASK_TITLE = "Installing {name}"
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
            self.message = (f"Installing {self.name} failed: {exc}\n\nYou can install it by "
                            f"hand with:\n{libs.manual_command(self.name)}")
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
