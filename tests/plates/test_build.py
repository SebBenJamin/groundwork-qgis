"""Templates and the plate builder: fit to page, legends, mini-map, title block; updates keep
the user's own edits."""
import pytest

TEMPLATE_IDS = ("wb_section_area", "wb_minimap", "wb_north", "wb_map_scalebar",
                "wb_legend_interp", "wb_legend_boreholes", "wb_field_notes", "wb_stamp_area",
                "wb_stamp_project", "wb_stamp_client", "wb_stamp_job", "wb_stamp_plate",
                "wb_stamp_title", "wb_stamp_date", "wb_stamp_author", "wb_stamp_checked",
                "wb_stamp_revision", "wb_stamp_survey", "wb_stamp_logo")


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


def _plate(st, p, frames=1, template="A3_landscape", same_profile=True):
    from groundwork_geophysics.core.plates import FrameLook, FrameSpec, ModelLook, PlateSpec
    ds = st.datasets(p.id)[0]
    look = FrameLook([ModelLook(ds.id, scale={"cmap": "viridis", "vmin": 10.0,
                                               "vmax": 1000.0, "log": True})])
    return PlateSpec("pl1", "3", "Transect", template,
                     [FrameSpec(f"f{i}", p.id, look) for i in range(frames)])


@pytest.mark.parametrize("template", ["A4_landscape", "A4_portrait", "A3_landscape",
                                      "A3_portrait"])
def test_create_from_each_template_has_all_ids(env, template):
    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    layout = create_or_update_plate(prj, st, prov, _plate(st, p, template=template))
    ids = {i.id() for i in layout.items() if hasattr(i, "id")}
    assert set(TEMPLATE_IDS) <= ids
    assert {"wb_frame_1", "wb_colourbar_1_1", "wb_provenance_1"} <= ids
    assert layout.name() == "Plate 3 – Transect"
    frame = layout.itemById("wb_frame_1")
    assert [s.profileSourceId() for s in frame.sources()] == ["geophysics_workbench:frame:f0"]


def test_two_frames_same_profile_share_scale_and_ve(env):
    from groundwork_geophysics.plates.build import create_or_update_plate, frame_scale_and_ve
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

    from groundwork_geophysics.plates.build import create_or_update_plate
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

    from groundwork_geophysics.core.plates import FrameLook, FrameSpec, PlateSpec
    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    plate = PlateSpec("pl2", "4", "Gone", "A4_landscape",
                      [FrameSpec("fx", "no-such-profile", FrameLook())])
    layout = create_or_update_plate(prj, st, prov, plate)
    assert "not found" in layout.itemById("wb_placeholder_1").text()
    path = tmp_path / "gone.pdf"
    assert QgsLayoutExporter(layout).exportToPdf(
        str(path), QgsLayoutExporter.PdfExportSettings()) == QgsLayoutExporter.ExportResult.Success


def test_field_notes_list_excludes_hidden(env):
    from groundwork_geophysics.core.field_notes import FieldNote
    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    st.save_field_note(FieldNote("a", p.id, 30.0, None, "fence"))
    st.save_field_note(FieldNote("b", p.id, 10.0, 20.0, "wet ground"))
    st.save_field_note(FieldNote("c", p.id, 5.0, None, "secret", shown=False))
    layout = create_or_update_plate(prj, st, prov, _plate(st, p))
    text = layout.itemById("wb_field_notes").text()
    assert text.index("wet ground") < text.index("fence") and "secret" not in text


def test_title_reads_project_variables(env):
    from qgis.core import QgsExpressionContextUtils

    from groundwork_geophysics.plates.build import create_or_update_plate, set_plate_details
    st, p, prov, prj = env
    set_plate_details(prj, project="Gülpe", client="LfU", job="2026-041", author="SB",
                      date="2026-11-09", revision="A")
    assert QgsExpressionContextUtils.projectScope(prj).variable("wb_client") == "LfU"
    layout = create_or_update_plate(prj, st, prov, _plate(st, p))
    label = layout.itemById("wb_stamp_client")
    assert "@wb_client" in label.text() and label.currentText().endswith("LfU")
    assert layout.itemById("wb_stamp_plate").text() == "Plate 3"
    assert layout.itemById("wb_stamp_title").text() == "Transect"


def test_colour_bars_survive_python_garbage_collection(env):
    """A colour bar made by the builder stays a colour bar once Python lets go of the layout
    (it was saved as a plain item, and lost, in the demo build)."""
    import gc

    from groundwork_geophysics.plates.build import create_or_update_plate
    from groundwork_geophysics.plates.items import COLOUR_BAR_TYPE, ColourBarItem
    st, p, prov, prj = env
    create_or_update_plate(prj, st, prov, _plate(st, p))
    gc.collect()
    layout = prj.layoutManager().layoutByName("Plate 3 – Transect")
    bar = layout.itemById("wb_colourbar_1_1")
    assert isinstance(bar, ColourBarItem) and bar.type() == COLOUR_BAR_TYPE
    assert bar.dataset_id == st.datasets(p.id)[0].id


