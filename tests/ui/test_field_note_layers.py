"""The "Field notes" map layers in the workbench group (the plugin's own data)."""
import numpy as np
import pytest

from geophysics_workbench.core.chainage import Chainage
from geophysics_workbench.core.field_notes import FieldNote

BENT = Chainage(np.array([[0.0, 0.0], [50.0, 0.0], [50.0, 50.0]]))


@pytest.fixture
def store(tmp_path):
    from geophysics_workbench.store.gpkg_store import ProjectStore
    st = ProjectStore.create(tmp_path / "wb.gpkg", "EPSG:25832")
    st.ensure_field_notes()
    st.save_field_note(FieldNote("a", "prof", 10.0, None, "fence"))
    st.save_field_note(FieldNote("b", "prof", 20.0, 30.0, "wet"))
    st.save_field_note(FieldNote("c", "prof", 35.0, None, "hidden one", shown=False))
    st.rebuild_field_note_geometry({"prof": BENT})
    return st


def test_layers_added_once_read_only_and_hidden_notes_left_out(qgis_app, store):
    from qgis.core import QgsProject

    from geophysics_workbench.ui.field_note_layers import add_field_note_layers
    prj = QgsProject()
    a = add_field_note_layers(store, prj)
    b = add_field_note_layers(store, prj)
    assert set(a) == set(b) == {"field_notes_points", "field_notes_lines"}
    assert len(prj.mapLayers()) == 2
    pts = a["field_notes_points"]
    assert pts.readOnly() and sorted(f["note_id"] for f in pts.getFeatures()) == ["a", "b"]
    assert pts.labelsEnabled()
    assert [f["note_id"] for f in a["field_notes_lines"].getFeatures()] == ["b"]
    prj.clear()
