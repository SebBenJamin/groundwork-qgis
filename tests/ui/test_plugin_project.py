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
