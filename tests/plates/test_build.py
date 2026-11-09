"""Templates and the plate builder: fit to page, legends, mini-map, title block; updates keep
the user's own edits."""
import pytest

TEMPLATE_IDS = ("wb_section_area", "wb_minimap", "wb_north", "wb_map_scalebar",
                "wb_legend_interp", "wb_legend_boreholes", "wb_field_notes", "wb_title_project",
                "wb_title_client", "wb_title_job", "wb_title_plate", "wb_title_date",
                "wb_title_author", "wb_title_revision", "wb_crs")


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


def _plate(st, p, frames=1, template="A3_landscape", same_profile=True):
    from geophysics_workbench.core.plates import FrameLook, FrameSpec, ModelLook, PlateSpec
    ds = st.datasets(p.id)[0]
    look = FrameLook([ModelLook(ds.id, scale={"cmap": "viridis", "vmin": 10.0,
                                               "vmax": 1000.0, "log": True})])
    return PlateSpec("pl1", "3", "Transect", template,
                     [FrameSpec(f"f{i}", p.id, look) for i in range(frames)])


@pytest.mark.parametrize("template", ["A4_landscape", "A4_portrait", "A3_landscape",
                                      "A3_portrait"])
def test_create_from_each_template_has_all_ids(env, template):
    from geophysics_workbench.plates.build import create_or_update_plate
    st, p, prov, prj = env
    layout = create_or_update_plate(prj, st, prov, _plate(st, p, template=template))
    ids = {i.id() for i in layout.items() if hasattr(i, "id")}
    assert set(TEMPLATE_IDS) <= ids
    assert {"wb_frame_1", "wb_colourbar_1_1", "wb_provenance_1"} <= ids
    assert layout.name() == "Plate 3 – Transect"
    frame = layout.itemById("wb_frame_1")
    assert [s.profileSourceId() for s in frame.sources()] == ["geophysics_workbench:frame:f0"]


def test_two_frames_same_profile_share_scale_and_ve(env):
    from geophysics_workbench.plates.build import create_or_update_plate, frame_scale_and_ve
    st, p, prov, prj = env
    layout = create_or_update_plate(prj, st, prov, _plate(st, p, frames=2))
    a, b = layout.itemById("wb_frame_1"), layout.itemById("wb_frame_2")
    assert frame_scale_and_ve(a) == frame_scale_and_ve(b)
    assert a.plot().xMinimum() == b.plot().xMinimum()
    assert a.rect().width() == pytest.approx(b.rect().width())
    assert "VE" in layout.itemById("wb_provenance_1").text()
    bar = layout.itemById("wb_colourbar_1_1")             # a slim bar, not the whole column
    assert bar.rect().width() <= 30.0 + 1e-6


def test_update_keeps_user_edits(env):
    """Review Focus 4: moved legend, added label, changed colour-bar title font survive."""
    from qgis.core import QgsLayoutItemLabel, QgsLayoutPoint, QgsUnitTypes

    from geophysics_workbench.plates.build import create_or_update_plate
    st, p, prov, prj = env
    plate = _plate(st, p)
    layout = create_or_update_plate(prj, st, prov, plate)
    legend = layout.itemById("wb_legend_interp")
    legend.attemptMove(QgsLayoutPoint(33, 44, QgsUnitTypes.LayoutMillimeters))
    mine = QgsLayoutItemLabel(layout)
    mine.setId("my_note")
    mine.setText("saltwater intrusion?")
    layout.addLayoutItem(mine)
    bar = layout.itemById("wb_colourbar_1_1")
    fmt = bar.settings.textFormat()
    fmt.setSize(13.0)
    bar.settings.setTextFormat(fmt)
    bar.title = "My title"
    again = create_or_update_plate(prj, st, prov, plate)
    assert again is layout
    assert layout.itemById("wb_legend_interp").positionWithUnits().x() == pytest.approx(33)
    assert layout.itemById("my_note").text() == "saltwater intrusion?"
    bar = layout.itemById("wb_colourbar_1_1")
    assert bar.settings.textFormat().size() == 13.0 and bar.title == "My title"


