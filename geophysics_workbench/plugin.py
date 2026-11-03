"""Plugin object: owns the 'Geophysics Workbench' menu, the section panel, the map link
and the registered profile source, and follows the QGIS project: the workbench project
(GeoPackage) it refers to is attached on load and detached when the project is cleared."""
from pathlib import Path

from qgis.core import Qgis, QgsCoordinateReferenceSystem, QgsMessageLog, QgsProject
from qgis.gui import QgsProjectionSelectionDialog
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QAction, QIcon
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMenu, QMessageBox

from .section.context_layers import ContextGatherer
from .section.crossing_lines import own_layer_ids
from .section.data import SectionDataProvider
from .section.dock import SectionDock
from .section.map_link import MapLink
from .section.profile_source import register_source, unregister_source
from .ui import project_actions
from .ui.context_dialog import read_settings

MENU_TITLE = "Geophysics Workbench"
_ICON_DIR = Path(__file__).parent / "icons"


class WorkbenchPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.menu = None
        self.actions = []
        self.provider: SectionDataProvider | None = None
        self.source = None
        self.gatherer: ContextGatherer | None = None
        self._context_logged: set[tuple[str, str]] = set()
        self.dock: SectionDock | None = None
        self.map_link: MapLink | None = None
        self.pick_action = None
        self.new_profile_action = None
        self.add_model_action = None
        self.context_action = None
        self.ties_action = None
        self.ties_panel = None
        self._profile_dialog = None
        self._context_dialog = None
        self._project_signals = []

    @property
    def store(self):
        return None if self.provider is None else self.provider.store

    def initGui(self):
        main_window = self.iface.mainWindow()
        self.menu = QMenu(MENU_TITLE, main_window)
        self.menu.setObjectName("GeophysicsWorkbenchMenu")
        main_window.menuBar().addMenu(self.menu)

        self.dock = SectionDock(main_window)
        self.iface.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock)
        self.dock.hide()
        self.map_link = MapLink(self.iface, self.dock)
        self.add_action("New workbench project…", self.new_workbench_project)
        self.add_action("Open workbench project…", self.open_workbench_project)
        self.menu.addSeparator()
        self.new_profile_action = self.add_action("New profile…", self.new_profile)
        self.add_model_action = self.add_action("Add ERT model…", self.add_model)
        self.context_action = self.add_action("Context layers…", self.edit_context)
        self.ties_action = self.add_action("Profile ties…", self.show_ties_panel)
        self.menu.addSeparator()
        self.add_action("Show section panel", self.show_section_panel)
        self.pick_action = self.add_action("Pick profile on map", self.toggle_pick_tool,
                                           checkable=True)
        self.map_link.tool.setAction(self.pick_action)   # unchecks when another tool takes over
        self.dock.profile_changed.connect(self._update_actions)
        if self.provider is not None:
            self.dock.set_provider(self.provider, self.source)

        project = QgsProject.instance()
        for signal, slot in ((project.readProject, self._project_read),
                             (project.cleared, self._project_cleared),
                             (project.fileNameChanged, self._project_renamed)):
            signal.connect(slot)
            self._project_signals.append((signal, slot))
        if self.provider is None:
            self._project_read()                         # plugin enabled with a project open
        self._update_actions()

    def unload(self):
        for signal, slot in self._project_signals:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._project_signals.clear()
        self._close_profile_dialog()
        self._close_context_dialog()
        self._close_ties_panel()
        if self.map_link is not None:
            self.map_link.unload()
            self.map_link = None
        if self.dock is not None:
            self.dock.set_provider(None)                 # detach the source before unregistering
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        self._drop_source()
        self._close_gatherer()
        self.provider = None
        if self.menu is not None:
            self.iface.mainWindow().menuBar().removeAction(self.menu.menuAction())
            self.menu.deleteLater()
            self.menu = None
        self.actions.clear()
        self.pick_action = self.new_profile_action = self.add_model_action = None
        self.context_action = self.ties_action = None

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
        self._close_profile_dialog()
        self._close_context_dialog()
        self._close_ties_panel()
        if self.dock is not None:
            self.dock.set_provider(None)
        self._drop_source()
        self._close_gatherer()
        self.provider = None
        if store is not None:
            self.provider = SectionDataProvider(store)
            project = QgsProject.instance()
            self.gatherer = ContextGatherer(project, store.crs_authid,
                                            on_change=self.provider.notify_changed,
                                            exclude=lambda: own_layer_ids(store, project))
            self.provider.context_source = self.gatherer.items_for
            self.provider.near_miss = read_settings(project).near_miss
            self.provider.on_context_error = self._log_context_error
            self._context_logged.clear()
            self.source = register_source(self.provider)
            if self.dock is not None:
                self.dock.set_provider(self.provider, self.source)
        self._update_actions()

    def _drop_source(self):
        if self.source is not None:
            unregister_source(self.source)
            self.source = None

    def _close_gatherer(self):
        """Stop the context gatherer watching layers; the provider no longer asks it."""
        if self.provider is not None:
            self.provider.context_source = None
        if self.gatherer is not None:
            self.gatherer.close()
            self.gatherer = None

    def _log_context_error(self, profile_id: str, message: str):
        """The context of a profile could not be gathered: log it once per profile and text."""
        if (profile_id, message) in self._context_logged or self.store is None:
            return
        self._context_logged.add((profile_id, message))
        try:
            name = self.store.profile(profile_id).name
        except KeyError:
            name = profile_id
        QgsMessageLog.logMessage(f"Context for profile '{name}' could not be gathered: "
                                 f"{message}", MENU_TITLE, Qgis.MessageLevel.Warning)

    # -- QGIS project --------------------------------------------------------------------------
    def _project_read(self, *_):
        try:
            store = project_actions.attach_store(QgsProject.instance())
        except ValueError as exc:
            store = None
            self._warn(str(exc))
        self.set_store(store)

    def _project_cleared(self):
        self.set_store(None)

    def _project_renamed(self):
        """Saved under a new name: keep the store path relative to the new location."""
        project = QgsProject.instance()
        if self.store is not None and project.fileName():
            project_actions.write_store_entry(project, self.store.path)

    def _update_actions(self, *_):
        if self.new_profile_action is not None:
            self.new_profile_action.setEnabled(self.store is not None)
        if self.context_action is not None:
            self.context_action.setEnabled(self.store is not None)
        if self.ties_action is not None:
            self.ties_action.setEnabled(self.store is not None)
        if self.add_model_action is not None:
            self.add_model_action.setEnabled(
                self.dock is not None and self.dock.current_profile_id() is not None)

    def _warn(self, text: str):
        bar = getattr(self.iface, "messageBar", None)
        if bar is not None:
            bar().pushWarning(MENU_TITLE, text)

    # -- workbench projects ----------------------------------------------------------------------
    def new_workbench_project(self):
        window = self.iface.mainWindow()
        path, _ = QFileDialog.getSaveFileName(window, "New workbench project", "",
                                              "GeoPackage (*.gpkg)",
                                              options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return
        if not path.lower().endswith(".gpkg"):
            path += ".gpkg"
        project = QgsProject.instance()
        crs_dialog = QgsProjectionSelectionDialog(window)
        crs_dialog.setWindowTitle("Projected CRS of the workbench project (metres)")
        if project.crs().isValid():
            crs_dialog.setCrs(project.crs())
        if crs_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        crs = crs_dialog.crs()
        try:
            store = project_actions.new_store(Path(path), crs.authid(), project)
        except FileExistsError:
            QMessageBox.warning(window, "New workbench project",
                                f"{Path(path).name} already exists. The workbench will not "
                                "overwrite an existing project file; choose another name.")
            return
        except (ValueError, OSError, RuntimeError) as exc:     # RuntimeError: GDAL write
            QMessageBox.warning(window, "New workbench project", str(exc))
            return
        if not project.crs().isValid():
            project.setCrs(QgsCoordinateReferenceSystem(crs.authid()))
        self.set_store(store)

    def open_workbench_project(self):
        window = self.iface.mainWindow()
        path, _ = QFileDialog.getOpenFileName(window, "Open workbench project", "",
                                              "GeoPackage (*.gpkg)")
        if not path:
            return
        try:
            store = project_actions.open_store(Path(path), QgsProject.instance())
        except (ValueError, OSError, RuntimeError) as exc:   # corrupt, locked or not a gpkg
            QMessageBox.warning(window, "Open workbench project", str(exc))
            return
        self.set_store(store)

    def new_profile(self):
        from .ui.new_profile_dialog import NewProfileDialog
        if self.store is None:
            return
        self._close_profile_dialog()
        dialog = NewProfileDialog(self.iface, self.store, provider=self.provider)
        dialog.accepted.connect(lambda: self._profile_created(dialog))
        self._profile_dialog = dialog
        dialog.show()                                    # non-modal: "Pick on map" needs the map

    def _profile_created(self, dialog):
        if dialog.profile is not None and self.dock is not None and self.provider is not None:
            self.show_section_panel()
            self.dock.open_profile(dialog.profile.id)

    def _close_profile_dialog(self):
        dialog, self._profile_dialog = self._profile_dialog, None
        if dialog is not None:
            dialog.reject()
            dialog.deleteLater()

    def add_model(self):
        from .ui.add_model_dialog import AddModelDialog
        pid = None if self.dock is None else self.dock.current_profile_id()
        if self.store is None or pid is None:
            return
        dialog = AddModelDialog(self.iface, self.store, pid, provider=self.provider)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def edit_context(self):
        from .ui.context_dialog import ContextDialog
        if self.store is None:
            return
        if self._context_dialog is not None:
            self._context_dialog.show()
            self._context_dialog.raise_()
            self._context_dialog.activateWindow()
            return
        project = QgsProject.instance()
        dialog = ContextDialog(self.iface, project,
                               exclude=own_layer_ids(self.store, project))
        dialog.applied.connect(self._context_applied)
        dialog.finished.connect(lambda _r, d=dialog: self._context_finished(d))
        self._context_dialog = dialog
        dialog.show()                                    # non-modal: the map stays usable

    def _context_applied(self):
        if self.provider is not None:
            self.provider.near_miss = read_settings(QgsProject.instance()).near_miss
            self.provider.notify_changed()               # redraw with the new layers now

    def _context_finished(self, dialog):
        if self._context_dialog is dialog:
            self._context_dialog = None
        dialog.deleteLater()

    def _close_context_dialog(self):
        dialog, self._context_dialog = self._context_dialog, None
        if dialog is not None:
            dialog.reject()
            dialog.deleteLater()

    def show_ties_panel(self):
        from .ui.ties_panel import TiesPanel
        if self.provider is None or self.dock is None:
            return
        if self.ties_panel is None:
            self.ties_panel = TiesPanel(self.provider, self.dock, self.iface.mainWindow())
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.ties_panel)
        self.ties_panel.refresh()
        self.ties_panel.show()
        self.ties_panel.raise_()

    def _close_ties_panel(self):
        panel, self.ties_panel = self.ties_panel, None
        if panel is not None:
            panel.detach()
            self.iface.removeDockWidget(panel)
            panel.deleteLater()

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
