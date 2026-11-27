"""The Plates… dialog: frames with their own look, plate details, create/update."""
import pytest


@pytest.fixture
def env(qgis_app, store_with_model):
    from qgis.core import QgsProject

    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.plates.items import register_items, set_context_provider
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.ui.project_actions import use_store
    st, p, _ = store_with_model
    prj = QgsProject.instance()
    prj.clear()
    use_store(st, prj)
    prov = SectionDataProvider(st)
    prov.context_source = lambda profile: ContextItems()
    register_items()
    set_context_provider(prov)
    yield st, p, prov, prj
    from groundwork_geophysics.plates.sources import detach_frame_items, unregister_frame_sources
    detach_frame_items(prj)
    unregister_frame_sources()
    set_context_provider(None)
    prj.removeAllMapLayers()
    prj.clear()


def _dialog(st, prov, prj, panel_profile=None):
    from groundwork_geophysics.ui.plates_dialog import PlatesDialog
    return PlatesDialog(prj, st, prov, panel_profile=lambda: panel_profile)


def test_take_from_panel_copies_current_look(env):
    from dataclasses import replace

    from groundwork_geophysics.core.colors import ColorScale
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
    from groundwork_geophysics.plates.sources import read_plates
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


def _page_mm(layout):
    size = layout.pageCollection().page(0).pageSize()
    return round(size.width()), round(size.height())


def test_new_template_for_an_existing_plate_remakes_its_layout(env):
    """The template used to apply only when the layout was first made: a plate switched to
    portrait stayed landscape without a word. Now the dialog asks and makes it again."""
    st, p, prov, prj = env
    dlg = _dialog(st, prov, prj, panel_profile=p.id)
    dlg.add_plate()
    dlg.template.setCurrentIndex(dlg.template.findData("A3_landscape"))
    dlg.add_frame()
    dlg.create_plates()
    [layout] = prj.layoutManager().printLayouts()
    assert _page_mm(layout) == (420, 297)
    asked = []
    dlg.confirm_remake = lambda plate: asked.append(plate.title) or True
    dlg.template.setCurrentIndex(dlg.template.findData("A3_portrait"))
    assert len(asked) == 1
    [layout] = prj.layoutManager().printLayouts()
    assert _page_mm(layout) == (297, 420)
    assert layout.itemById("wb_frame_1") is not None
    assert dlg.current_plate().template == "A3_portrait"


def test_declined_template_change_keeps_layout_and_setting(env):
    st, p, prov, prj = env
    dlg = _dialog(st, prov, prj, panel_profile=p.id)
    dlg.add_plate()
    dlg.template.setCurrentIndex(dlg.template.findData("A3_landscape"))
    dlg.add_frame()
    dlg.create_plates()
    dlg.confirm_remake = lambda plate: False
    dlg.template.setCurrentIndex(dlg.template.findData("A3_portrait"))
    [layout] = prj.layoutManager().printLayouts()
    assert _page_mm(layout) == (420, 297)
    assert dlg.current_plate().template == "A3_landscape"
    assert dlg.template.currentData() == "A3_landscape"


def test_plate_details_checked_and_logo(env, tmp_path):
    from qgis.core import QgsExpressionContextUtils

    from groundwork_geophysics.plates.build import plate_logo
    from groundwork_geophysics.ui.plates_dialog import PlateDetailsDialog
    st, p, prov, prj = env
    prj.setFileName(str(tmp_path / "p.qgz"))
    dlg = PlateDetailsDialog(prj)
    assert "checked" in dlg.fields
    dlg.fields["checked"].setText("KM")
    assert dlg.logo.isReadOnly()
    dlg.logo.setText(str(tmp_path / "logo.png"))
    dlg.accept()
    assert QgsExpressionContextUtils.projectScope(prj).variable("wb_checked") == "KM"
    assert plate_logo(prj) == "logo.png"
    again = PlateDetailsDialog(prj)
    assert again.logo.text() == "logo.png"
    again.logo_clear.click()
    again.accept()
    assert plate_logo(prj) == ""


def test_plate_details_set_project_variables(env):
    import datetime

    from qgis.core import QgsExpressionContextUtils

    from groundwork_geophysics.ui.plates_dialog import PlateDetailsDialog
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


def test_the_look_of_a_section_is_named_like_its_layer_row(qgis_app):
    from groundwork_geophysics.core.plates import FrameLook, ModelLook
    from groundwork_geophysics.ui.plates_dialog import look_summary
    look = FrameLook([ModelLook("s1", gain={"agc_window": 0.2}), ModelLook("m1", mode="smooth"),
                      ModelLook("s2", clip_percent=95.0)], boreholes=False, field_notes=False,
                     context=False)
    text = look_summary(look, {"s1": "VD-P760057", "m1": "ERT", "s2": "VD-P760068"},
                        traces={"s1", "s2"})
    assert text.startswith("VD-P760057 (clip 98 % · AGC) · ERT (smooth) · VD-P760068 (clip 95 %)")
    assert "(cells)" not in text


def test_frame_cells_read_like_a_user_types_them():
    """Usability review 2: "1.000" (German) became scale 1:1; "1:250" was refused."""
    from groundwork_geophysics.ui.plates_dialog import parse_cell
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
