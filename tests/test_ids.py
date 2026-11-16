"""The hidden identifiers of the old plugin stay as they were; only the package is renamed."""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PACKAGE = REPO / "groundwork_geophysics"
OLD_ID = "geophysics_workbench"


def test_hidden_ids_unchanged():
    from qgis.core import QgsLayoutItemRegistry

    from groundwork_geophysics.plates import items, sources
    from groundwork_geophysics.section import borehole_style, borehole_viewer, dock, profile_source
    from groundwork_geophysics.ui import add_data_dialog, context_dialog, derived_layers, project_actions

    assert (project_actions.SCOPE == sources.SCOPE == borehole_viewer.SCOPE
            == borehole_style.STYLE_SCOPE == OLD_ID)
    assert profile_source.SOURCE_ID == OLD_ID
    assert profile_source.RESULTS_TYPE == "geophysics_workbench_section"
    assert derived_layers._FLAG == "geophysics_workbench/derived"
    assert project_actions.STORE_KEY == "store_path"
    assert dock.SPLITTER_KEY == "geophysics_workbench/section/splitter"
    assert borehole_viewer.GEOMETRY_KEY == "geophysics_workbench/borehole_viewer/geometry"
    assert add_data_dialog.SETTINGS_KEY == "geophysics_workbench/import/last"
    assert context_dialog.SIZE_KEY == "geophysics_workbench/context_dialog/size"
    assert items.COLOUR_BAR_TYPE - QgsLayoutItemRegistry.PluginItem == 4712
    assert items.BOREHOLE_LEGEND_TYPE - QgsLayoutItemRegistry.PluginItem == 4713


def test_ids_module_holds_the_names():
    from groundwork_geophysics import ids

    assert ids.NAME == "Groundwork"
    assert ids.SUBTITLE == "geophysical profiles in QGIS"
    assert ids.LEGACY_ID == OLD_ID
    assert ids.LEGACY_NAME == "Geophysics Workbench"


def test_old_id_only_in_ids():
    offenders = []
    for pattern in ("*.py", "*.txt", "*.qpt", "*.qml", "*.xml"):
        for path in PACKAGE.rglob(pattern):
            if path.name == "ids.py" and path.parent == PACKAGE:
                continue
            if OLD_ID in path.read_text(encoding="utf-8", errors="replace"):
                offenders.append(path.relative_to(REPO).as_posix())
    assert offenders == []


def test_package_is_groundwork_geophysics():
    import groundwork_geophysics

    assert hasattr(groundwork_geophysics, "classFactory")
    assert not (REPO / OLD_ID).exists()
