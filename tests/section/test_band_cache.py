"""Strips from web layers (the live geology of a state survey) are remembered per profile
beside the project and fetched in the background the first time; local layers are read as
before."""
import numpy as np
import pytest

from tests.section.test_context_layers import AUTH, _add, _layer, project  # noqa: F401


@pytest.fixture
def geology(project):  # noqa: F811
    from groundwork_geophysics.core.context_settings import BandSetting, ContextSettings
    from groundwork_geophysics.ui.context_dialog import write_settings
    geo = _layer(project, "Polygon", "Geo", "unit:string")
    _add(geo, "POLYGON((60 -10, 100 -10, 100 10, 60 10, 60 -10))", ["Loess"])
    _add(geo, "POLYGON((0 -10, 60 -10, 60 10, 0 10, 0 -10))", ["Sand"])
    write_settings(project, ContextSettings(bands=[BandSetting(geo.id(), "unit")]))
    return geo


@pytest.fixture
def web(monkeypatch):
    """Every layer counts as a web layer; counts the strip fetches."""
    from groundwork_geophysics.section import context_layers
    monkeypatch.setattr(context_layers, "is_remote", lambda layer: True)
    runs = []
    real = context_layers.run_band
    monkeypatch.setattr(context_layers, "run_band",
                        lambda job: runs.append(job) or real(job))
    return runs


def _profile(end=100.0):
    from groundwork_geophysics.core.model import Profile
    return Profile("p1", "P1", np.array([[0.0, 0.0], [end, 0.0]]), AUTH)


def _strips(project, cache, profile, **kw):  # noqa: F811
    from groundwork_geophysics.section.context_layers import ContextGatherer
    g = ContextGatherer(project, AUTH, kw.pop("on_change", lambda: None), cache_dir=cache)
    for k, v in kw.items():
        setattr(g, k, v)
    try:
        return [(b.label, round(b.s0), round(b.s1)) for b in g.items_for(profile).band], g
    finally:
        if not kw.get("background"):
            g.close()


SAND_LOESS = [("Sand", 0, 60), ("Loess", 60, 100)]


def test_a_web_strip_is_remembered(project, geology, web, tmp_path):  # noqa: F811
    assert _strips(project, tmp_path, _profile())[0] == SAND_LOESS
    assert len(web) == 1 and len(list(tmp_path.glob("strip-*.json"))) == 1
    assert _strips(project, tmp_path, _profile())[0] == SAND_LOESS
    assert len(web) == 1                                  # not fetched again


def test_a_moved_line_fetches_the_strip_again(project, geology, web, tmp_path):  # noqa: F811
    _strips(project, tmp_path, _profile())
    assert _strips(project, tmp_path, _profile(80.0))[0] == [("Sand", 0, 60), ("Loess", 60, 80)]
    assert len(web) == 2


def test_local_strips_are_not_remembered(project, geology, tmp_path):  # noqa: F811
    assert _strips(project, tmp_path, _profile())[0] == SAND_LOESS
    assert not list(tmp_path.glob("strip-*.json"))


def test_refresh_web_layers_fetches_again(project, geology, web, tmp_path):  # noqa: F811
    from groundwork_geophysics.section.context_layers import ContextGatherer
    _strips(project, tmp_path, _profile())
    g = ContextGatherer(project, AUTH, lambda: None, cache_dir=tmp_path)
    g.refresh_web_layers()
    g.close()
    assert not list(tmp_path.glob("strip-*.json"))
    _strips(project, tmp_path, _profile())
    assert len(web) == 2


def test_a_new_web_strip_comes_in_the_background(qgis_app, project, geology, web,  # noqa: F811
                                                 tmp_path):
    from qgis.PyQt.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    told = []

    def changed():
        told.append(1)
        loop.quit()
    first, g = _strips(project, tmp_path, _profile(), on_change=changed, background=True)
    try:
        assert first == []                                  # not waited for
        QTimer.singleShot(30000, loop.quit)
        loop.exec()
        assert told and len(web) == 1
        assert [(b.label, round(b.s0), round(b.s1))
                for b in g.items_for(_profile()).band] == SAND_LOESS
        assert len(web) == 1
    finally:
        g.close()


def test_the_profile_menu_refreshes_web_layers(qgis_app, store_with_model, make_dock):
    from groundwork_geophysics.section.dock import REFRESH_WEB_TEXT
    st, _p, _src = store_with_model
    dock = make_dock(st)
    menu = dock.profile_menu()
    assert REFRESH_WEB_TEXT not in [a.text() for a in menu.actions()]   # no web context
    asked = []
    dock.provider.refresh_web_layers = lambda: asked.append(1)
    menu = dock.profile_menu()
    [entry] = [a for a in menu.actions() if a.text() == REFRESH_WEB_TEXT]
    entry.trigger()
    assert asked == [1]
