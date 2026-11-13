"""Interpretation controls of the section dock: the tool bar row, drawing, saving.

Every finished piece goes through the open attribute form, is saved to the store at once,
the derived 3D/footprint layers are rebuilt and the section is redrawn.
"""
from __future__ import annotations

import weakref

import numpy as np

from qgis.core import QgsExpressionContextUtils, QgsProject
from qgis.PyQt.QtCore import QObject
from qgis.PyQt.QtWidgets import QButtonGroup, QHBoxLayout, QMenu, QMessageBox, QToolButton

from ..core.interpretation import (InterpFeature, InterpPiece, clamp_to_surface, new_id,
                                   normalise, type_suggestions)
from ..ui.interp_form import ask_feature
from .interp_tools import DrawTool, EditTool, plot_tolerance
from .interp_undo import InterpUndo

#: one line per tool in the panel's hint line: how to use it (as in QGIS digitising)
TOOL_HINTS = {
    "line": "Line: click to add points, right-click to finish, Esc to cancel",
    "polygon": "Polygon: click to add corners, right-click to close, Esc to cancel",
    "point": "Point: click to place it",
    "note": "Note: click for a note at one place, drag for a stretch",
    "edit": "Edit: click a piece to select it, drag its points, right-click for more",
}
TOOLS = (("pan", "Pan"), ("line", "Line"), ("polygon", "Polygon"), ("point", "Point"),
         ("edit", "Edit"), ("note", "Note"))
#: QGIS theme icons of the row's buttons (the text is the fallback and the tooltip)
ICONS = {"pan": "mActionPan.svg", "line": "mActionCaptureLine.svg",
         "polygon": "mActionCapturePolygon.svg", "point": "mActionCapturePoint.svg",
         "edit": "mActionVertexToolActiveLayer.svg", "snap": "mIconSnapping.svg",
         "note": "mActionTextAnnotation.svg",
         "undo": "mActionUndo.svg", "redo": "mActionRedo.svg"}


def _icon_button(icon_name: str, text: str) -> QToolButton:
    from qgis.core import QgsApplication
    b = QToolButton()
    icon = QgsApplication.getThemeIcon(icon_name)
    if icon.isNull() or not icon.availableSizes():
        b.setText(text if len(text) <= 12 else text.split(" ")[0])
    else:
        b.setIcon(icon)
        b.setAutoRaise(True)
    b.setToolTip(text)
    return b


#: coverage-edge snap lines per (layer, settings): computing them grids the coverage
_EDGE_CACHE: dict = {}


def current_author() -> str:
    scope = QgsExpressionContextUtils.globalScope()
    for name in ("user_full_name", "user_account_name"):
        value = scope.variable(name)
        if value:
            return str(value)
    import getpass
    try:
        return getpass.getuser()
    except Exception:                       # no account name available
        return ""


