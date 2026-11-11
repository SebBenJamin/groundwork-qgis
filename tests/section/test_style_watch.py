"""Round 2, B5: a style change of the workbench's own QGIS layers (interpretation, field
notes) redraws the section at once, not only after the profile is reopened."""
import numpy as np
import pytest


@pytest.fixture
def interp_store(tmp_path):
    from geophysics_workbench.core.chainage import Chainage
    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id
    from geophysics_workbench.store.gpkg_store import ProjectStore
    st = ProjectStore.create(tmp_path / "wb.gpkg", "EPSG:25832")
    st.ensure_interpretation()
    v = st.current_version()
    f = InterpFeature(new_id(), v.id, type="anomaly")
    st.save_feature(f)
    st.save_piece(InterpPiece(new_id(), v.id, f.id, "prof", "polygon",
                              [(40, 0), (60, 0), (60, -5), (40, -5)]))
    st.rebuild_derived(v.id, {"prof": Chainage(np.array([[0.0, 0.0], [50.0, 0.0]]))})
    return st


def _wait(qgis_app, ms=450):
    import time
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        qgis_app.processEvents()
        time.sleep(0.01)


def _restyle(layer, rgb="0,0,255"):
    from qgis.core import QgsSingleSymbolRenderer, QgsSymbol
    sym = QgsSymbol.defaultSymbol(layer.geometryType())
    sym.setColor(__import__("qgis.PyQt.QtGui", fromlist=["QColor"]).QColor(
        *(int(v) for v in rgb.split(","))))
    layer.setRenderer(QgsSingleSymbolRenderer(sym))


@pytest.fixture
def project(qgis_app):
    from qgis.core import QgsProject
    prj = QgsProject.instance()
    prj.clear()
    yield prj
    prj.removeAllMapLayers()
    prj.clear()


def _watch(store, project, calls):
    from geophysics_workbench.section.style_watch import StyleWatch
    from geophysics_workbench.ui.field_note_layers import field_note_layers
    from geophysics_workbench.ui.interp_layers import interp_layers
    return StyleWatch(project, lambda: [*interp_layers(store, project).values(),
                                        *field_note_layers(store, project).values()],
                      lambda: calls.append(1))


def test_renderer_change_redraws(qgis_app, interp_store, project):
    from geophysics_workbench.ui.interp_layers import add_interp_layers
    layers = add_interp_layers(interp_store, project)
    calls = []
    watch = _watch(interp_store, project, calls)
    _restyle(layers["interp_polygons_3d"])
    _wait(qgis_app)
    assert calls == [1]                          # debounced: one redraw
    watch.unload()


def test_layer_added_later_is_watched(qgis_app, interp_store, project):
    from geophysics_workbench.ui.field_note_layers import add_field_note_layers
    calls = []
    watch = _watch(interp_store, project, calls)
    layers = add_field_note_layers(interp_store, project)
    _wait(qgis_app)
    calls.clear()
    _restyle(layers["field_notes_lines"])
    _wait(qgis_app)
    assert calls == [1]
    watch.unload()


def test_unload_disconnects(qgis_app, interp_store, project):
    from geophysics_workbench.ui.interp_layers import add_interp_layers
    layers = add_interp_layers(interp_store, project)
    calls = []
    watch = _watch(interp_store, project, calls)
    watch.unload()
    _restyle(layers["interp_polygons_3d"])
    _wait(qgis_app)
    assert calls == []


def test_plugin_redraws_on_interp_style(qgis_app, fake_iface, interp_store, project):
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from geophysics_workbench import classFactory
    from geophysics_workbench.ui.interp_layers import add_interp_layers
    plug = classFactory(fake_iface)
    plug.initGui()
    try:
        layers = add_interp_layers(interp_store, project)
        plug.set_store(interp_store)
        calls = []
        plug.provider.on_change.append(lambda: calls.append(1))
        _restyle(layers["interp_polygons_3d"])
        _wait(qgis_app)
        assert calls
    finally:
        plug.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)
