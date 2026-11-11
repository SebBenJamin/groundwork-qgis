"""Round 2, B3: placing a field note sometimes made the workbench profile lines disappear
from the QGIS map. The profiles layer must stay valid, keep its features and draw after a
note is saved - the first note too (it creates the note tables under the loaded layers)."""
import pytest


def _render(layer):
    from qgis.core import QgsMapRendererSequentialJob, QgsMapSettings
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor
    ms = QgsMapSettings()
    ms.setLayers([layer])
    ms.setDestinationCrs(layer.crs())
    ext = layer.extent()
    ext.grow(max(ext.width(), ext.height(), 10.0) * 0.1)
    ms.setExtent(ext)
    ms.setOutputSize(QSize(200, 200))
    ms.setBackgroundColor(QColor(255, 255, 255))
    job = QgsMapRendererSequentialJob(ms)
    job.start()
    job.waitForFinished()
    img = job.renderedImage()
    drawn = sum(1 for x in range(0, 200, 2) for y in range(0, 200, 2)
                if img.pixelColor(x, y) != QColor(255, 255, 255))
    return drawn, job.errors()


@pytest.fixture
def setup(qgis_app, store_with_model):
    from qgis.core import QgsProject

    from geophysics_workbench.ui.project_actions import add_store_layers
    store, profile, _ = store_with_model
    prj = QgsProject.instance()
    prj.clear()
    layers = add_store_layers(store, prj)
    yield store, profile, layers["profiles"], prj
    prj.removeAllMapLayers()
    prj.clear()


def _place_note(store, profile, prj, text):
    from geophysics_workbench.core.field_notes import FieldNote
    from geophysics_workbench.core.interpretation import new_id
    from geophysics_workbench.ui.field_notes_dialog import after_change, save_note
    save_note(store, FieldNote(new_id(), profile.id, 10.0, None, text))
    after_change(store, None, prj)


def test_profiles_drawn_after_first_note(qgis_app, setup):
    store, profile, layer, prj = setup
    count = layer.featureCount()
    before, _ = _render(layer)
    assert before > 0
    _place_note(store, profile, prj, "first")
    assert layer.isValid() and layer.featureCount() == count
    after, errors = _render(layer)
    assert after == before, errors


def test_profiles_drawn_after_later_notes(qgis_app, setup):
    store, profile, layer, prj = setup
    _place_note(store, profile, prj, "first")
    before, _ = _render(layer)
    for i in range(3):
        _place_note(store, profile, prj, f"note {i}")
        assert layer.isValid()
        after, errors = _render(layer)
        assert after == before, errors


def _render_parallel_during(layer, action):
    """Render in QGIS's worker threads (as the map canvas does) while ``action`` runs."""
    from qgis.core import QgsMapRendererParallelJob, QgsMapSettings
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor
    ms = QgsMapSettings()
    ms.setLayers([layer])
    ms.setDestinationCrs(layer.crs())
    ext = layer.extent()
    ext.grow(max(ext.width(), ext.height(), 10.0) * 0.1)
    ms.setExtent(ext)
    ms.setOutputSize(QSize(200, 200))
    ms.setBackgroundColor(QColor(255, 255, 255))
    job = QgsMapRendererParallelJob(ms)
    job.start()
    action()
    job.waitForFinished()
    img = job.renderedImage()
    drawn = sum(1 for x in range(0, 200, 2) for y in range(0, 200, 2)
                if img.pixelColor(x, y) != QColor(255, 255, 255))
    return drawn, [e.message for e in job.errors()]


def test_profiles_drawn_while_note_saved(qgis_app, setup):
    store, profile, layer, prj = setup
    _place_note(store, profile, prj, "first")
    before, _ = _render(layer)
    results = [_render_parallel_during(layer, lambda i=i: _place_note(store, profile, prj,
                                                                       f"n{i}"))
               for i in range(10)]
    assert all(r[0] == before for r in results), results


def test_note_repaints_every_workbench_layer(qgis_app, setup):
    """Not reproducible offscreen: after a note, every layer from the workbench file is
    repainted, so a draw that QGIS lost while the file was written is redone."""
    store, profile, layer, prj = setup
    _place_note(store, profile, prj, "first")
    painted = []
    layer.repaintRequested.connect(lambda *a: painted.append(1))
    _place_note(store, profile, prj, "second")
    assert painted


def test_saving_a_note_opens_the_file_for_writing_once(qgis_app, setup):
    """``save_field_note`` opened the file for writing twice per note (``ensure_field_notes``
    always opened it for writing, even when the tables exist)."""
    store, profile, layer, prj = setup
    _place_note(store, profile, prj, "first")
    writes = []
    real = store._ds

    def spy(write=False):
        writes.append(write)
        return real(write)

    store._ds = spy
    from geophysics_workbench.core.field_notes import FieldNote
    from geophysics_workbench.core.interpretation import new_id
    store.save_field_note(FieldNote(new_id(), profile.id, 12.0, None, "again"))
    assert writes.count(True) <= 1
