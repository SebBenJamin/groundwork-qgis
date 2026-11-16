"""Round 2, F5: field notes in the section follow their QGIS layers' styles ("Field notes"
for notes at one chainage, "Field notes (stretches)" for stretches). The layers are added when
the store has notes; old layers get the workbench style once."""
import pytest
from qgis.PyQt.QtGui import QColor


@pytest.fixture
def project(qgis_app):
    from qgis.core import QgsProject
    prj = QgsProject.instance()
    prj.clear()
    yield prj
    prj.removeAllMapLayers()
    prj.clear()


def _notes(st, p):
    from groundwork_geophysics.core.field_notes import FieldNote
    from groundwork_geophysics.ui.field_notes_dialog import after_change
    st.save_field_note(FieldNote("a", p.id, 30.0, None, "fence", "obstacle"))
    st.save_field_note(FieldNote("b", p.id, 10.0, 20.0, "wet ground", "ground"))
    st.rebuild_field_note_geometry({q.id: q.chainage for q in st.profiles()})


def _colour(layer, rgb):
    sym = layer.renderer().symbol().clone()
    sym.setColor(QColor(*rgb))
    from qgis.core import QgsSingleSymbolRenderer
    layer.setRenderer(QgsSingleSymbolRenderer(sym))


def test_layers_added_when_notes_exist(store_with_model, project):
    from groundwork_geophysics.ui.field_note_layers import ensure_note_layers, field_note_layers
    st, p, _ = store_with_model
    _notes(st, p)
    assert field_note_layers(st, project) == {}
    ensure_note_layers(st, project)
    assert set(field_note_layers(st, project)) == {"field_notes_points", "field_notes_lines"}


def test_no_layers_without_notes(store_with_model, project):
    from groundwork_geophysics.ui.field_note_layers import ensure_note_layers, field_note_layers
    st, _p, _ = store_with_model
    ensure_note_layers(st, project)
    assert field_note_layers(st, project) == {}


def test_default_style_matches_today(store_with_model, project):
    from groundwork_geophysics.section.field_notes_render import NOTE_RGB, note_looks
    from groundwork_geophysics.ui.field_note_layers import ensure_note_layers
    st, p, _ = store_with_model
    _notes(st, p)
    ensure_note_layers(st, project)
    looks = note_looks(st, project)
    assert looks["a"].rgb == NOTE_RGB and looks["b"].rgb == NOTE_RGB
    assert looks["b"].width_mm == 0.5


def test_old_layers_migrated_once(store_with_model, project):
    from qgis.core import QgsSingleSymbolRenderer, QgsSymbol

    from groundwork_geophysics.section.field_notes_render import NOTE_RGB, note_looks
    from groundwork_geophysics.ui.field_note_layers import (NOTE_STYLE_PROPERTY,
                                                           add_field_note_layers,
                                                           migrate_note_styles)
    st, p, _ = store_with_model
    _notes(st, p)
    layers = add_field_note_layers(st, project)
    for layer in layers.values():                    # as 0.7 left them: QGIS's random style
        layer.removeCustomProperty(NOTE_STYLE_PROPERTY)
        sym = QgsSymbol.defaultSymbol(layer.geometryType())
        sym.setColor(QColor(10, 200, 10))
        layer.setRenderer(QgsSingleSymbolRenderer(sym))
    migrate_note_styles(st, project)
    assert note_looks(st, project)["b"].rgb == NOTE_RGB
    _colour(layers["field_notes_lines"], (0, 0, 255))   # the user restyles
    migrate_note_styles(st, project)
    assert note_looks(st, project)["b"].rgb == (0, 0, 255)


def test_categorized_per_note(store_with_model, project):
    from qgis.core import QgsCategorizedSymbolRenderer, QgsRendererCategory, QgsSymbol

    from groundwork_geophysics.section.field_notes_render import note_looks
    from groundwork_geophysics.ui.field_note_layers import ensure_note_layers, field_note_layers
    from groundwork_geophysics.core.field_notes import FieldNote
    st, p, _ = store_with_model
    _notes(st, p)
    st.save_field_note(FieldNote("c", p.id, 40.0, None, "gate", "access"))
    st.rebuild_field_note_geometry({q.id: q.chainage for q in st.profiles()})
    ensure_note_layers(st, project)
    layer = field_note_layers(st, project)["field_notes_points"]
    cats = []
    for value, rgb in (("obstacle", (255, 0, 0)), ("access", (0, 0, 255))):
        sym = QgsSymbol.defaultSymbol(layer.geometryType())
        sym.setColor(QColor(*rgb))
        cats.append(QgsRendererCategory(value, sym, value))
    layer.setRenderer(QgsCategorizedSymbolRenderer("category", cats))
    looks = note_looks(st, project)
    assert looks["a"].rgb == (255, 0, 0) and looks["c"].rgb == (0, 0, 255)


def test_plugin_adds_layers_and_reads_looks(store_with_model, project, fake_iface):
    from qgis.PyQt.QtCore import QCoreApplication, QEvent

    from groundwork_geophysics import classFactory
    from groundwork_geophysics.ui.field_note_layers import field_note_layers
    st, p, _ = store_with_model
    _notes(st, p)
    plug = classFactory(fake_iface)
    plug.initGui()
    try:
        plug.set_store(st)
        layers = field_note_layers(st, project)
        assert set(layers) == {"field_notes_points", "field_notes_lines"}
        _colour(layers["field_notes_lines"], (0, 0, 255))
        assert plug.provider.context(p.id).note_looks["b"].rgb == (0, 0, 255)
    finally:
        plug.unload()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete.value)


def test_note_tool_preview_in_layer_colour(store_with_model, project):
    from groundwork_geophysics.ui.field_note_layers import ensure_note_layers, stretch_rgb
    st, p, _ = store_with_model
    _notes(st, p)
    layers = ensure_note_layers(st, project)
    _colour(layers["field_notes_lines"], (0, 0, 255))
    assert stretch_rgb(st, project) == (0, 0, 255)
