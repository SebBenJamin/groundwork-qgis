"""Plugin object: owns the 'Geophysics Workbench' menu. Later tasks add actions via add_action."""
from pathlib import Path

from qgis.PyQt.QtGui import QAction, QIcon
from qgis.PyQt.QtWidgets import QMenu

MENU_TITLE = "Geophysics Workbench"
_ICON_DIR = Path(__file__).parent / "icons"


class WorkbenchPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.menu = None
        self.actions = []

    def initGui(self):
        main_window = self.iface.mainWindow()
        self.menu = QMenu(MENU_TITLE, main_window)
        self.menu.setObjectName("GeophysicsWorkbenchMenu")
        main_window.menuBar().addMenu(self.menu)

    def unload(self):
        if self.menu is not None:
            self.iface.mainWindow().menuBar().removeAction(self.menu.menuAction())
            self.menu.deleteLater()
            self.menu = None
        self.actions.clear()

    def add_action(self, text, callback, icon=None, checkable=False):
        """Add a menu action. `icon` is a file name inside the icons folder or an absolute path."""
        action = QAction(text, self.menu)
        if icon:
            path = Path(icon)
            action.setIcon(QIcon(str(path if path.is_absolute() else _ICON_DIR / path)))
        action.setCheckable(checkable)
        action.triggered.connect(callback)
        self.menu.addAction(action)
        self.actions.append(action)
        return action
