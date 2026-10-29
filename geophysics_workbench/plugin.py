"""Plugin object: owns the 'Geophysics Workbench' menu, the section panel, the map link
and the registered profile source. Later tasks add actions via add_action."""
from pathlib import Path

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QAction, QIcon
from qgis.PyQt.QtWidgets import QMenu

from .section.data import SectionDataProvider
from .section.dock import SectionDock
from .section.map_link import MapLink
from .section.profile_source import register_source, unregister_source

MENU_TITLE = "Geophysics Workbench"
_ICON_DIR = Path(__file__).parent / "icons"


class WorkbenchPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.menu = None
        self.actions = []
        self.provider: SectionDataProvider | None = None
        self.source = None
        self.dock: SectionDock | None = None
        self.map_link: MapLink | None = None
        self.pick_action = None

    def initGui(self):
        main_window = self.iface.mainWindow()
        self.menu = QMenu(MENU_TITLE, main_window)
        self.menu.setObjectName("GeophysicsWorkbenchMenu")
        main_window.menuBar().addMenu(self.menu)

        self.dock = SectionDock(main_window)
        self.iface.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock)
        self.dock.hide()
        self.map_link = MapLink(self.iface, self.dock)
        self.add_action("Show section panel", self.show_section_panel)
        self.pick_action = self.add_action("Pick profile on map", self.toggle_pick_tool,
                                           checkable=True)
        self.map_link.tool.setAction(self.pick_action)   # unchecks when another tool takes over
        if self.provider is not None:
            self.dock.set_provider(self.provider, self.source)

    def unload(self):
        if self.map_link is not None:
            self.map_link.unload()
            self.map_link = None
        if self.dock is not None:
            self.dock.set_provider(None)                 # detach the source before unregistering
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        self._drop_source()
        self.provider = None
        if self.menu is not None:
            self.iface.mainWindow().menuBar().removeAction(self.menu.menuAction())
            self.menu.deleteLater()
            self.menu = None
        self.actions.clear()
        self.pick_action = None

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

    # -- project store -------------------------------------------------------------------------
    def set_store(self, store):
        """Show ``store`` (a ``ProjectStore``) in the section panel; ``None`` tears down.

        The canvas is detached before the old source is unregistered, because
        unregistering destroys the source."""
        if self.dock is not None:
            self.dock.set_provider(None)
        self._drop_source()
        self.provider = None
        if store is None:
            return
        self.provider = SectionDataProvider(store)
        self.source = register_source(self.provider)
        if self.dock is not None:
            self.dock.set_provider(self.provider, self.source)

    def _drop_source(self):
        if self.source is not None:
            unregister_source(self.source)
            self.source = None

    # -- actions -------------------------------------------------------------------------------
    def show_section_panel(self):
        if self.dock is not None:
            self.dock.show()
            self.dock.raise_()

    def toggle_pick_tool(self, checked=True):
        if self.map_link is None:
            return
        canvas = self.iface.mapCanvas()
        if checked:
            canvas.setMapTool(self.map_link.tool)
        elif canvas.mapTool() is self.map_link.tool:
            canvas.unsetMapTool(self.map_link.tool)