def test_plate_items_survive_project_reload(env, tmp_path):
    import gc

    from groundwork_geophysics.plates.build import create_or_update_plate
    from groundwork_geophysics.plates.items import BoreholeLegendItem, ColourBarItem
    from groundwork_geophysics.plates.sources import detach_frame_items
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


def test_colour_bars_follow_their_model_not_their_position(env):
    """Review I4: removing frame 1 must not hand frame 2's tuned bar to another model or
    reset it."""
    from groundwork_geophysics.plates.build import create_or_update_plate
    from groundwork_geophysics.plates.items import ColourBarItem
    st, p, prov, prj = env
    plate = _plate(st, p, frames=2)
    layout = create_or_update_plate(prj, st, prov, plate)
    second = next(i for i in layout.items() if isinstance(i, ColourBarItem)
                  and i.frame_id == "f1")
    second.title, second.ticks = "Tuned", "list:10,100"
    plate.frames.pop(0)
    create_or_update_plate(prj, st, prov, plate)
    bars = [i for i in layout.items() if isinstance(i, ColourBarItem)]
    assert [(b.frame_id, b.title, b.ticks) for b in bars] == [("f1", "Tuned", "list:10,100")]


def test_update_keeps_user_edits_to_minimap_provenance_and_legend(env):
    """Review I3: a panned mini-map, an edited provenance line and a legend the user
    changed survive Create; untouched ones are still refreshed."""
    from qgis.core import QgsRectangle

    from groundwork_geophysics.plates.build import create_or_update_plate
    from groundwork_geophysics.ui.project_actions import store_layers
    st, p, prov, prj = env
    plate = _plate(st, p)
    layout = create_or_update_plate(prj, st, prov, plate)
    m = layout.itemById("wb_minimap")
    mine = QgsRectangle(0, 0, 1000, 700)
    m.zoomToExtent(mine)
    panned = m.extent()
    prov_label = layout.itemById("wb_provenance_1")
    prov_label.setText("Our own wording")
    legend = layout.itemById("wb_legend_interp")
    legend.model().rootGroup().addLayer(store_layers(st, prj)["profiles"])
    plate.title = "Renamed"                                  # something else to refresh
    create_or_update_plate(prj, st, prov, plate)
    assert m.extent() == panned
    assert prov_label.text() == "Our own wording"
    assert [n.name() for n in legend.model().rootGroup().children()] == ["profiles"]
    assert layout.itemById("wb_stamp_title").text() == "Renamed"


def test_untouched_provenance_is_refreshed(env):
    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    plate = _plate(st, p)
    layout = create_or_update_plate(prj, st, prov, plate)
    plate.frames[0].scale = 1250
    create_or_update_plate(prj, st, prov, plate)
    assert "1:1250" in layout.itemById("wb_provenance_1").text()


def test_frame_leaves_room_for_labels_above_the_data(env):
    """Labels of notes, cores and crossings sit in rows above the ground; the plate keeps
    room for them (they were cut off at the top of the frame)."""
    from groundwork_geophysics.core.field_notes import FieldNote
    from groundwork_geophysics.plates.build import (create_or_update_plate, frame_scale_and_ve,
                                                   label_room_mm, snapshot_extent)
    st, p, prov, prj = env
    st.save_field_note(FieldNote("a", p.id, 1.0, 8.0, "wet ground"))
    st.save_field_note(FieldNote("b", p.id, 4.0, None, "fence"))
    plate = _plate(st, p)
    layout = create_or_update_plate(prj, st, prov, plate)
    snap = prov.snapshot(p.id, look=plate.frames[0].look)
    room = label_room_mm(snap)
    assert room > 10.0                                  # band/lanes + three label rows
    item = layout.itemById("wb_frame_1")
    scale, ve = frame_scale_and_ve(item)
    top = snapshot_extent(snap, p.chainage.length)[3]
    assert item.plot().yMaximum() - top >= room * scale / (1000.0 * ve) * 0.98


def test_local_frame_labels_its_vertical_axis_with_depths(env):
    from dataclasses import replace

    import numpy as np
    from qgis.core import QgsNumericFormatContext

    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    [s] = st.station_sets(p.id)
    [d] = st.datasets(p.id)
    st.save_station_set(replace(s, xyz=np.column_stack([s.xyz[:, :2], np.full(len(s.xyz),
                                                                              np.nan)])))
    st.save_dataset(replace(d, reader_options={"z_kind": "local"}))   # no heights at all
    assert prov.is_local(p.id)
    plate = _plate(st, p)
    layout = create_or_update_plate(prj, st, prov, plate)
    axis = layout.itemById("wb_frame_1").plot().yAxis()
    ctx = QgsNumericFormatContext()
    assert axis.numericFormat().formatDouble(-12.5, ctx) == "12.5"
    assert axis.labelSuffix() == " m"
    st.save_station_set(s)                                  # heights again: elevations
    layout = create_or_update_plate(prj, st, prov, plate)
    axis = layout.itemById("wb_frame_1").plot().yAxis()
    assert axis.numericFormat().id() == "basic"
    assert axis.numericFormat().formatDouble(-12.5, ctx) == "-12.5"


