"""The 3D view's point clouds and contour lines are computed in a QGIS task; filling the 3D
layers afterwards only picks up the files."""
import pytest

from tests.section.test_model_reading import _wait
from tests.ui.test_view3d_layers import _choose, _mode, setup  # noqa: F401

#: these tests run the 3D preparation themselves (not at once, as other tests get it)
pytestmark = pytest.mark.background_reads


def test_pending_lists_missing_files_only(setup):  # noqa: F811
    from groundwork_geophysics.ui.view3d_prepare import pending_3d, run_job3d
    st, p, provider, prj = setup
    _mode(provider, p, "smooth+contours")
    _choose(prj, ["d"])
    jobs = pending_3d(st, provider, prj)
    assert sorted(j.kind for j in jobs) == ["cloud", "contours"]
    for job in jobs:
        run_job3d(job)
    assert all(job.path.exists() for job in jobs)
    assert pending_3d(st, provider, prj) == []


def test_run_job3d_writes_what_sync_reuses(setup, monkeypatch):  # noqa: F811
    from groundwork_geophysics.core import view3d
    from groundwork_geophysics.ui import view3d_layers
    from groundwork_geophysics.ui.view3d_prepare import pending_3d, run_job3d
    st, p, provider, prj = setup
    _mode(provider, p, "smooth+contours")
    _choose(prj, ["d"])
    for job in pending_3d(st, provider, prj):
        run_job3d(job)
    calls = []
    monkeypatch.setattr(view3d_layers, "_write_cloud", lambda *a: calls.append("cloud") or 0)
    real = view3d.field_contours
    monkeypatch.setattr(view3d, "field_contours",
                        lambda *a, **k: calls.append("contours") or real(*a, **k))
    out = view3d_layers.sync(st, provider, prj, create=True)
    assert calls == []
    assert out["clouds"]["d"].isValid() and out["contours"].featureCount() > 0


def test_show_in_3d_reads_and_grids_in_the_background(qgis_app, fake_iface, store_with_model):
    """The plugin's 3D refill returns at once; the clouds come when the tasks are done."""
    from qgis.core import QgsProject

    from groundwork_geophysics.plugin import WorkbenchPlugin
    from groundwork_geophysics.ui.view3d_layers import Choice, clouds_3d, write_choice
    st, p, _src = store_with_model
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    project = QgsProject.instance()
    try:
        plugin.set_store(st)
        style = plugin.provider.style("d1")
        from dataclasses import replace
        plugin.provider.set_style("d1", replace(style, mode="smooth"))
        write_choice(project, Choice(frozenset(["d1"])))
        assert plugin._sync_3d(create=True) == {}           # nothing waited for
        _wait(qgis_app, lambda: "d1" in clouds_3d(project), 60.0)
    finally:
        plugin.unload()
        project.clear()


def test_a_refill_while_preparing_waits_for_the_task(qgis_app, fake_iface, store_with_model,
                                                      monkeypatch):
    """A style change during "Preparing 3D" never makes the clouds on the main thread."""
    import threading
    from dataclasses import replace

    from qgis.core import QgsProject

    from groundwork_geophysics.plugin import WorkbenchPlugin
    from groundwork_geophysics.ui import view3d_layers
    from groundwork_geophysics.ui.view3d_layers import Choice, clouds_3d, write_choice
    main = threading.get_ident()
    on_main = []
    real = view3d_layers._write_cloud
    monkeypatch.setattr(view3d_layers, "_write_cloud", lambda *a: on_main.append(
        threading.get_ident() == main) or real(*a))
    st, _p, _src = store_with_model
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    project = QgsProject.instance()
    try:
        plugin.set_store(st)
        plugin.provider.set_style("d1", replace(plugin.provider.style("d1"), mode="smooth"))
        write_choice(project, Choice(frozenset(["d1"])))
        plugin._sync_3d(create=True)
        _wait(qgis_app, lambda: plugin._prepare_tasks or "d1" in clouds_3d(project))
        plugin._sync_3d(create=True)                    # a refill while it runs
        _wait(qgis_app, lambda: "d1" in clouds_3d(project), 60.0)
        assert on_main and not any(on_main)
    finally:
        plugin.unload()
        project.clear()


def test_a_section_picture_is_painted_by_the_job_not_the_fill(setup, monkeypatch):  # noqa: F811
    """Show in 3D with every model as a Section Picture: the picture is listed with the
    other files to prepare, the job paints it, and filling the 3D layers only picks it up."""
    from groundwork_geophysics.ui import view3d_layers
    from groundwork_geophysics.ui.view3d_prepare import pending_3d, run_job3d
    st, p, provider, prj = setup
    _choose(prj, ["d"], looks={"d": "picture"})
    jobs = pending_3d(st, provider, prj)
    assert [j.kind for j in jobs] == ["picture"]
    for job in jobs:
        run_job3d(job)
    assert jobs[0].path.exists() and jobs[0].path.with_suffix(".glb").exists()
    assert pending_3d(st, provider, prj) == []
    monkeypatch.setattr(view3d_layers, "_write_picture",
                        lambda *a, **k: pytest.fail("painted while filling the 3D layers"))
    out = view3d_layers.sync(st, provider, prj, create=True)
    assert out["pictures"][p.id].isValid()


def test_the_plugin_paints_section_pictures_off_the_main_thread(qgis_app, fake_iface,
                                                                store_with_model, monkeypatch):
    import threading

    from qgis.core import QgsProject

    from groundwork_geophysics.plugin import WorkbenchPlugin
    from groundwork_geophysics.ui import view3d_layers
    from groundwork_geophysics.ui.view3d_layers import Choice, pictures_3d, write_choice
    main = threading.get_ident()
    on_main = []
    real = view3d_layers._write_picture
    monkeypatch.setattr(view3d_layers, "_write_picture", lambda *a, **k: on_main.append(
        threading.get_ident() == main) or real(*a, **k))
    st, p, _src = store_with_model
    plugin = WorkbenchPlugin(fake_iface)
    plugin.initGui()
    project = QgsProject.instance()
    try:
        plugin.set_store(st)
        write_choice(project, Choice(frozenset(["d1"]), looks={"d1": "picture"}))
        assert plugin._sync_3d(create=True) == {}           # nothing waited for
        _wait(qgis_app, lambda: p.id in pictures_3d(project), 60.0)
        assert on_main and not any(on_main)
    finally:
        plugin.unload()
        project.clear()
