"""Borehole style window: QGIS's own style editor on an in-memory copy of the interval table."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "section"))
from test_context_layers import _add, _layer, project  # noqa: E402,F401


@pytest.fixture
def logs(project):
    log = _layer(project, "NoGeometry", "Log",
                 "bid:string&field=top:double&field=bot:double&field=lith:string")
    _add(log, None, ["B1", 0.0, 2.0, "sand"])
    _add(log, None, ["B1", 2.0, 3.0, "clay"])
    _add(log, None, ["B2", 0.0, 1.0, "peat"])
    return log


def _entry(log):
    from geophysics_workbench.core.context_settings import BoreholeSetting
    return BoreholeSetting("pts", "bid", "", log.id(), "bid", "top", "bot", "lith")


def _categorized(colour="10,200,30"):
    from qgis.core import QgsCategorizedSymbolRenderer, QgsFillSymbol, QgsRendererCategory
    return QgsCategorizedSymbolRenderer("lith", [QgsRendererCategory(
        "sand", QgsFillSymbol.createSimple({"color": colour}), "sand")])


def test_style_copy_has_fields_and_all_rows_for_local_source(logs):
    from geophysics_workbench.ui.borehole_style_dialog import style_copy
    copy = style_copy(logs, None, "bid")
    assert copy.isSpatial() and copy.featureCount() == 3
    assert copy.fields().names() == logs.fields().names()


def test_style_copy_filters_ids_for_remote_provider(logs):
    from geophysics_workbench.ui.borehole_style_dialog import style_copy
    copy = style_copy(logs, ["B2"], "bid")
    assert copy.featureCount() == 1
    assert next(copy.getFeatures())["lith"] == "peat"


def test_remote_detection(logs, monkeypatch):
    from geophysics_workbench.ui import borehole_style_dialog as m
    assert not m.is_remote(logs)
    monkeypatch.setattr(type(logs), "providerType", lambda self: "WFS")
    assert m.is_remote(logs)


def test_copy_is_never_added_to_project(project, logs, qgis_app):
    from geophysics_workbench.ui.borehole_style_dialog import BoreholeStyleDialog
    before = set(project.mapLayers())
    dlg = BoreholeStyleDialog(project, _entry(logs), ["B1"], lambda: None)
    assert set(project.mapLayers()) == before
    dlg.close()


def test_apply_saves_renderer_and_calls_back(project, logs, qgis_app):
    from geophysics_workbench.section.borehole_style import load_renderer
    from geophysics_workbench.ui.borehole_style_dialog import BoreholeStyleDialog
    calls = []
    dlg = BoreholeStyleDialog(project, _entry(logs), ["B1"], lambda: calls.append(1))
    dlg.copy.setRenderer(_categorized())
    dlg.reload_editor()
    dlg.apply()
    saved = load_renderer(project, logs.id())
    assert saved is not None and saved.type() == "categorizedSymbol"
    assert calls == [1]
    dlg.close()


def test_existing_style_is_loaded_into_the_editor(project, logs, qgis_app):
    from geophysics_workbench.section.borehole_style import save_renderer
    from geophysics_workbench.ui.borehole_style_dialog import BoreholeStyleDialog
    save_renderer(project, logs.id(), _categorized())
    dlg = BoreholeStyleDialog(project, _entry(logs), [], lambda: None)
    assert dlg.copy.renderer().type() == "categorizedSymbol"
    dlg.close()


def test_export_import_round_trip(project, logs, qgis_app, tmp_path):
    from geophysics_workbench.section.borehole_style import load_renderer
    from geophysics_workbench.ui.borehole_style_dialog import BoreholeStyleDialog
    dlg = BoreholeStyleDialog(project, _entry(logs), [], lambda: None)
    dlg.copy.setRenderer(_categorized("1,2,3"))
    dlg.reload_editor()
    path = tmp_path / "cores.qml"
    assert dlg.export_to(str(path)) and path.is_file()
    other = BoreholeStyleDialog(project, _entry(logs), [], lambda: None)
    assert other.import_from(str(path))
    other.apply()
    c = load_renderer(project, logs.id()).categories()[0].symbol().color()
    assert (c.red(), c.green(), c.blue()) == (1, 2, 3)
    dlg.close()
    other.close()


def test_remote_note_names_the_profile(project, logs, qgis_app, monkeypatch):
    from geophysics_workbench.ui import borehole_style_dialog as m
    monkeypatch.setattr(m, "is_remote", lambda layer: True)
    dlg = m.BoreholeStyleDialog(project, _entry(logs), ["B1"], lambda: None,
                                profile_name="Transect 3")
    assert "Transect 3" in dlg.note.text() and dlg.copy.featureCount() == 2
    dlg.close()


def test_editor_is_embedded_and_visible(project, logs, qgis_app):
    """QGIS's style editor is a QDialog: it must sit inside the window as a widget (the
    window was empty when it stayed a separate, hidden top-level dialog)."""
    from geophysics_workbench.ui.borehole_style_dialog import BoreholeStyleDialog
    dlg = BoreholeStyleDialog(project, _entry(logs), [], lambda: None)
    dlg.show()
    qgis_app.processEvents()
    assert not dlg.editor.isWindow()
    assert dlg.editor.isVisible() and dlg.editor.height() > 100
    dlg.reload_editor()
    qgis_app.processEvents()
    assert not dlg.editor.isWindow() and dlg.editor.isVisible()
    dlg.close()
