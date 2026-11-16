"""Usability round 1, Task 5: the section gets the room; measured data does not cover a model
by default."""


def test_measured_starts_hidden_when_model_exists():
    from groundwork_geophysics.section.data import starts_hidden

    class D:
        def __init__(self, kind):
            self.kind = kind
    model, measured, misfit = D("ert_model"), D("ert_measured"), D("ert_misfit")
    assert starts_hidden(measured, [model, measured])
    assert not starts_hidden(measured, [measured])               # alone: shown
    assert not starts_hidden(model, [model, measured])
    assert not starts_hidden(misfit, [model, misfit])            # a misfit is asked for


def test_layer_list_default_width_at_most_300px(qgis_app, store_with_model, make_dock):
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.resize(1366, 330)
    dock.show()
    dock.open_profile(p.id)
    qgis_app.processEvents()
    assert dock.layer_list.width() <= 300


def test_splitter_width_is_remembered(qgis_app, store_with_model, make_dock):
    from qgis.core import QgsSettings

    from groundwork_geophysics.section.dock import SPLITTER_KEY
    st, p, _ = store_with_model
    dock = make_dock(st)
    dock.resize(1366, 330)
    dock.show()
    qgis_app.processEvents()
    dock.splitter.setSizes([900, 400])
    dock.splitter.splitterMoved.emit(900, 1)
    assert QgsSettings().value(SPLITTER_KEY) is not None
    QgsSettings().remove(SPLITTER_KEY)