def test_missing_profile_shows_placeholder_and_exports(env, tmp_path):
    """Review Focus 2."""
    from qgis.core import QgsLayoutExporter

    from geophysics_workbench.core.plates import FrameLook, FrameSpec, PlateSpec
    from geophysics_workbench.plates.build import create_or_update_plate
    st, p, prov, prj = env
    plate = PlateSpec("pl2", "4", "Gone", "A4_landscape",
                      [FrameSpec("fx", "no-such-profile", FrameLook())])
    layout = create_or_update_plate(prj, st, prov, plate)
    assert "not found" in layout.itemById("wb_placeholder_1").text()
    path = tmp_path / "gone.pdf"
    assert QgsLayoutExporter(layout).exportToPdf(
        str(path), QgsLayoutExporter.PdfExportSettings()) == QgsLayoutExporter.ExportResult.Success


def test_field_notes_list_excludes_hidden(env):
    from geophysics_workbench.core.field_notes import FieldNote
    from geophysics_workbench.plates.build import create_or_update_plate
    st, p, prov, prj = env
    st.save_field_note(FieldNote("a", p.id, 30.0, None, "fence"))
    st.save_field_note(FieldNote("b", p.id, 10.0, 20.0, "wet ground"))
    st.save_field_note(FieldNote("c", p.id, 5.0, None, "secret", shown=False))
    layout = create_or_update_plate(prj, st, prov, _plate(st, p))
    text = layout.itemById("wb_field_notes").text()
    assert text.index("wet ground") < text.index("fence") and "secret" not in text


def test_title_reads_project_variables(env):
    from qgis.core import QgsExpressionContextUtils

    from geophysics_workbench.plates.build import create_or_update_plate, set_plate_details
    st, p, prov, prj = env
    set_plate_details(prj, project="Gülpe", client="LfU", job="2026-041", author="SB",
                      date="2026-11-09", revision="A")
    assert QgsExpressionContextUtils.projectScope(prj).variable("wb_client") == "LfU"
    layout = create_or_update_plate(prj, st, prov, _plate(st, p))
    label = layout.itemById("wb_title_client")
    assert "@wb_client" in label.text() and label.currentText().endswith("LfU")
    assert layout.itemById("wb_title_plate").text() == "Plate 3 – Transect"


def test_colour_bars_survive_python_garbage_collection(env):
    """A colour bar made by the builder stays a colour bar once Python lets go of the layout
    (it was saved as a plain item, and lost, in the demo build)."""
    import gc

    from geophysics_workbench.plates.build import create_or_update_plate
    from geophysics_workbench.plates.items import COLOUR_BAR_TYPE, ColourBarItem
    st, p, prov, prj = env
    create_or_update_plate(prj, st, prov, _plate(st, p))
    gc.collect()
    layout = prj.layoutManager().layoutByName("Plate 3 – Transect")
    bar = layout.itemById("wb_colourbar_1_1")
    assert isinstance(bar, ColourBarItem) and bar.type() == COLOUR_BAR_TYPE
    assert bar.dataset_id == st.datasets(p.id)[0].id


def test_plate_items_survive_project_reload(env, tmp_path):
    import gc

    from geophysics_workbench.plates.build import create_or_update_plate
    from geophysics_workbench.plates.items import BoreholeLegendItem, ColourBarItem
    from geophysics_workbench.plates.sources import detach_frame_items
    st, p, prov, prj = env
    create_or_update_plate(prj, st, prov, _plate(st, p))
    path = tmp_path / "plates.qgz"
    assert prj.write(str(path))
    detach_frame_items(prj)
    prj.clear()
    assert prj.read(str(path))
    gc.collect()
    layout = prj.layoutManager().layoutByName("Plate 3 – Transect")
    bar = layout.itemById("wb_colourbar_1_1")
    assert isinstance(bar, ColourBarItem) and bar.dataset_id == st.datasets(p.id)[0].id
    assert isinstance(layout.itemById("wb_legend_boreholes"), BoreholeLegendItem)