def _make_local(st, p):
    """No heights at all (the stations lose theirs, the model reads local heights); returns
    the station set as it was."""
    from dataclasses import replace

    import numpy as np
    [s] = st.station_sets(p.id)
    [d] = st.datasets(p.id)
    st.save_station_set(replace(s, xyz=np.column_stack([s.xyz[:, :2], np.full(len(s.xyz),
                                                                              np.nan)])))
    st.save_dataset(replace(d, reader_options={"z_kind": "local"}))
    return s


def test_user_tuned_basic_format_is_kept_on_a_local_frame(env):
    from qgis.core import QgsBasicNumericFormat, QgsNumericFormatContext

    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    plate = _plate(st, p)
    layout = create_or_update_plate(prj, st, prov, plate)
    tuned = QgsBasicNumericFormat()
    tuned.setNumberDecimalPlaces(2)
    tuned.setShowTrailingZeros(True)
    layout.itemById("wb_frame_1").plot().yAxis().setNumericFormat(tuned)
    stations = _make_local(st, p)
    assert prov.is_local(p.id)
    ctx = QgsNumericFormatContext()
    layout = create_or_update_plate(prj, st, prov, plate)
    axis = layout.itemById("wb_frame_1").plot().yAxis()
    assert axis.numericFormat().id() == "basic"
    assert axis.numericFormat().formatDouble(-12.5, ctx) == "-12.50"     # the user's
    st.save_station_set(stations)                           # heights again: still the user's
    layout = create_or_update_plate(prj, st, prov, plate)
    axis = layout.itemById("wb_frame_1").plot().yAxis()
    assert axis.numericFormat().formatDouble(-12.5, ctx) == "-12.50"


def test_plate_legend_skips_boreholes_of_a_local_frame(env):
    import numpy as np

    from groundwork_geophysics.core.context import (BoreholeView, ContextItems, Curve,
                                                   LogInterval, ProjectedPoint)
    from groundwork_geophysics.plates.build import create_or_update_plate
    st, p, prov, prj = env
    bh = ProjectedPoint(25.0, 0.0, "BH1", "borehole", None, [LogInterval(0.0, 3.0, "sand")],
                        entry=0, curves=[Curve("k:gr", "GR", "API", np.array([0.0, 3.0]),
                                               np.array([10.0, 20.0]))])
    prov.context_source = lambda profile: ContextItems(
        points=[bh], borehole_views={0: BoreholeView(curve_keys=("k:gr",))})
    layout = create_or_update_plate(prj, st, prov, _plate(st, p))
    legend = layout.itemById("wb_legend_boreholes")
    assert [label for label, _ in legend.rows()] == ["GR (API)"]
    _make_local(st, p)
    prov.notify_changed()
    assert prov.is_local(p.id)
    assert legend.rows() == []


def test_plate_headroom_counts_strips(env):
    from dataclasses import replace

    from groundwork_geophysics.core.context import BandSegment, ContextItems
    from groundwork_geophysics.plates.build import label_room_mm
    st, p, prov, prj = env
    snap = prov.snapshot(p.id)
    one = replace(snap, context=ContextItems(band=[BandSegment(0, 5, "a", strip=0)]))
    two = replace(snap, context=ContextItems(band=[BandSegment(0, 5, "a", strip=0),
                                                   BandSegment(0, 5, "b", strip=1)]))
    assert label_room_mm(two) - label_room_mm(one) == pytest.approx(3.6)


def test_plate_headroom_is_millimetres_not_screen_pixel_minimums(env):
    # the panel's layout keeps minimum sizes in screen pixels (a marker at least 3 px, a
    # station number at least 10 px); read at "1 px per mm" they became 3 and 10 mm, and
    # three short frames on a plate were left with no room for their sections at all
    from dataclasses import replace

    from groundwork_geophysics.core.context import BandSegment, ContextItems
    from groundwork_geophysics.plates.build import label_room_mm
    st, p, prov, prj = env
    snap = prov.snapshot(p.id)
    one = replace(snap, context=ContextItems(band=[BandSegment(0, 5, "a", strip=0)]))
    # marker 2 x 1 mm, station number 1.6 x 3 mm, gap 1.5 mm, strip 3 mm, 1 mm spacing
    assert label_room_mm(one) == pytest.approx(2 * 1.0 + 1.6 * 3.0 + 1.5 + 3.0 + 1.0, abs=0.2)