class InterpController(QObject):
    def __init__(self, dock):
        super().__init__(dock)
        # weak: a strong back-reference makes dock <-> controller a Python cycle, so the dock's
        # wrapper outlives its C++ object and a late garbage collection deletes it twice
        self._dock = weakref.ref(dock)
        self.tool = None
        self._sync = None
        self._targets = None                    # (exclude, SnapTargets): no store reads per move
        #: (feature, type suggestions, names in use) -> edited feature or None (cancel).
        #: Every drawn piece starts its own feature: interpretation stays per profile;
        #: linking across profiles is a separate, deliberate step.
        self.form_factory = lambda f, s, names: ask_feature(self.dock, f, s, names)
        #: (note, known categories) -> edited note or None (cancel)
        from ..ui.field_notes_dialog import ask_note
        self.note_form_factory = lambda note, cats: ask_note(self.dock, note, cats)
        self.bar = QHBoxLayout()
        self.buttons: dict = {}
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for key, text in TOOLS:
            b = _icon_button(ICONS[key], text)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, k=key: self.stop() if k == "pan" else self.start(k))
            self.group.addButton(b)
            self.bar.addWidget(b)
            self.buttons[key] = b
        b = _icon_button(ICONS["snap"], "Snap to vertices of drawn pieces, borehole layer "
                                        "boundaries, the coverage fade edge and the ground "
                                        "line")
        b.setCheckable(True)
        b.setChecked(True)
        self.bar.addWidget(b)
        self.buttons["snap"] = b
        self.undo = InterpUndo(self, self._apply, self._apply_rows)
        # after every undo/redo the Edit tool's selection is read again from the store (it
        # must never hold an undone shape: the next edit would save it back)
        self.undo.stack.indexChanged.connect(self._refresh_selection)
        for text, slot, signal in (("Undo", self.undo.stack.undo, self.undo.stack.canUndoChanged),
                                   ("Redo", self.undo.stack.redo, self.undo.stack.canRedoChanged)):
            b = _icon_button(ICONS[text.lower()], text)
            b.setEnabled(False)
            b.clicked.connect(slot)
            signal.connect(b.setEnabled)
            self.bar.addWidget(b)
            self.buttons[text.lower()] = b
        #: everything that is not drawing lives in one menu, so the row stays short
        self.menu = QMenu(dock)
        self.menu.setToolTipsVisible(True)
        act = self.menu.addAction("Types…")
        act.setToolTip("Rename or merge interpretation types")
        act.triggered.connect(self.show_types)
        self.buttons["types"] = act
        act = self.menu.addAction("Export…")
        act.setToolTip("Export the selected feature's 3D pieces (in Edit), or all features of "
                       "the shown version, to GeoPackage or DXF")
        act.triggered.connect(self.export)
        self.buttons["export"] = act
        self.menu.addSeparator()
        act = self.menu.addAction("Field Notes…")
        act.setToolTip("The field notes of this profile: add, edit, switch off, delete")
        act.triggered.connect(self.show_field_notes)
        self.buttons["field_notes"] = act
        act = self.menu.addAction("Show Field Notes")
        act.setCheckable(True)
        act.setChecked(True)
        act.setToolTip("Draw the field notes along the top of the section")
        act.toggled.connect(self._show_field_notes)
        self.buttons["show_notes"] = act
        menu_button = QToolButton()
        menu_button.setText("Interpretation")
        menu_button.setToolTip("Types, export, field notes and versions of the interpretation")
        menu_button.setMenu(self.menu)
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.bar.addWidget(menu_button)
        #: asks for the export file (None cancels) and reports the result; tests replace them
        self.ask_path = self._ask_path
        self.info = lambda text: QMessageBox.information(self.dock, "Interpretation", text)
        self.bar.addStretch(1)
        from .interp_versions import VersionBar
        self.versions = VersionBar(self)
        self.menu.addSeparator()
        self.menu.addAction(self.versions.freeze_button)
        self.menu.addAction(self.versions.restore_button)
        self.menu.addSeparator()
        self.menu.addMenu(self.versions.compare_menu)
        self.bar.addWidget(self.versions.widget)
        self.buttons["pan"].setChecked(True)
        #: asks the user to confirm a deletion; tests replace it
        self.confirm = lambda text: QMessageBox.question(
            self.dock, "Interpretation", text) == QMessageBox.StandardButton.Yes
        dock.profile_changed.connect(self._profile_changed)

    @property
    def dock(self):
        return self._dock()

    # -- tools -------------------------------------------------------------------------------
    def writable(self) -> bool:
        """False while a frozen version is shown (read-only)."""
        prov = self.dock.provider
        if prov is None or prov.interp_version_id is None:
            return True
        store = prov.store
        return not store.has_interpretation() or prov.interp_version_id == \
                store.current_version().id

    def surface(self):
        """The drawn ground line of the open profile, or None."""
        try:
            self.dock._current_layers()         # fills the dock's cached topography
        except Exception:                       # a broken layer must not block drawing
            pass
        return self.dock._topo

    def snap_targets(self, exclude: str | None = None):
        """Vertices of the open profile's current pieces (all features, but not the piece
        ``exclude`` being edited), borehole layer boundaries, and the ground line."""
        from ..core.interp_snap import SnapTargets
        if self._targets is not None and self._targets[0] == exclude:
            return self._targets[1]
        verts = [v for p in self.current_pieces() if p.id != exclude for v in p.vertices]
        bounds = []
        try:
            ctx = self.dock.provider.context(self.dock.current_profile_id())
        except Exception:                       # broken context must not block drawing
            ctx = None
        surface = self.surface()
        for p in (ctx.points if ctx is not None else []):
            if p.kind != "borehole":
                continue
            top = p.z_top
            if top is None and surface is not None and len(surface[0]):
                top = float(np.interp(p.s, *surface))   # hung from the ground, as drawn
            if top is None:
                continue
            for iv in p.log:
                bounds += [(p.s, top - iv.top), (p.s, top - iv.bottom)]
        targets = SnapTargets(verts, sorted(set(bounds)), surface,
                              lines=self._coverage_edges(surface))
        self._targets = (exclude, targets)
        return targets

    def _coverage_edges(self, surface) -> list:
        """The faded edge (coverage threshold contour) of every visible layer with its
        coverage fade on: the user draws "unreliable" zones along it by hand. Memoised per
        layer and settings; a mesh that cannot be gridded gives no edge."""
        from ..core import gridding
        prov = self.dock.provider
        out = []
        try:
            layers = prov.layers(self.dock.current_profile_id())
        except Exception:                       # a broken layer must not block drawing
            return out
        for layer in layers:
            st, mesh = layer.style, layer.mesh
            if (mesh is None or not st.visible or not st.fade_coverage
                    or mesh.coverage is None):
                continue
            thr = st.coverage_threshold
            if thr is None:
                thr = gridding.default_threshold(mesh.coverage)
            topo_key = None if surface is None else (np.asarray(surface[0]).tobytes(),
                                                     np.asarray(surface[1]).tobytes())
            key = (layer.dataset.id, hash(mesh.vertices.tobytes()),
                   hash(mesh.coverage.tobytes()), thr, st.grid_cell, topo_key)
            lines = _EDGE_CACHE.get(key)
            if lines is None:
                try:
                    grid = gridding.grid_model(mesh, surface,
                                               gridding.grid_shape(mesh, st.grid_cell),
                                               False, values=mesh.coverage)
                    lines = [x for _lv, ls in gridding.contour_lines(grid, [thr], False)
                             for x in ls]
                except ValueError:              # cannot be gridded: drawn as cells, no edge
                    lines = []
                _EDGE_CACHE[key] = lines
                while len(_EDGE_CACHE) > 8:
                    _EDGE_CACHE.pop(next(iter(_EDGE_CACHE)))
            out += lines
        return out

    def snap(self, s: float, z: float, tol_s: float, tol_z: float,
             exclude: str | None = None) -> tuple[float, float]:
        """(s, z) snapped to the nearest target when snapping is on; else unchanged."""
        from ..core.interp_snap import snap
        if not self.buttons["snap"].isChecked():
            return s, z
        hit = snap(s, z, self.snap_targets(exclude), tol_s, tol_z)
        return (s, z) if hit is None else hit

    def hover(self, plot_point) -> None:
        self.dock._hovered(None, plot_point)

    def current_pieces(self) -> list:
        store = self.dock.provider.store
        if not store.has_interpretation():
            return []
        return store.pieces(store.current_version().id, self.dock.current_profile_id())

    def start(self, kind: str) -> None:
        self._targets = None
        if kind == "note":
            self._start_note()
            return
        if (self.dock.provider is None or self.dock.current_profile_id() is None
                or not self.writable()):
            self.stop()
            return
        if kind == "edit":
            self.tool = EditTool(self.dock.canvas, self)
            self.dock.canvas.setTool(self.tool)
            self.buttons["edit"].setChecked(True)
            self.dock.canvas.setFocus()
            self._show_hint("edit")
            return
        canvas = self.dock.canvas
        self.tool = DrawTool(canvas, kind, lambda pts, k=kind: self._finished(k, pts),
                             on_cancel=self.stop,
                             on_hover=lambda pp: self.dock._hovered(None, pp),
                             snap=lambda s, z, pos: self.snap(s, z,
                                                              *plot_tolerance(canvas, pos)))
        self.dock.canvas.setTool(self.tool)
        self.buttons[kind].setChecked(True)
        self.dock.canvas.setFocus()
        self._show_hint(kind)

    def ensure_sync(self) -> None:
        """Rebuild the derived layers when attributes are edited in QGIS's own tools."""
        from ..ui.interp_layers import InterpSync, interp_layers
        prov = self.dock.provider
        layer = None
        if prov is not None and prov.store.has_interpretation():
            layer = interp_layers(prov.store, QgsProject.instance()).get("interp_features")
        if self._sync is not None and (layer is None or self._sync._layer is not layer):
            self._sync.detach()                 # another store, or none: never act on it again
            self._sync = None
        if layer is None or self._sync is not None:
            return
        store = prov.store
        # the derived (map/3D) layers always hold the current version; bound to this store
        self._sync = InterpSync(store, QgsProject.instance(), prov.notify_redraw,
                                version_id=lambda: store.current_version().id,
                                chainages=lambda: {p.id: p.chainage for p in store.profiles()})

    def _profile_changed(self, *_args) -> None:
        self._targets = None
        self.ensure_sync()
        self.stop()
        self.undo.clear()
        self.versions.refresh(self.versions.combo.currentData() or "")

    def stop(self) -> None:
        dock = self.dock
        if dock is None:
            return
        dock.canvas.setTool(dock._pan_tool)
        self.tool = None
        self.buttons["pan"].setChecked(True)
        dock.set_tool_hint(None)

    def _refresh_selection(self, *_args) -> None:
        tool = self.tool
        selected = getattr(tool, "selected", None)
        if selected is None or self.dock is None or self.dock.provider is None:
            return
        store = self.dock.provider.store
        fresh = next((p for p in store.pieces(selected.version_id, selected.profile_id)
                      if p.id == selected.id), None)
        vertex = getattr(tool, "vertex", None)
        if fresh is None or vertex is None or vertex >= len(fresh.vertices):
            vertex = None
        tool.select(fresh, vertex)                      # a dragged vertex stays selected

    def _show_hint(self, kind: str) -> None:
        self.dock.set_tool_hint(TOOL_HINTS.get(kind))

    # -- saving ------------------------------------------------------------------------------
    def _based_on(self, profile_id: str) -> tuple[str, str]:
        try:
            for layer in self.dock.provider.layers(profile_id):
                if layer.mesh is not None:
                    return layer.dataset.id, str(layer.dataset.version)
        except Exception:                   # a broken layer must not block saving
            pass
        return "", ""

    def chainages(self) -> dict:
        return {p.id: p.chainage for p in self.dock.provider.store.profiles()}

    def _finished(self, kind: str, points: list) -> None:
        store = self.dock.provider.store
        profile_id = self.dock.current_profile_id()
        if profile_id is None:
            return
        store.ensure_interpretation()
        version = store.current_version()
        dataset, dversion = self._based_on(profile_id)
        points = clamp_to_surface(points, self.surface())
        piece = normalise(InterpPiece(new_id(), version.id, "", profile_id, kind, points,
                                      based_on_dataset=dataset, based_on_version=dversion))
        feature = InterpFeature(new_id(), version.id, author=current_author())
        names = self._names_on_profile(store, version.id, profile_id)
        edited = self.form_factory(feature, type_suggestions(store.used_types()), names)
        if edited is None:
            return
        edited.author = edited.author or feature.author
        piece.feature_id = edited.id
        self.undo.push("Add piece", (None, None), (edited, piece))     # saves it (redo)

    def changed(self, _version_id: str | None = None) -> None:
        """Rebuild the derived layers from the current version (map and 3D never show a
        frozen one), add them if new, redraw the section (which shows the chosen version)."""
        from ..ui.interp_layers import add_interp_layers, reload_interp_layers
        self._targets = None
        store = self.dock.provider.store
        project = QgsProject.instance()
        add_interp_layers(store, project)
        self.ensure_sync()
        store.rebuild_derived(store.current_version().id, self.chainages())
        reload_interp_layers(store, project)
        self.dock.provider.notify_redraw()

    # -- edits (through the undo stack) ------------------------------------------------------
    def _feature(self, piece):
        return next((f for f in self.dock.provider.store.features(piece.version_id)
                     if f.id == piece.feature_id), None)

    def replace_piece(self, old, new):
        """Save ``new`` in place of ``old`` (undoable); returns the saved piece."""
        import copy
        new = copy.deepcopy(new)
        new.vertices = clamp_to_surface(new.vertices, self.surface())
        new = normalise(new)
        self.undo.push("Edit piece", (None, old), (None, new))
        return new

    def delete_piece(self, piece) -> None:
        self.dock.provider.store._writable(piece.version_id)
        self.undo.push("Delete piece", (self._feature(piece), piece), (None, None))

    @staticmethod
    def _names_on_profile(store, version_id: str, profile_id, exclude=None) -> set[str]:
        """Names of the features drawn on this profile: interpretation is per profile, so
        "Clay A" on another profile is no clash."""
        here = {p.feature_id for p in store.pieces(version_id, profile_id)}
        return {f.name for f in store.features(version_id)
                if f.name and f.id in here and f.id != exclude}

    def edit_feature(self, feature_id: str) -> None:
        store = self.dock.provider.store
        version = store.current_version()
        feature = next((f for f in store.features(version.id) if f.id == feature_id), None)
        if feature is None:
            return
        names = self._names_on_profile(store, version.id, self.dock.current_profile_id(),
                                       exclude=feature_id)
        edited = self.form_factory(feature, type_suggestions(store.used_types()), names)
        if edited is None:
            return
        edited.author = edited.author or feature.author
        edited.extra = edited.extra or feature.extra
        self.undo.push("Edit attributes", (feature, None), (edited, None))

    def _apply(self, state: tuple, other: tuple) -> None:
        import copy
        store = self.dock.provider.store
        feat, piece = state
        _ofeat, opiece = other
        version = (piece or feat or opiece or _ofeat).version_id
        if piece is None and opiece is not None:
            store.delete_piece(opiece.id)
        if feat is not None:
            store.save_feature(copy.deepcopy(feat))
        if piece is not None:
            store.save_piece(copy.deepcopy(piece))
            self._mark_local(piece.profile_id)
        self.changed(version)

    def _mark_local(self, profile_id: str) -> None:
        """A piece saved on a profile without real heights (a local or referenced local
        section) marks the profile, so the pieces are re-hung once real heights arrive
        (``SectionDataProvider.settle_local_interpretation``). Written once, not per draw."""
        from .topography import LOCAL_KINDS
        prov = self.dock.provider
        try:
            profile = prov.store.profile(profile_id)
        except KeyError:
            return
        if profile.metadata.get("local_pieces"):
            return
        surface = prov.surface(profile_id)
        if surface is not None and surface.kind in LOCAL_KINDS:
            profile.metadata["local_pieces"] = True
            prov.store.save_profile(profile)

    def _start_note(self) -> None:
        from .interp_tools import NoteTool
        if self.dock.provider is None or self.dock.current_profile_id() is None:
            self.stop()
            return
        from qgis.core import QgsProject

        from ..ui.field_note_layers import stretch_rgb
        rgb = stretch_rgb(self.dock.provider.store, QgsProject.instance())
        self.tool = NoteTool(self.dock.canvas, self._note_finished, on_cancel=self.stop,
                             on_hover=self.hover, rgb=rgb)
        self.dock.canvas.setTool(self.tool)
        self.buttons["note"].setChecked(True)
        self.dock.canvas.setFocus()
        self._show_hint("note")

    def _note_finished(self, s_from: float, s_to: float | None) -> None:
        from ..core.field_notes import FieldNote
        from ..core.interpretation import new_id
        from ..ui.field_notes_dialog import categories
        store, profile_id = self.dock.provider.store, self.dock.current_profile_id()
        if profile_id is None:
            return
        note = self.note_form_factory(FieldNote(new_id(), profile_id, s_from, s_to, ""),
                                      categories(store))
        if note is None:
            return
        self.undo.push_with(self._apply_note, "Add note", (None,), (note,))

    def _apply_note(self, state: tuple, other: tuple) -> None:
        """Undo/redo of a field note: save the state's note, or delete the other one."""
        from ..ui.field_notes_dialog import after_change, save_note
        store = self.dock.provider.store
        (note,), (other_note,) = state, other
        if note is not None:
            save_note(store, note)
        elif other_note is not None:
            store.delete_field_note(other_note.id)
        after_change(store, self.dock.provider)

    def show_field_notes(self) -> None:
        from ..ui.field_notes_dialog import FieldNotesDialog, after_change
        profile_id = self.dock.current_profile_id()
        if self.dock.provider is None or profile_id is None:
            return
        store = self.dock.provider.store
        changed = []

        def on_change():
            changed.append(True)
            after_change(store, self.dock.provider)
        dlg = FieldNotesDialog(store, profile_id, on_change, self.dock)
        dlg.exec()
        dlg.deleteLater()
        if changed:     # the list's edits are not on the stack: its note commands are stale
            self.undo.clear()

    def _show_field_notes(self, on: bool) -> None:
        provider = self.dock.provider
        if provider is not None:
            provider.show_field_notes = bool(on)
            provider.notify_redraw()                # notes are read with each context

    def show_types(self) -> None:
        from ..ui.interp_types import TypesDialog
        store = self.dock.provider.store
        if not self.writable():
            return
        store.ensure_interpretation()
        TypesDialog(self.dock, lambda: store.type_counts(store.current_version().id),
                    self.rename_type).exec()

    def _ask_path(self) -> str | None:
        from qgis.PyQt.QtWidgets import QFileDialog
        path, _f = QFileDialog.getSaveFileName(self.dock, "Export interpretation", "",
                                               "GeoPackage (*.gpkg);;DXF (*.dxf)")
        return path or None

    def export(self) -> int:
        """Export the selected piece's feature (Edit tool) or every feature of the shown
        version; returns the number of pieces written."""
        from ..ui.interp_export import export_pieces, held_back_lines
        prov = self.dock.provider
        version = None if prov is None else prov.shown_interp_version()
        if version is None:
            return 0
        selected = getattr(self.tool, "selected", None)
        ids = None if selected is None else {selected.feature_id}
        path = self.ask_path()
        if not path:
            return 0
        if not path.lower().endswith((".gpkg", ".dxf")):
            path += ".gpkg"
        # a profile without heights is held back: its pieces have no real elevations
        held = {p.id for p in prov.store.profiles() if prov.is_local(p.id)}
        try:
            n = export_pieces(prov.store, version, ids, path, held_back=held)
        except (OSError, ValueError, RuntimeError) as exc:
            self.info(f"Export failed: {exc}")
            return 0
        lines = [f"Exported {n} piece{'s' if n != 1 else ''} to {path}"]
        self.info("\n".join(lines + held_back_lines(prov.store, version, ids, held)))
        return n

    # -- regrouping (one undo step each) -----------------------------------------------------
    def _apply_rows(self, state: tuple, other: tuple) -> None:
        import copy
        store = self.dock.provider.store
        feats, pieces = state
        ofeats, opieces = other
        for f in feats:
            store.save_feature(copy.deepcopy(f))
        for p in pieces:
            store.save_piece(copy.deepcopy(p))
        keep_p = {p.id for p in pieces}
        for p in opieces:
            if p.id not in keep_p:
                store.delete_piece(p.id)
        keep_f = {f.id for f in feats}
        gone = [f for f in ofeats if f.id not in keep_f]
        if gone:
            # a feature still holding a piece drawn after this step stays: deleting it would
            # take that piece with it (delete_feature cascades)
            used = {p.feature_id for p in store.pieces(gone[0].version_id)}
            for f in gone:
                if f.id not in used:
                    store.delete_feature(f.id)
        self.changed()

    def move_piece_to(self, piece, feature_id: str | None) -> None:
        """Give ``piece`` to feature ``feature_id``; ``None`` splits it off as a new feature
        with the old one's attributes (no name). A feature left without pieces goes."""
        import copy
        store = self.dock.provider.store
        store._writable(piece.version_id)
        if feature_id == piece.feature_id:
            return
        feats = {f.id: f for f in store.features(piece.version_id)}
        if feature_id is not None and feature_id not in feats:
            raise KeyError(feature_id)
        old = feats.get(piece.feature_id)
        before_f, after_f = ([old] if old else []), []
        if feature_id is None:
            new = InterpFeature(new_id(), piece.version_id, author=current_author())
            if old is not None:
                new.type, new.confidence, new.note = old.type, old.confidence, old.note
                new.extra = copy.deepcopy(old.extra)
            after_f.append(new)
            feature_id = new.id
        moved = copy.deepcopy(piece)
        moved.feature_id = feature_id
        if old is not None and any(p.feature_id == old.id and p.id != piece.id
                                   for p in store.pieces(piece.version_id)):
            after_f.append(old)
        self.undo.push_rows("Move piece", (before_f, [piece]), (after_f, [moved]))

    def merge_features(self, gone_id: str, keep_id: str) -> None:
        """All pieces of ``gone_id`` join ``keep_id``; ``gone_id`` is deleted."""
        import copy
        store = self.dock.provider.store
        feats = {}
        for v in store.versions():
            feats.update({f.id: f for f in store.features(v.id)})
        gone, keep = feats.get(gone_id), feats.get(keep_id)
        if gone is None or keep is None:
            raise KeyError(gone_id if gone is None else keep_id)
        store._writable(gone.version_id)
        if gone_id == keep_id:
            return
        if keep.version_id != gone.version_id:
            raise ValueError("features of different versions cannot be merged")
        pieces = [p for p in store.pieces(gone.version_id) if p.feature_id == gone_id]
        moved = [copy.deepcopy(p) for p in pieces]
        for p in moved:
            p.feature_id = keep_id
        self.undo.push_rows("Merge features", ([gone], pieces), ([], moved))

    def rename_type(self, old: str, new: str) -> int:
        """Every current feature of type ``old`` (any case) gets ``new``; a type already used
        with ``new``'s spelling in another case is taken over, which merges the two."""
        import copy
        store = self.dock.provider.store
        if not store.has_interpretation() or not new.strip():
            return 0
        feats = store.features(store.current_version().id)
        targets = [f for f in feats if f.type.strip().lower() == old.strip().lower()]
        spelling = next((f.type for f in feats if f not in targets
                         and f.type.strip().lower() == new.strip().lower()), new.strip())
        before = [f for f in targets if f.type != spelling]
        if not before:
            return 0
        after = [copy.deepcopy(f) for f in before]
        for f in after:
            f.type = spelling
        self.undo.push_rows("Rename type", (before, []), (after, []))
        return len(after)
