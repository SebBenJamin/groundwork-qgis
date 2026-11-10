"""Usability round 1, Task 8: QGIS Human Interface Guidelines for every text the plugin shows.

Titles (buttons, menu items, group boxes, tabs) are title case; labels are sentence case and
never end with a colon; a text that opens a dialog ends with "…" (U+2026), never "...";
every tool button has a tooltip."""
import re

import pytest

SMALL = {"a", "an", "the", "and", "or", "nor", "but", "of", "to", "in", "on", "at", "by",
         "for", "from", "with", "into", "onto", "as", "per", "via", "vs", "is"}


def title_problem(text: str) -> str | None:
    t = re.sub(r"\([^)]*\)", "", text.replace("&", "")).replace("…", "").strip()
    words = re.findall(r"[^\W\d_][\w'’.\-]*", t)
    for i, w in enumerate(words):
        if w[0].islower() and not (w.lower() in SMALL and 0 < i < len(words) - 1):
            return f"title case: {text!r} ({w!r})"
    return None


def collect(widget):
    from qgis.PyQt.QtWidgets import (QAbstractButton, QCheckBox, QGroupBox, QLabel, QMenu,
                                     QPushButton, QRadioButton, QTabWidget, QToolButton)
    out = []
    for w in [widget] + widget.findChildren(object):
        if isinstance(w, QGroupBox) and w.title():
            out.append(("title", w.title(), w))
        elif isinstance(w, (QCheckBox, QRadioButton)) and w.text():
            out.append(("label", w.text(), w))
        elif isinstance(w, (QPushButton, QToolButton)) and isinstance(w, QAbstractButton):
            if w.text():
                out.append(("title", w.text(), w))
            if isinstance(w, QToolButton) and not w.objectName().startswith("Scroll"):
                out.append(("tool", w.toolTip(), w))       # (not Qt's own tab-scroll arrows)
        elif isinstance(w, QLabel) and w.text() and not w.text().lstrip().startswith("<"):
            out.append(("label", w.text(), w))
        elif isinstance(w, QTabWidget):
            out += [("title", w.tabText(i), w) for i in range(w.count())]
        elif isinstance(w, QMenu):
            out += [("title", a.text(), w) for a in w.actions() if a.text()]
    return out


def problems(entries, where: str) -> list[str]:
    """Rule breaks; the user's data (layer names) and values ("81.4–314 log") are skipped."""
    from qgis.core import QgsProject
    data = {layer.name() for layer in QgsProject.instance().mapLayers().values()}
    bad = []
    for kind, text, w in entries:
        if text.strip() in data or text.strip()[:1].isdigit():
            continue
        if "..." in text:
            bad.append(f"{where}: three dots instead of …: {text!r}")
        if kind == "title":
            p = title_problem(text)
            if p:
                bad.append(f"{where}: {p}")
        elif kind == "label":
            first = text.strip()[:1]
            if text.rstrip().endswith(":"):
                bad.append(f"{where}: label ends with a colon: {text!r}")
            if first.isalpha() and first.islower():
                bad.append(f"{where}: label not sentence case: {text!r}")
        elif kind == "tool" and not text.strip():
            bad.append(f"{where}: tool button without tooltip: {w.text()!r} "
                       f"{w.objectName()!r} {w.metaObject().className()}")
    return bad


@pytest.fixture
def world(qgis_app, fake_iface, store_with_model):
    from qgis.core import QgsProject

    from geophysics_workbench.core.context import ContextItems
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.ui.project_actions import use_store
    st, p, _ = store_with_model
    prj = QgsProject.instance()
    prj.clear()
    use_store(st, prj)
    prov = SectionDataProvider(st)
    prov.context_source = lambda profile: ContextItems()
    yield fake_iface, st, p, prov, prj
    prj.removeAllMapLayers()
    prj.clear()


def _dialogs(iface, st, p, prov, prj):
    from qgis.core import QgsCategorizedSymbolRenderer

    from geophysics_workbench.core.field_notes import FieldNote
    from geophysics_workbench.section.scale_dialog import ColorScaleDialog, DisplayDialog
    from geophysics_workbench.ui.add_model_dialog import AddModelDialog
    from geophysics_workbench.ui.context_dialog import ContextDialog
    from geophysics_workbench.ui.curve_style_dialog import CurveStyleDialog
    from geophysics_workbench.ui.dataset_info_dialog import DatasetInfoDialog
    from geophysics_workbench.ui.field_notes_dialog import FieldNotesDialog, NoteForm
    from geophysics_workbench.ui.misfit_panel import MisfitSummary
    from geophysics_workbench.ui.new_profile_dialog import NewProfileDialog
    from geophysics_workbench.ui.pattern_table import PatternTable
    from geophysics_workbench.ui.plates_dialog import PlateDetailsDialog, PlatesDialog
    ds = st.datasets(p.id)[0]
    layer = prov.layers(p.id)[0]
    return {
        "Colour scale": ColorScaleDialog(None),
        "Display": DisplayDialog(None, layer),
        "Add ERT model": AddModelDialog(iface, st, p.id, prov),
        "Context layers": ContextDialog(iface, prj),
        "Curve style": CurveStyleDialog(prj, {}, lambda: None),
        "Dataset info": DatasetInfoDialog(st, ds.id),
        "Field notes": FieldNotesDialog(st, p.id, lambda: None),
        "Note form": NoteForm(FieldNote("n", p.id, 1.0, None, ""), []),
        "Misfit summary": MisfitSummary(),
        "New profile": NewProfileDialog(iface, st, prj, prov),
        "Patterns": PatternTable(QgsCategorizedSymbolRenderer("x", [])),
        "Plates": PlatesDialog(prj, st, prov),
        "Plate details": PlateDetailsDialog(prj),
    }


def test_hig_rules_in_every_dialog(world):
    iface, st, p, prov, prj = world
    bad = []
    dialogs = _dialogs(iface, st, p, prov, prj)
    for name, dialog in dialogs.items():
        bad += problems(collect(dialog), name)
    assert not bad, "\n".join(bad)


def test_hig_rules_in_menu_and_panel(world, qgis_app):
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench import classFactory
    iface, st, p, prov, prj = world
    plugin = classFactory(iface)
    plugin.initGui()
    try:
        plugin.set_store(st)
        plugin.dock.open_profile(p.id)
        bad = problems([("title", a.text(), None) for a in plugin.actions], "plugin menu")
        bad += problems(collect(plugin.dock), "section panel")
        for menu in plugin.dock.findChildren(__import__("qgis.PyQt.QtWidgets",
                                                        fromlist=["QMenu"]).QMenu):
            bad += problems(collect(menu), f"menu {menu.title() or menu.objectName()}")
        assert not bad, "\n".join(bad)
    finally:
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()


def test_disabled_actions_say_why(qgis_app, fake_iface):
    from qgis.core import QgsProject
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench import classFactory
    QgsProject.instance().clear()
    plugin = classFactory(fake_iface)
    plugin.initGui()
    try:
        disabled = [a for a in plugin.actions if not a.isEnabled()]
        assert disabled
        for a in disabled:
            assert a.toolTip() and a.toolTip() != a.text().replace("&", ""), a.text()
        add = next(a for a in plugin.actions if a.text().startswith("Add ERT Model"))
        assert "Open a profile" in add.toolTip()
        pick = next(a for a in plugin.actions if a.text().startswith("Pick Profile"))
        assert not pick.isEnabled()
    finally:
        plugin.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
        qgis_app.processEvents()
