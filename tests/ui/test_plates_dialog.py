"""The Plates… dialog: frames with their own look, plate details, create/update."""
import pytest


@pytest.fixture
def env(qgis_app, store_with_model):
    from qgis.core import QgsProject

    from geophysics_workbench.core.context import ContextItems
    from geophysics_workbench.plates.items import register_items, set_context_provider
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.ui.project_actions import use_store
    st, p, _ = store_with_model
    prj = QgsProject.instance()
    prj.clear()
    use_store(st, prj)
    prov = SectionDataProvider(st)
    prov.context_source = lambda profile: ContextItems()
    register_items()
    set_context_provider(prov)
    yield st, p, prov, prj
    from geophysics_workbench.plates.sources import detach_frame_items, unregister_frame_sources
    detach_frame_items(prj)
    unregister_frame_sources()
    set_context_provider(None)
    prj.removeAllMapLayers()
    prj.clear()


def _dialog(st, prov, prj, panel_profile=None):
    from geophysics_workbench.ui.plates_dialog import PlatesDialog
    return PlatesDialog(prj, st, prov, panel_profile=lambda: panel_profile)


def test_take_from_panel_copies_current_look(env):
    from dataclasses import replace

    from geophysics_workbench.core.colors import ColorScale
    st, p, prov, prj = env
    ds = st.datasets(p.id)[0]
    prov.set_style(ds.id, replace(prov.style(ds.id), opacity=0.6, mode="smooth",
                                  scale=ColorScale("viridis", 5.0, 500.0, True)))
    prov.show_field_notes = False
    dlg = _dialog(st, prov, prj, panel_profile=p.id)
    dlg.add_plate()
    dlg.add_frame()
    dlg.take_from_panel(0)
    frame = dlg.current_plate().frames[0]
    assert frame.profile_id == p.id
    model = frame.look.models[0]
    assert (model.dataset_id, model.opacity, model.mode) == (ds.id, 0.6, "smooth")
    assert model.scale == {"cmap": "viridis", "vmin": 5.0, "vmax": 500.0, "log": True,
                           "ramp": "", "lut": None}
    assert frame.look.field_notes is False
    # restyling the panel afterwards leaves the plate's look alone
    prov.set_style(ds.id, replace(prov.style(ds.id), opacity=1.0))
    assert dlg.current_plate().frames[0].look.models[0].opacity == 0.6
    assert "smooth" in dlg.frames.item(0, 1).text()


def test_create_writes_specs_and_layouts(env):
    from geophysics_workbench.plates.sources import read_plates
    st, p, prov, prj = env
    dlg = _dialog(st, prov, prj, panel_profile=p.id)
    dlg.add_plate()
    dlg.number.setText("7")
    dlg.title.setText("Line A")
    dlg.number.editingFinished.emit()
    dlg.title.editingFinished.emit()
    dlg.template.setCurrentIndex(dlg.template.findData("A4_portrait"))
    dlg.add_frame()
    dlg.take_from_panel(0)
    dlg.create_plates()
    plates = read_plates(prj)
    assert [(pl.number, pl.title, pl.template) for pl in plates] == [("7", "Line A",
                                                                      "A4_portrait")]
    layout = prj.layoutManager().layoutByName("Plate 7 – Line A")
    assert layout is not None and layout.itemById("wb_frame_1") is not None
    dlg.create_plates()                                       # again: updated, not duplicated
    assert len(prj.layoutManager().printLayouts()) == 1
    again = _dialog(st, prov, prj)                            # reopened: the plates are there
    assert again.plate_list.count() == 1 and again.current_plate().title == "Line A"


def test_plate_details_set_project_variables(env):
    import datetime

    from qgis.core import QgsExpressionContextUtils

    from geophysics_workbench.ui.plates_dialog import PlateDetailsDialog
    st, p, prov, prj = env
    dlg = PlateDetailsDialog(prj)
    assert dlg.fields["date"].text() == datetime.date.today().isoformat()
    dlg.fields["client"].setText("LfU Brandenburg")
    dlg.fields["job"].setText("2026-041")
    dlg.accept()
    scope = QgsExpressionContextUtils.projectScope(prj)
    assert scope.variable("wb_client") == "LfU Brandenburg"
    assert scope.variable("wb_job") == "2026-041"
    reopened = PlateDetailsDialog(prj)
    assert reopened.fields["client"].text() == "LfU Brandenburg"


def test_frame_cells_read_like_a_user_types_them():
    """Usability review 2: "1.000" (German) became scale 1:1; "1:250" was refused."""
    from geophysics_workbench.ui.plates_dialog import parse_cell
    assert parse_cell("scale", "1.000") == 1000
    assert parse_cell("scale", "1:2500") == 2500 and parse_cell("scale", "1:1.000") == 1000
    assert parse_cell("ve", "1,5") == 1.5 and parse_cell("s_from", "12,5") == 12.5
    assert parse_cell("scale", "") is None
    for attr, text in (("ve", "inf"), ("ve", "nan"), ("ve", "0"), ("scale", "1:0"),
                       ("scale", "abc"), ("s_to", "x")):
        with pytest.raises(ValueError):
            parse_cell(attr, text)


def test_valid_cell_clears_the_message(env):
    st, p, prov, prj = env
    dlg = _dialog(st, prov, prj, panel_profile=p.id)
    dlg.add_plate()
    dlg.frames.item(0, 4).setText("abc")
    assert "not a usable number" in dlg.message.text()
    dlg.frames.item(0, 4).setText("1:2500")
    assert dlg.current_plate().frames[0].scale == 2500 and dlg.message.text() == ""
