"""New plates carry the stamp; old plates keep their title block; A4 makes room for it."""
from pathlib import Path

import pytest

TEMPLATES = ("A4_landscape", "A4_portrait", "A3_landscape", "A3_portrait")
OLD_TEMPLATE = Path(__file__).parent / "data" / "A4_landscape_0.10.qpt"


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


def _plate(st, p, template="A3_landscape"):
    from groundwork_geophysics.core.plates import FrameLook, FrameSpec, ModelLook, PlateSpec
    ds = st.datasets(p.id)[0]
    look = FrameLook([ModelLook(ds.id, scale={"cmap": "viridis", "vmin": 10.0,
                                               "vmax": 1000.0, "log": True})])
    return PlateSpec("pl1", "3", "Transect", template, [FrameSpec("f0", p.id, look)])


def _build(env, template="A3_landscape"):
    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    return create_or_update_plate(prj, st, prov, _plate(st, p, template))


def _ids(layout, prefix):
    return {i.id() for i in layout.items() if hasattr(i, "id") and i.id().startswith(prefix)}


@pytest.mark.parametrize("template", TEMPLATES)
def test_new_plate_has_stamp_on_every_template(env, template):
    from groundwork_geophysics.plates.stamp import CELLS
    layout = _build(env, template)
    for cell in CELLS:
        key = "wb_stamp_logo" if cell.key == "logo" else f"wb_stamp_{cell.key}"
        assert layout.itemById(key) is not None, (template, key)
    assert layout.itemById("wb_stamp_plate").text() == "Plate 3"
    assert layout.itemById("wb_stamp_title").text() == "Transect"
    assert not _ids(layout, "wb_title_") and layout.itemById("wb_crs") is None


def test_stamp_reads_project_variables(env):
    from groundwork_geophysics.plates.build import set_plate_details
    set_plate_details(env[3], project="Gülpe", client="LfU", checked="KM")
    layout = _build(env)
    checked = layout.itemById("wb_stamp_checked")
    assert "@wb_checked" in checked.text() and checked.currentText().endswith("KM")
    assert layout.itemById("wb_stamp_client").currentText().endswith("LfU")


def test_stamp_survey_from_dataset_info(env):
    from groundwork_geophysics.core.dataset_info import with_info
    st, p, prov, prj = env
    st.save_dataset(with_info(st.datasets(p.id)[0], {"method": "ERT", "array": "Wenner",
                                                     "date": "2024-06-12"}))
    layout = _build(env)
    survey = layout.itemById("wb_stamp_survey").text()
    assert "Acquired 2024-06-12" in survey and "Scale 1:" in survey
    assert layout.itemById("wb_stamp_method").text() == "ERT · Wenner"
    assert layout.itemById("wb_stamp_profile").text() == p.name


def test_stamp_edit_survives_update(env):
    layout = _build(env)
    layout.itemById("wb_stamp_client").setText("Auftraggeber: LfU")
    layout = _build(env)
    assert layout.itemById("wb_stamp_client").text() == "Auftraggeber: LfU"


def test_deleted_stamp_cell_stays_deleted(env):
    layout = _build(env)
    method = layout.itemById("wb_stamp_method")
    assert method is not None
    layout.removeLayoutItem(method)
    layout = _build(env)
    assert layout.itemById("wb_stamp_method") is None
    assert layout.itemById("wb_stamp_plate").text() == "Plate 3"


def test_old_template_plate_keeps_title_block(env):
    from groundwork_geophysics.plates.build import set_plate_details
    set_plate_details(env[3], client="LfU")
    layout = _build(env, str(OLD_TEMPLATE))
    assert not _ids(layout, "wb_stamp_")
    client = layout.itemById("wb_title_client")
    assert client is not None and client.currentText().endswith("LfU")
    assert layout.itemById("wb_title_plate").text() == "Plate 3 – Transect"


@pytest.mark.parametrize("template", ("A4_landscape", "A4_portrait"))
def test_a4_items_do_not_overlap(env, template):
    from groundwork_geophysics.plates.stamp import item_rect
    layout = _build(env, template)
    ids = ("wb_stamp_area", "wb_legend_interp", "wb_legend_boreholes", "wb_field_notes",
           "wb_minimap", "wb_section_area")
    rects = {i: item_rect(layout.itemById(i)) for i in ids}
    for n, a in enumerate(ids):
        for b in ids[n + 1:]:
            ra, rb = rects[a], rects[b]
            w = min(ra[0] + ra[2], rb[0] + rb[2]) - max(ra[0], rb[0])
            h = min(ra[1] + ra[3], rb[1] + rb[3]) - max(ra[1], rb[1])
            assert w <= 0.01 or h <= 0.01, (a, b)


@pytest.mark.parametrize("template", TEMPLATES)
def test_stamp_area_has_room(env, template):
    from groundwork_geophysics.plates.stamp import item_rect
    _, _, w, h = item_rect(_build(env, template).itemById("wb_stamp_area"))
    assert w >= 60 and h >= 60, (w, h)
