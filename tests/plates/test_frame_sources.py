"""Each plate frame draws its own stored look, also after the project is reopened."""
import numpy as np
import pytest


def _look(st, p, **model):
    from geophysics_workbench.core.plates import FrameLook, ModelLook
    ds = st.datasets(p.id)[0]
    return FrameLook([ModelLook(ds.id, **model)], None, True, True, False)


def test_snapshot_with_look_shows_only_chosen_models_and_scale(store_with_model, qgis_app):
    from geophysics_workbench.core.plates import FrameLook
    from geophysics_workbench.section.data import SectionDataProvider
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    look = _look(st, p, opacity=0.5, scale={"cmap": "viridis", "vmin": 10.0, "vmax": 100.0,
                                            "log": True}, mode="cells")
    snap = prov.snapshot(p.id, look=look)
    [layer] = snap.layers
    assert layer.style.opacity == 0.5 and layer.style.scale.cmap == "viridis"
    assert layer.style.scale.vmin == 10.0
    assert prov.snapshot(p.id, look=FrameLook([], None, True, True, False)).layers == []


def test_frame_look_independent_of_panel_restyle(store_with_model, qgis_app):
    from geophysics_workbench.core.colors import ColorScale
    from geophysics_workbench.section.data import LayerStyle, SectionDataProvider
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    ds_id = st.datasets(p.id)[0].id
    look = _look(st, p, scale={"cmap": "viridis", "vmin": 10.0, "vmax": 100.0, "log": True})
    prov.layers(p.id)
    prov.set_style(ds_id, LayerStyle(scale=ColorScale("gray", 1.0, 5.0, False), opacity=0.2))
    snap = prov.snapshot(p.id, look=look)
    assert snap.layers[0].style.scale.cmap == "viridis" and snap.layers[0].style.opacity == 1.0


def test_latest_or_chosen_interpretation_version(store_with_model, qgis_app):
    from dataclasses import replace

    from geophysics_workbench.core.interpretation import InterpFeature, InterpPiece, new_id
    from geophysics_workbench.section.data import SectionDataProvider
    st, p, _ = store_with_model
    st.ensure_interpretation()
    v = st.current_version()
    f = InterpFeature(new_id(), v.id, type="clay")
    st.save_feature(f)
    st.save_piece(InterpPiece(new_id(), v.id, f.id, p.id, "point", [(5.0, -1.0)]))
    prov = SectionDataProvider(st)
    look = _look(st, p)
    assert len(prov.snapshot(p.id, look=look).interpretation) == 1          # latest
    other = replace(look, interp_version="no-such-version")
    assert prov.snapshot(p.id, look=other).interpretation == []


def test_frame_drawing_is_clipped_to_the_plot_area(store_with_model, qgis_app):
    """Spike finding: the section must not spill past the frame."""
    from qgis.core import QgsDoubleRange, QgsProfileRenderContext, QgsRenderContext
    from qgis.PyQt.QtGui import QImage, QPainter, QTransform

    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.section.profile_source import WorkbenchProfileGenerator
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)

    class Owner:
        last_results = None

    gen = WorkbenchProfileGenerator(prov.snapshot(p.id, look=_look(st, p)), Owner())
    assert gen.generateProfile()
    res = gen.takeResults()
    img = QImage(400, 300, QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    painter = QPainter(img)
    rc = QgsRenderContext.fromQPainter(painter)
    ctx = QgsProfileRenderContext(rc)
    ctx.setDistanceRange(QgsDoubleRange(10.0, 30.0))     # a window inside the data
    zr = res.zRange()
    ctx.setElevationRange(QgsDoubleRange(zr.lower(), zr.upper()))
    tr = QTransform()                                    # 10..30 m -> x 100..300 px
    tr.translate(100 - 10 * 10.0, 0)
    tr.scale(10.0, -200.0 / (zr.upper() - zr.lower()))
    tr.translate(0, -zr.upper())
    ctx.setWorldTransform(tr)
    res.renderResults(ctx)
    painter.end()
    assert any(img.pixel(200, y) != 0xFFFFFFFF for y in range(300))          # inside: drawn
    assert all(img.pixel(x, y) == 0xFFFFFFFF for x in range(0, 95) for y in range(300))
    assert all(img.pixel(x, y) == 0xFFFFFFFF for x in range(306, 400) for y in range(300))


def test_reopened_project_frames_draw(store_with_model, qgis_app, tmp_path):
    """Review Focus 1: save, clear, read, re-attach: the frame item has its source again."""
    from qgis.core import QgsLayoutItemElevationProfile, QgsPrintLayout, QgsProject

    from geophysics_workbench.core.plates import FrameSpec, PlateSpec
    from geophysics_workbench.plates.sources import (attach_frame_sources, read_plates,
                                                     register_frame_sources,
                                                     unregister_frame_sources, write_plates)
    from geophysics_workbench.section.data import SectionDataProvider
    st, p, _ = store_with_model
    prov = SectionDataProvider(st)
    prj = QgsProject.instance()
    prj.clear()
    plates = [PlateSpec("pl1", "1", "P1", "A4_landscape",
                        [FrameSpec("f1", p.id, _look(st, p))])]
    write_plates(prj, plates)
    layout = QgsPrintLayout(prj)
    layout.initializeDefaults()
    layout.setName("Plate 1 – P1")
    item = QgsLayoutItemElevationProfile(layout)
    item.setId("wb_frame_1")
    item.setCustomProperty("wb_frame_id", "f1")
    layout.addLayoutItem(item)
    prj.layoutManager().addLayout(layout)
    sources = register_frame_sources(prov, read_plates(prj))
    attach_frame_sources(prj, st, sources)
    assert [s.profileSourceId() for s in item.sources()] == ["geophysics_workbench:frame:f1"]
    path = tmp_path / "plates.qgz"
    assert prj.write(str(path))
    prj.clear()
    unregister_frame_sources()
    assert prj.read(str(path))
    sources = register_frame_sources(prov, read_plates(prj))
    attach_frame_sources(prj, st, sources)
    again = prj.layoutManager().layoutByName("Plate 1 – P1").itemById("wb_frame_1")
    assert [s.profileSourceId() for s in again.sources()] == ["geophysics_workbench:frame:f1"]
    assert again.profileCurve() is not None and again.profileCurve().length() > 0
    for lay in prj.layoutManager().printLayouts():
        for it in lay.items():
            if isinstance(it, QgsLayoutItemElevationProfile):
                it.setSources([])
    unregister_frame_sources()
    prj.clear()
