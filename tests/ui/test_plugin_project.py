"""Plugin menu actions that open workbench projects."""
import pytest


@pytest.mark.parametrize("error", [RuntimeError("not a GeoPackage (OGR error)"),
                                   OSError("permission denied: file is locked"),
                                   ValueError("no workbench tables")])
def test_open_workbench_project_errors_are_shown(qgis_app, fake_iface, tmp_path, warnings_shown,
                                                 monkeypatch, error):
    """A corrupt, locked or foreign .gpkg shows a message box instead of a traceback."""
    from qgis.PyQt.QtWidgets import QFileDialog

    from groundwork_geophysics.plugin import WorkbenchPlugin
    from groundwork_geophysics.ui import project_actions

    target = tmp_path / "broken.gpkg"
    target.write_bytes(b"not a database")

    def fail(*_a, **_k):
        raise error

    monkeypatch.setattr(QFileDialog, "getOpenFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    monkeypatch.setattr(project_actions, "open_store", fail)
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.open_workbench_project()
        assert warnings_shown == [str(error)]
        assert plugin.provider is None and plugin.source is None
    finally:
        plugin.unload()


def test_a_models_section_style_comes_back_with_the_project(qgis_app, fake_iface, tmp_path,
                                                            store_with_model):
    """A style changed in the section is kept in the project file and is there again when
    the project is opened next time."""
    from dataclasses import replace

    from qgis.core import QgsProject

    from groundwork_geophysics.core.colors import ColorScale
    from groundwork_geophysics.plugin import WorkbenchPlugin
    from groundwork_geophysics.ui.project_actions import write_store_entry

    st, _p, _src = store_with_model
    project = QgsProject.instance()
    project.setFileName(str(tmp_path / "p.qgz"))
    write_store_entry(project, st.path)
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    try:
        plugin.set_store(st)
        style = replace(plugin.provider.style("d1"), mode="smooth",
                        scale=ColorScale("viridis", 3.0, 300.0, True))
        plugin.provider.set_style("d1", style)
        assert project.write()
        project.clear()
        assert project.read(str(tmp_path / "p.qgz"))
        assert plugin.provider is not None
        got = plugin.provider.style("d1")
        assert got.mode == "smooth" and got.scale == style.scale
    finally:
        plugin.unload()
        project.clear()
