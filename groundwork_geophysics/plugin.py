"""Plugin object: owns the 'Groundwork' menu, the section panel, the map link
and the registered profile source, and follows the QGIS project: the workbench project
(GeoPackage) it refers to is attached on load and detached when the project is cleared."""
from dataclasses import replace
from functools import partial
from pathlib import Path

from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsMessageLog,
                       QgsProject)
from qgis.gui import QgsProjectionSelectionDialog
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QAction, QIcon
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QMenu, QMessageBox

from .ids import NAME
from .section.context_layers import ContextGatherer
from .section.crossing_lines import own_layer_ids
from .section.data import SectionDataProvider
from .section.dock import UNCUT_3D_TEXT, SectionDock
from .section.map_link import MapLink
from .section.view3d_link import View3dLink
from .section.profile_source import register_source, unregister_source
from .section.style_watch import StyleWatch
from .ui import derived_layers, project_actions, view3d_layers, view3d_view
from .ui.context_dialog import read_settings
from .section.field_notes_render import note_looks
from .ui.field_note_layers import ensure_note_layers, migrate_note_styles
from .ui.interp_layers import (ensure_3d_styles, interp_layers, migrate_letter_styles,
                               stop_following)


def _own_styled_layers(store, project) -> list:
    """The workbench's own layers whose QGIS style the section draws with."""
    from .ui.field_note_layers import field_note_layers
    return [*interp_layers(store, project).values(),
            *field_note_layers(store, project).values()]

MENU_TITLE = NAME
_ICON_DIR = Path(__file__).parent / "icons"


class WorkbenchPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.borehole_viewer = None
        self.menu = None
        self.actions = []
        self.provider: SectionDataProvider | None = None
        self.source = None
        self.gatherer: ContextGatherer | None = None
        #: reads models in the background for the section panel and the 3D view
        self.model_reader = None
        self._prepared_3d: set = set()          # cloud / contour files a task has made
        self._prepare_tasks: list = []          # the running "Preparing 3D" tasks
        self.style_watch: StyleWatch | None = None
        self._context_logged: set[tuple[str, str]] = set()
        self.dock: SectionDock | None = None
        self.map_link: MapLink | None = None
        self.view3d_link: View3dLink | None = None
        self.pick_action = None
        self.new_profile_action = None
        self.add_data_action = None
        self.context_action = None
        self.ties_action = None
        self.help_action = None
        self.about_action = None
        self.ties_panel = None
        self._profile_dialog = None
        self._data_dialog = None
        self._context_dialog = None
        self._plates_dialog = None
        self.plates_action = None
        self.viewer_action = None
        self.rename_action = self.delete_action = None
        self._project_signals = []
        self._syncing_derived = False
        self._derived_timer = None
        self._syncing_3d = False
        self._view3d_timer = None
        self._view3d_boreholes = False          # the next refill also gathers boreholes
        self._view3d_stale = False              # a refill waits for a 3D view to open
        self.view3d_action = None
        self._view3d_dialog = None              # Show in 3D…, non-modal, one at a time

    @property
    def store(self):
        return None if self.provider is None else self.provider.store

    def initGui(self):
        from .patterns import register_svg_path
        from .plates import items as plate_items
        from .plates.sources import read_plates
        register_svg_path()                              # FGDC patterns in the SVG pickers
        # a project with plates read before the item types existed lost its colour bars and
        # borehole legends (QGIS drops unknown items): say so before the user saves
        read_too_early = not plate_items.items_registered() and \
            bool(read_plates(QgsProject.instance()))
        plate_items.register_items()                     # colour bar, borehole legend
        main_window = self.iface.mainWindow()
        self.menu = QMenu(MENU_TITLE, main_window)
        self.menu.setObjectName("GeophysicsWorkbenchMenu")
        self.menu.setToolTipsVisible(True)               # greyed-out entries say why
        main_window.menuBar().addMenu(self.menu)

        self.dock = SectionDock(main_window)
        self.iface.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.dock)
        self.dock.hide()
        self.map_link = MapLink(self.iface, self.dock)
        self.view3d_link = View3dLink(self.iface, self.dock)   # the 3D view's mouse
        self.view3d_link.on_opened = self._view3d_opened
        self.add_action("New Groundwork Project…", self.new_workbench_project)
        self.add_action("Open Groundwork Project…", self.open_workbench_project)
        self.menu.addSeparator()
        from .ui.profile_actions import RENAME_TEXT
        self.new_profile_action = self.add_action("New Profile…", self.new_profile)
        self.add_data_action = self.add_action("Add Data…", self.add_data)
        self.rename_action = self.add_action(RENAME_TEXT, lambda: self.rename_profile())
        self.delete_action = self.add_action("Delete Profile…", lambda: self.delete_profile())
        self.context_action = self.add_action("Context Layers…", self.edit_context)
        self.ties_action = self.add_action("Profile Ties…", self.show_ties_panel)
        self.plates_action = self.add_action("Plates…", self.show_plates)
        self.menu.addSeparator()
        self.add_action("Show Section Panel", self.show_section_panel)
        self.viewer_action = self.add_action("Show Borehole Viewer",
                                             lambda: self.open_borehole_viewer())
        self.viewer_action.setProperty(
            "enabled_tip", "The boreholes of the profile open in the section panel, side by side")
        self.view3d_action = self.add_action("Show in 3D…", self.show_in_3d)
        self.view3d_action.setProperty(
            "enabled_tip", "Pick the models and boreholes to show in QGIS's 3D view")
        self.pick_action = self.add_action("Pick Profile on Map", self.toggle_pick_tool,
                                           checkable=True)
        self.map_link.tool.setAction(self.pick_action)   # unchecks when another tool takes over
        self.pick_action.setIcon(QgsApplication.getThemeIcon("/mActionSelect.svg"))
        self.pick_action.setProperty("enabled_tip", "Pick a profile on the map")
        self.dock.set_pick_action(self.pick_action)
        self.menu.addSeparator()
        from .ui import help as help_links
        self.help_action = self.add_action("Help", lambda: help_links.open_help())
        self.help_action.setToolTip("The Groundwork documentation, in your browser")
        self.about_action = self.add_action("About Groundwork…", self.show_about)
        for action in (self.help_action, self.about_action):      # macOS would move them
            action.setMenuRole(QAction.MenuRole.NoRole)            # into its app menu
        self.dock.profile_changed.connect(self._update_actions)
        self.dock.borehole_clicked.connect(self.open_borehole_viewer)
        self.dock.rename_requested.connect(self.rename_profile)
        self.dock.delete_requested.connect(self.delete_profile)
        self.dock.view3d_requested.connect(self.profile_in_3d)
        self.dock.view3d_cut_active = self._view3d_cut_state
        self.dock.view3d_button.setVisible(hasattr(self.iface, "mapCanvases3D"))
        if self.provider is not None:
            self.dock.set_provider(self.provider, self.source)
            self.dock.set_reader(self.model_reader)

        project = QgsProject.instance()
        for signal, slot in ((project.readProject, self._project_read),
                             (project.writeProject, self._project_write),
                             (project.cleared, self._project_cleared),
                             (project.fileNameChanged, self._project_renamed)):
            signal.connect(slot)
            self._project_signals.append((signal, slot))
        if self.provider is None:
            self._project_read()                         # plugin enabled with a project open
        self._update_actions()
        if read_too_early:
            self._warn("Plates: this project was opened before the plugin was loaded, so its "
                       "plate colour bars and borehole legends were not read. Please reopen "
                       "the project before saving it (saving now would lose them).")
        from .ui.old_plugin import OLD_PLUGIN_WARNING, old_plugin_present
        if old_plugin_present():
            self._warn(OLD_PLUGIN_WARNING)

    def unload(self):
        for signal, slot in self._project_signals:
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        self._project_signals.clear()
        stop_following()                    # 2D restyles no longer restyle the 3D style
        self._close_view3d_dialog()
        self._close_profile_dialog()
        self._close_data_dialog()
        self._close_context_dialog()
        self._close_plates_dialog()
        self._close_ties_panel()
        self._close_borehole_viewer()
        if self.map_link is not None:
            self.map_link.unload()
            self.map_link = None
        if self.view3d_link is not None:
            self.view3d_link.unload()
            self.view3d_link = None
        if self.model_reader is not None:              # no reading task calls back any more
            self.model_reader.cancel()
            self.model_reader = None
        for task in list(self._prepare_tasks):
            task.cancel()
        self._prepare_tasks.clear()
        if self.dock is not None:
            self.dock.set_provider(None)                 # detach the source before unregistering
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        self._drop_plate_sources()
        self._drop_source()
        self._close_gatherer()
        self.provider = None
        if self.menu is not None:
            self.iface.mainWindow().menuBar().removeAction(self.menu.menuAction())
            self.menu.deleteLater()
            self.menu = None
        self.actions.clear()
        self.pick_action = self.new_profile_action = self.add_data_action = None
        self.rename_action = self.delete_action = None
        self.context_action = self.ties_action = self.plates_action = None
        self.viewer_action = None
        self.help_action = self.about_action = None
        from .patterns import unregister_svg_path
        unregister_svg_path()

    def show_about(self):
        from .ui.about_dialog import AboutDialog
        AboutDialog(self.iface.mainWindow()).exec()

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
        self._close_borehole_viewer()          # it follows the old store's data
        stop_following()                       # the old store's interpretation layers
        self._close_view3d_dialog()            # it lists the old store's profiles
        view3d_layers.forget_shown(QgsProject.instance())   # a new store starts afresh
        old = derived_layers.derived_layer(QgsProject.instance())
        if old is not None:                    # the old store's electrodes
            QgsProject.instance().removeMapLayer(old.id())
        self._close_profile_dialog()
        self._close_data_dialog()             # it adds to the old store
        self._close_context_dialog()
        self._close_plates_dialog()           # it edits the old store's plates
        self._close_ties_panel()
        if self.dock is not None:
            self.dock.set_provider(None)
        self._drop_plate_sources()
        self._drop_source()
        self._close_gatherer()
        if self.model_reader is not None:
            self.model_reader.cancel()
            self.model_reader = None
        self.provider = None
        self._view3d_stale = False
        if store is not None:
            project = QgsProject.instance()
            from .section.model_reading import ModelReader
            from .section.style_store import load_styles, save_styles
            self.provider = SectionDataProvider(store, styles=load_styles(project))
            self.model_reader = ModelReader(self.provider)
            reader, provider_ = self.model_reader, self.provider
            # ties to crossing profiles: drawn at once, their columns once those are read
            self.provider.on_unread_ties = lambda ids: reader.request(
                ids, lambda ok: provider_.notify_redraw(ties=True))
            provider = self.provider
            self.provider.on_style.append(lambda: save_styles(project, provider.styles()))
            project_actions.reload_stale_layers(store, project)  # 0.8 stations, no inline
            migrate_letter_styles(store, project)       # 0.7 styles named "letter"
            ensure_3d_styles(store, project)            # before 0.14: no 3D style
            project_actions.ensure_station_3d(store, project)
            ensure_note_layers(store, project)          # notes always have a layer to style
            migrate_note_styles(store, project)
            self.provider.note_looks = partial(note_looks, store, project)
            from .section.data import cache_folder
            self.gatherer = ContextGatherer(project, store.crs_authid,
                                            on_change=self.provider.notify_changed,
                                            exclude=lambda: own_layer_ids(store, project),
                                            cache_dir=cache_folder(store))
            self.gatherer.background = True             # a web strip never freezes QGIS
            self.provider.refresh_web_layers = self.gatherer.refresh_web_layers
            self.provider.has_web_layers = self.gatherer.uses_web_layers
            self.provider.context_source = self.gatherer.items_for
            self.provider.borehole_source = self.gatherer.borehole_keys
            self.provider.interp_layers = lambda: interp_layers(store, project)
            self.style_watch = StyleWatch(project, partial(_own_styled_layers, store, project),
                                          self.provider.notify_redraw)
            self.provider.near_miss = read_settings(project).near_miss
            self.provider.on_context_error = self._log_context_error
            self.provider.on_data_change.append(self._schedule_derived)
            self._sync_derived(create=True)
            self.provider.on_change.append(self._schedule_3d)
            self.provider.on_data_change.append(lambda: self._schedule_3d(boreholes=True))
            self._sync_3d()
            self._context_logged.clear()
            self.source = register_source(self.provider)
            if self.dock is not None:
                self.dock.set_provider(self.provider, self.source)
                self.dock.set_reader(self.model_reader)
            self.attach_plates()
        self._update_actions()

    def attach_plates(self) -> None:
        """Register one source per plate frame and give the frame items their sources (also
        after the plates change)."""
        from .plates.sources import (attach_frame_sources, detach_frame_items, read_plates,
                                     register_frame_sources)
        if self.provider is None:
            return
        from .plates.items import set_context_provider
        project = QgsProject.instance()
        set_context_provider(self.provider)
        detach_frame_items(project)
        sources = register_frame_sources(self.provider, read_plates(project))
        attach_frame_sources(project, self.provider.store, sources)

    def _drop_plate_sources(self) -> None:
        from .plates.items import set_context_provider
        from .plates.sources import detach_frame_items, unregister_frame_sources
        set_context_provider(None)
        detach_frame_items(QgsProject.instance())
        unregister_frame_sources()

    def _drop_source(self):
        if self.source is not None:
            unregister_source(self.source)
            self.source = None

    def _close_gatherer(self):
        """Stop the context gatherer (and the style watch) watching layers; the provider no
        longer asks it."""
        if self.style_watch is not None:
            self.style_watch.unload()
            self.style_watch = None
        if self.provider is not None:
            self.provider.context_source = None
            self.provider.borehole_source = None
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

    def _schedule_derived(self) -> None:
        """Data changed: refill the derived layer once after the event loop turn."""
        if self._derived_timer is None:
            self._derived_timer = QTimer()
            self._derived_timer.setSingleShot(True)
            self._derived_timer.timeout.connect(self._sync_derived)
        self._derived_timer.start(0)

    def _sync_derived(self, create: bool = False) -> None:
        """Show the derived electrodes as a temporary map layer (never stored). Only a store
        being opened creates the layer; it never raises out of opening or a notification."""
        if self.provider is None or self._syncing_derived:
            return
        self._syncing_derived = True            # adding the layer must not set off a rebuild
        try:
            derived_layers.sync(self.provider.store, self.provider, QgsProject.instance(),
                                create=create)
        except Exception as exc:
            QgsMessageLog.logMessage(f"Derived electrodes layer: {exc}", MENU_TITLE,
                                     Qgis.MessageLevel.Warning)
        finally:
            self._syncing_derived = False

    def _schedule_3d(self, boreholes: bool = False) -> None:
        """A section style changed (or, with ``boreholes``, the data or context): refill
        the 3D layers once things settle."""
        self._view3d_boreholes = self._view3d_boreholes or boreholes
        if self._view3d_timer is None:
            self._view3d_timer = QTimer()
            self._view3d_timer.setSingleShot(True)
            self._view3d_timer.timeout.connect(
                lambda: self._sync_3d(boreholes=self._view3d_boreholes))
        self._view3d_timer.start(300)

    def _sync_3d(self, create: bool = False, boreholes: bool = True, then=None) -> dict:
        """Refill the Show in 3D layers (created only when the user asks); never raises out
        of opening or a notification. Without ``create`` and with no 3D map view open, it
        only takes out what belongs to deleted or unticked models and profiles and notes
        that the layers are out of date: point clouds and pictures are files, rewritten on
        every style change, and nobody would see them. The next 3D view that opens, or OK in
        Show in 3D…, brings them up to date.

        Models not read yet and point clouds or contour lines not computed yet are done in
        QGIS tasks first; the layers are filled when those are done (returns {} meanwhile).
        ``then(layers)`` is called after the fill, at once or after the tasks."""
        if self.provider is None or self._syncing_3d:
            return {}
        if (create or view3d_view.views_open(self.iface)) and \
                self._prepare_3d_first(create, boreholes, then):
            return {}
        layers = self._fill_3d(create, boreholes)
        if then is not None:
            then(layers)
        return layers

    def _prepare_3d_first(self, create: bool, boreholes: bool, then) -> bool:
        """Read the chosen models and compute missing clouds and contour lines in QGIS
        tasks, then fill the 3D layers; False when nothing needs doing first."""
        if self.model_reader is None:
            return False
        project = QgsProject.instance()
        store, provider = self.provider.store, self.provider
        choice = view3d_layers.read_choice(project)
        ids = sorted({p.id for p, _d in view3d_layers._chosen_models(store, choice)})

        def again(ok: bool = True) -> None:
            if ok and self.provider is provider:
                self._sync_3d(create, boreholes, then)
        if ids and self.model_reader.request(ids, again):
            return True
        from .ui.view3d_prepare import Prepare3DTask, pending_3d
        try:
            jobs = [j for j in pending_3d(store, provider, project)
                    if j.path not in self._prepared_3d]
        except Exception as exc:                # never raises out of a notification
            QgsMessageLog.logMessage(f"3D view layers: {exc}", MENU_TITLE,
                                     Qgis.MessageLevel.Warning)
            return False
        if not jobs:
            return False
        self._prepared_3d.update(j.path for j in jobs)     # once: an empty cloud is no file
        task = Prepare3DTask(jobs)
        self._prepare_tasks.append(task)

        def finished(ok: bool) -> None:
            if task in self._prepare_tasks:
                self._prepare_tasks.remove(task)
            again(ok)
        task.taskCompleted.connect(lambda: finished(True))
        task.taskTerminated.connect(lambda: finished(False))
        from qgis.core import QgsApplication
        QgsApplication.taskManager().addTask(task)
        return True

    def _fill_3d(self, create: bool, boreholes: bool) -> dict:
        if self.provider is None or self._syncing_3d:
            return {}
        if not create and not view3d_view.views_open(self.iface):
            self._view3d_stale = True
            self._view3d_boreholes = False      # the waiting refill gathers them anyway
            self._syncing_3d = True
            try:
                view3d_layers.prune(self.provider.store, QgsProject.instance())
            except Exception as exc:
                QgsMessageLog.logMessage(f"3D view layers: {exc}", MENU_TITLE,
                                         Qgis.MessageLevel.Warning)
            finally:
                self._syncing_3d = False
            return {}
        self._syncing_3d = True
        self._view3d_boreholes = False
        self._view3d_stale = False
        try:
            return view3d_layers.sync(self.provider.store, self.provider,
                                      QgsProject.instance(), create=create,
                                      boreholes=boreholes)
        except Exception as exc:
            QgsMessageLog.logMessage(f"3D view layers: {exc}", MENU_TITLE,
                                     Qgis.MessageLevel.Warning)
            return {}
        finally:
            self._syncing_3d = False

    def _view3d_opened(self) -> None:
        """A 3D map view has opened: bring the 3D layers up to date if a refill waits."""
        if self._view3d_stale:
            self._sync_3d()

    def show_in_3d(self):
        """Show in 3D…: pick the models and boreholes in a non-modal dialog (one at a time;
        asked again, it comes to the front); Apply and OK make the layers follow the
        choice."""
        from qgis.PyQt.QtGui import QGuiApplication
        from qgis.PyQt.QtCore import Qt as QtNs

        from .ui.view3d_dialog import View3dDialog
        from .ui.view3d_layers import profiles_with_boreholes, read_choice
        if self.store is None:
            return
        if self._view3d_dialog is not None:
            self._view3d_dialog.show()
            self._view3d_dialog.raise_()
            self._view3d_dialog.activateWindow()
            return
        project = QgsProject.instance()
        local = set()
        for profile in self.store.profiles():
            try:
                if self.provider.is_local(profile.id):
                    local.add(profile.id)
            except Exception:
                continue
        QGuiApplication.setOverrideCursor(QtNs.CursorShape.WaitCursor)
        try:                                    # each profile's context is gathered once
            with_boreholes = profiles_with_boreholes(self.store, self.provider)
        finally:
            QGuiApplication.restoreOverrideCursor()
        dialog = View3dDialog(self.store, read_choice(project), local=local,
                              parent=self.iface.mainWindow(), with_boreholes=with_boreholes)
        dialog.applied.connect(lambda: self._apply_3d(dialog))
        dialog.restyle_requested.connect(self._restyle_interpretation_3d)
        dialog.finished.connect(lambda _r: self._forget_view3d_dialog(dialog))
        self._view3d_dialog = dialog
        dialog.show()

    def _forget_view3d_dialog(self, dialog) -> None:
        if self._view3d_dialog is dialog:
            self._view3d_dialog = None
        dialog.deleteLater()

    def _close_view3d_dialog(self) -> None:
        dialog = self._view3d_dialog
        if dialog is not None:
            dialog.reject()                     # finished: forgotten and deleted

    def _restyle_interpretation_3d(self) -> None:
        """Show in 3D's Restyle Interpretation from 2D button: at once, with a message."""
        from .ui import interp_layers as interp_module
        if self.store is None:
            return
        if interp_module.restyle_from_2d(self.store, QgsProject.instance()):
            self._info("The interpretation's 3D style follows its 2D style again.")
        else:
            self._info("There is no interpretation to restyle in 3D.")

    def _apply_3d(self, dialog) -> None:
        """Show in 3D's Apply or OK: store the choice, build the layers, open or use a 3D
        map view on them, and say what is shown."""
        from .ui.view3d_layers import write_choice
        if self.store is None:
            return
        project = QgsProject.instance()
        choice = dialog.choice()
        write_choice(project, choice)
        # the chosen size, or one fitting the stations imported since
        project_actions.fit_station_spheres(self.store, project,
                                            (choice.station_size or 0) / 2 or None)
        if not choice.models and not choice.boreholes:
            self._sync_3d(create=True)
            self._info("Nothing is shown in 3D.")
            return

        def shown(layers: dict) -> None:
            summary = f"Shown in 3D: {view3d_layers.shown_summary(layers)}"
            if not layers:
                self._info(f"{summary}.")
                return
            self._show_3d_view(project, summary)
        self._sync_3d(create=True, then=shown)

    def _view3d_cut_state(self) -> bool | None:
        """For the profile menu: whether a 3D view is cut along a profile; None in a QGIS
        without 3D map views (no 3D entries then)."""
        if not hasattr(self.iface, "mapCanvases3D"):
            return None
        return view3d_view.cut_active(self.iface)

    def profile_in_3d(self, profile_id: str, what: str) -> None:
        """The section panel's 3D button and profile menu: "look" turns the 3D view side-on
        to the profile, "cut" also clips it to a slab along the profile (the curtain shows
        through the terrain), "uncut" makes every 3D view whole again, "dialog" opens Show in
        3D…. A profile nothing of which is shown yet is shown first (its models and
        boreholes ticked and built: asking to look at it asks for it), and with no 3D view
        open, a ready one opens."""
        if what == "dialog":
            self.show_in_3d()
            return
        if what == "uncut":
            view3d_view.remove_cuts(self.iface)
            self._info("The 3D view shows everything again.")
            return
        if self.store is None or self.provider is None:
            return
        try:
            profile = self.store.profile(profile_id)
            local = self.provider.is_local(profile_id)
        except Exception:                        # deleted meanwhile
            return
        if local:
            self._info(f"{profile.name} has no real heights, so it has no place in 3D. Give "
                       f"it a reference height in the section panel first.")
            return
        project = QgsProject.instance()
        added = self._show_profile_in_3d(project, profile_id)
        if not view3d_view.views_open(self.iface):
            try:
                box = view3d_layers.shown_box(self.store, self.provider, project)
            except Exception:
                box = None
            view3d_view.open_ready_view(self.iface, project, box, self.store.crs_authid)
            if self.view3d_link is not None:
                self.view3d_link.poll()          # follows it, and fills what waits
        done = view3d_view.look_at_profile(self.iface, project, profile,
                                           self.store.crs_authid, cut=what == "cut")
        if not done:
            self._info("Open a 3D map view with View → 3D Map Views → New 3D Map View.")
            return
        if added is None:
            self._info(f"{profile.name} has no model or boreholes to show in 3D.")
        elif added:
            self._info(f"{profile.name} is now shown in 3D. Change what is shown in "
                       f"Groundwork → Show in 3D….")
        elif done == view3d_view.CUT:
            self._info(f"The 3D view is cut along {profile.name}. To see everything again, "
                       f"right-click the profile list → {UNCUT_3D_TEXT}.")

    def _show_profile_in_3d(self, project, profile_id: str) -> bool | None:
        """When nothing of the profile is ticked in Show in 3D, tick its models (in their
        chosen look) and, when its section shows some, its boreholes, and build them; other
        profiles stay as they are. True when it did, False when something of it was shown
        already, None when it has nothing to show."""
        choice = view3d_layers.read_choice(project)
        models = {d.id for d in self.store.datasets(profile_id) if d.kind.endswith("_model")}
        if profile_id in choice.boreholes or models & choice.models:
            return False
        boreholes = {profile_id} & view3d_layers.profiles_with_boreholes_of(
            self.provider, [profile_id])
        if not models and not boreholes:
            return None
        view3d_layers.write_choice(project, replace(
            choice, models=choice.models | models, boreholes=choice.boreholes | boreholes))
        if self._view3d_dialog is not None:     # its ticks follow
            self._view3d_dialog.tick(models, boreholes)
        self._sync_3d(create=True)
        return True

    def _show_3d_view(self, project, summary: str) -> None:
        """Open (or use) a 3D map view on what is shown, and say so."""
        try:
            box = view3d_layers.shown_box(self.store, self.provider, project)
        except Exception:
            box = None
        view = view3d_view.open_ready_view(self.iface, project, box, self.store.crs_authid)
        if self.view3d_link is not None:
            self.view3d_link.poll()              # the 3D mouse follows a new view at once
        if view == view3d_view.ALREADY_OPEN:
            text = f"{summary}, in the open 3D map view."
        elif view == view3d_view.READY:
            text = f"{summary}, in a new 3D map view."
        elif view == view3d_view.OPENED:
            text = (f"{summary}, in a new 3D map view. If the curtains are hidden, switch its "
                    f"terrain off in the view's settings.")
        else:
            text = f"{summary}. Open a 3D map view with View → 3D Map Views → New 3D Map View."
        self._info(text)

    def _project_write(self, *_):
        derived_layers.save_style(QgsProject.instance())

    def _project_cleared(self):
        self._close_borehole_viewer()
        self.set_store(None)

    def open_borehole_viewer(self, entry: int | None = None, label: str = "") -> None:
        """Show the current profile's boreholes, ``(entry, label)`` highlighted (from a click
        on a column; none from the menu); one window, re-used later."""
        from .section.borehole_viewer import BoreholeViewer
        if self.dock is None or self.dock.provider is None:
            return
        profile_id = self.dock.current_profile_id()
        if profile_id is None:
            return
        if self.borehole_viewer is None:
            self.borehole_viewer = BoreholeViewer(self.dock, QgsProject.instance(),
                                                  self.iface.mainWindow())
        self.borehole_viewer.show_profile(profile_id,
                                          None if entry is None else (entry, label))
        self.borehole_viewer.show()
        self.borehole_viewer.raise_()
        self.borehole_viewer.activateWindow()

    def _current_boreholes(self) -> tuple[list[str], str]:
        """Labels of the open profile's boreholes and its name (Borehole style on a live
        interval table only reads those)."""
        profile = self.dock.current_profile() if self.dock is not None else None
        if profile is None or self.provider is None:
            return [], ""
        items = self.provider.context(profile.id)
        return ([p.label for p in (items.points if items else []) if p.kind == "borehole"],
                profile.name)

    def _close_borehole_viewer(self) -> None:
        viewer, self.borehole_viewer = self.borehole_viewer, None
        if viewer is not None:
            viewer.detach()
            viewer.close()
            viewer.deleteLater()

    def _project_renamed(self):
        """Saved under a new name: keep the store path relative to the new location."""
        project = QgsProject.instance()
        if self.store is not None and project.fileName():
            project_actions.write_store_entry(project, self.store.path)

    def _update_actions(self, *_):
        """Enable what can be used now; a greyed-out entry says why in its tooltip."""
        no_project = "Open or create a Groundwork project first"
        has_store = self.store is not None
        has_profile = self.dock is not None and self.dock.current_profile_id() is not None
        for action, ok, why in ((self.new_profile_action, has_store, no_project),
                                (self.add_data_action, has_store, no_project),
                                (self.context_action, has_store, no_project),
                                (self.ties_action, has_store, no_project),
                                (self.plates_action, has_store, no_project),
                                (self.view3d_action, has_store, no_project),
                                (self.pick_action, has_store, no_project),
                                (self.rename_action, has_profile,
                                 "Open a profile in the section panel first"),
                                (self.delete_action, has_profile,
                                 "Open a profile in the section panel first"),
                                (self.viewer_action, has_profile,
                                 "Open a profile in the section panel first")):
            if action is None:
                continue
            action.setEnabled(ok)
            tip = action.property("enabled_tip") or action.text().replace("…", "")
            action.setToolTip(tip if ok else why)

    def _warn(self, text: str):
        bar = getattr(self.iface, "messageBar", None)
        if bar is not None:
            bar().pushWarning(MENU_TITLE, text)

    # -- workbench projects ----------------------------------------------------------------------
    def new_workbench_project(self):
        window = self.iface.mainWindow()
        path, _ = QFileDialog.getSaveFileName(window, "New Groundwork project",
                                              project_actions.default_store_name(
                                                  QgsProject.instance()),
                                              "GeoPackage (*.gpkg)",
                                              options=QFileDialog.Option.DontConfirmOverwrite)
        if not path:
            return
        if not path.lower().endswith(".gpkg"):
            path += ".gpkg"
        project = QgsProject.instance()
        crs_dialog = QgsProjectionSelectionDialog(window)
        crs_dialog.setWindowTitle("Projected CRS of the Groundwork project (metres)")
        if project.crs().isValid():
            crs_dialog.setCrs(project.crs())
        if crs_dialog.exec() != QDialog.DialogCode.Accepted:
            return
        crs = crs_dialog.crs()
        try:
            store = project_actions.new_store(Path(path), crs.authid(), project)
        except FileExistsError:
            QMessageBox.warning(window, "New Groundwork project",
                                f"{Path(path).name} already exists. Groundwork will not "
                                "overwrite an existing project file; choose another name.")
            return
        except (ValueError, OSError, RuntimeError) as exc:     # RuntimeError: GDAL write
            QMessageBox.warning(window, "New Groundwork project", str(exc))
            return
        if not project.crs().isValid():
            project.setCrs(QgsCoordinateReferenceSystem(crs.authid()))
        self.set_store(store)

    def open_workbench_project(self):
        window = self.iface.mainWindow()
        path, _ = QFileDialog.getOpenFileName(window, "Open Groundwork project", "",
                                              "GeoPackage (*.gpkg)")
        if not path:
            return
        try:
            store = project_actions.open_store(Path(path), QgsProject.instance())
        except (ValueError, OSError, RuntimeError) as exc:   # corrupt, locked or not a gpkg
            QMessageBox.warning(window, "Open Groundwork project", str(exc))
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
        dialog.show()                                    # non-modal: "Pick on Map" needs the map

    def _profile_created(self, dialog):
        if dialog.profile is not None and self.dock is not None and self.provider is not None:
            self.show_section_panel()
            self.dock.open_profile(dialog.profile.id)

    def _close_profile_dialog(self):
        dialog, self._profile_dialog = self._profile_dialog, None
        if dialog is not None:
            dialog.reject()
            dialog.deleteLater()

    def add_data(self):
        """Add Data…: non-modal (its placement can pick on the map), one at a time; the
        profile open in the section panel is preselected."""
        from .ui.add_data_dialog import AddDataDialog
        if self.store is None:
            return
        if self._data_dialog is not None:
            self._data_dialog.show()
            self._data_dialog.raise_()
            self._data_dialog.activateWindow()
            return
        pid = None if self.dock is None else self.dock.current_profile_id()
        dialog = AddDataDialog(self.iface, self.store, pid, provider=self.provider,
                               project=QgsProject.instance())
        dialog.accepted.connect(lambda: self._data_added(dialog))
        dialog.finished.connect(lambda _r, d=dialog: self._data_finished(d))
        self._data_dialog = dialog
        dialog.show()

    def _data_added(self, dialog):
        """A profile made by Add Data opens in the section panel."""
        if dialog.created:
            self._profile_created(dialog)

    def _data_finished(self, dialog):
        if self._data_dialog is dialog:
            self._data_dialog = None
            dialog.deleteLater()

    def _close_data_dialog(self):
        dialog, self._data_dialog = self._data_dialog, None
        if dialog is not None:
            dialog.reject()
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
                               exclude=own_layer_ids(self.store, project),
                               current_boreholes=self._current_boreholes)
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

    # -- profiles: rename and delete ---------------------------------------------------------
    def rename_profile(self, profile_id: str | None = None) -> None:
        """Open Profile Properties for the profile (the open one by default)."""
        from .ui.profile_properties_dialog import ProfilePropertiesDialog
        pid = profile_id or (self.dock.current_profile_id() if self.dock else None)
        if self.store is None or not pid:
            return
        dialog = ProfilePropertiesDialog(self.iface, self.store, pid, self.provider,
                                         QgsProject.instance(), dock=self.dock)
        try:
            dialog.exec()
        finally:
            dialog.deleteLater()

    def delete_profile(self, profile_id: str | None = None) -> None:
        from .ui import profile_actions
        from .ui.field_notes_dialog import after_change
        from .ui.project_actions import refresh_layers
        pid = profile_id or (self.dock.current_profile_id() if self.dock else None)
        if self.store is None or not pid:
            return
        name = self.store.profile(pid).name
        counts = self.store.profile_contents(pid)
        if not profile_actions.confirm_delete(self.iface.mainWindow(), name, counts):
            return
        if self.dock is not None and self.dock.current_profile_id() == pid:
            self.dock._close_profile()
        self.store.delete_profile(pid)
        project = QgsProject.instance()
        refresh_layers(self.store, project)
        if self.store.has_interpretation() and self.dock is not None:
            self.dock.interp.changed()               # rebuild the 3D and map layers
        if self.store.has_field_notes():
            after_change(self.store, self.provider, project)
        self.provider.notify_changed()
        if self.dock is not None:
            self.dock._fill_combo()
        self.attach_plates()                         # a plate of it shows "not found"
        self._update_actions()
        self._info(f"Profile “{name}” deleted from the Groundwork project.")

    def _info(self, text: str):
        bar = getattr(self.iface, "messageBar", None)
        if bar is not None:
            bar().pushInfo(MENU_TITLE, text)

    def show_plates(self):
        """Plates…: report plates (non-modal, one at a time)."""
        from .ui.plates_dialog import PlatesDialog
        if self.store is None:
            return
        if self._plates_dialog is not None:
            self._plates_dialog.show()
            self._plates_dialog.raise_()
            self._plates_dialog.activateWindow()
            return
        dialog = PlatesDialog(QgsProject.instance(), self.store, self.provider,
                              panel_profile=lambda: self.dock.current_profile_id()
                              if self.dock is not None else None,
                              parent=self.iface.mainWindow())
        dialog.finished.connect(lambda _r, d=dialog: self._plates_finished(d))
        self._plates_dialog = dialog
        dialog.show()

    def _plates_finished(self, dialog):
        if self._plates_dialog is dialog:
            self._plates_dialog = None
            dialog.deleteLater()

    def _close_plates_dialog(self):
        dialog, self._plates_dialog = self._plates_dialog, None
        if dialog is not None:
            dialog.reject()
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
