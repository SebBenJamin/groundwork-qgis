"""Section styles kept in the project, and one model's style applied to every model of the
same method."""
from dataclasses import replace

import numpy as np
import pytest


def _three_lines(st, p, src):
    """``st`` with a second ERT model on P2, a refraction model on P3 and an ERT model in
    another unit on P4 (all from the same file). Returns the dataset ids."""
    from groundwork_geophysics.core.model import (Dataset, file_fingerprint,
                                                  profile_from_stations)
    ids = {}
    for name, kind, quantity, unit in (("P2", "ert_model", "resistivity", "ohm.m"),
                                       ("P3", "srt_model", "velocity", "m/s"),
                                       ("P4", "ert_model", "resistivity", "kohm.m")):
        q, s = profile_from_stations(name, "EPSG:25832",
                                     np.array([[0, 10, 100], [50, 10, 102.0]]))
        st.save_profile(q)
        st.save_station_set(s)
        mt, sha = file_fingerprint(src)
        d = Dataset(f"d{name}", q.id, s.id, kind, str(src), mt, sha, "r2_res_dat",
                    {"z_kind": "elevation"}, {}, name=f"{name} model", quantity=quantity,
                    unit=unit)
        st.save_dataset(d)
        ids[name] = d.id
    return ids


def _custom():
    from groundwork_geophysics.core.colors import ColorScale
    from groundwork_geophysics.core.interpolators import Interpolation
    from groundwork_geophysics.section.data import LayerStyle
    return LayerStyle(visible=True, opacity=0.7, scale=ColorScale("viridis", 5.0, 500.0, True),
                      mode="smooth", contour_step=0.5, contour_major=(10.0, 100.0),
                      grid_cell=0.5, interpolation=Interpolation("idw", power=3.0),
                      fade_coverage=True, fade_mode="blank")


def test_styles_survive_saving_and_reopening(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.section.style_store import load_styles, save_styles

    prj = QgsProject()
    style = _custom()
    save_styles(prj, {"d1": style, "d2": replace(style, visible=False, scale=None)})
    back = load_styles(prj)
    assert back["d1"] == style
    assert back["d2"].visible is False and back["d2"].scale is None


def test_saving_the_same_styles_leaves_the_project_unchanged(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.section.style_store import save_styles

    prj = QgsProject()
    save_styles(prj, {"d1": _custom()})
    prj.setDirty(False)
    save_styles(prj, {"d1": _custom()})
    assert not prj.isDirty()


def test_an_unusable_entry_gives_no_styles(qgis_app):
    from qgis.core import QgsProject

    from groundwork_geophysics.section.style_store import (SCOPE, STYLES_KEY, load_styles)

    prj = QgsProject()
    for text in ("not json", "{}", '[{"no": "id"}, 3]'):
        prj.writeEntry(SCOPE, STYLES_KEY, text)
        assert load_styles(prj) == {}


def test_same_method_is_the_same_type_quantity_and_unit(store_with_model):
    from groundwork_geophysics.section.style_store import same_method

    st, p, src = store_with_model
    ids = _three_lines(st, p, src)
    assert [d.id for d in same_method(st, "d1")] == [ids["P2"]]
    assert same_method(st, ids["P3"]) == []
    assert same_method(st, "gone") == []


def test_the_provider_tells_when_a_style_changes(store_with_model):
    from groundwork_geophysics.section.data import SectionDataProvider

    st, _p, _src = store_with_model
    provider = SectionDataProvider(st, styles={"d1": _custom()})
    assert provider.style("d1") == _custom()
    told = []
    provider.on_style.append(lambda: told.append(dict(provider.styles())))
    provider.set_style("d1", replace(_custom(), opacity=0.3))
    assert told[-1]["d1"].opacity == 0.3


# -- the panel -----------------------------------------------------------------------------
def test_apply_style_to_all_sections_of_the_same_method(qgis_app, store_with_model, make_dock):
    from groundwork_geophysics.section.dock import APPLIED_ALL

    st, p, src = store_with_model
    ids = _three_lines(st, p, src)
    dock = make_dock(st)
    provider = dock.provider
    provider.set_style(ids["P2"], replace(provider.style(ids["P2"]), visible=False))
    provider.set_style("d1", _custom())
    dock.apply_style_to_all("d1")
    got = provider.style(ids["P2"])
    assert got == replace(_custom(), visible=False)          # shown or not stays
    assert provider.style(ids["P3"]) != _custom()            # refraction: never
    assert provider.style(ids["P4"]) != _custom()            # another unit: never
    assert dock.readout.text() == APPLIED_ALL.format(n=1, what="ERT model")
    dock.interp.undo.stack.undo()                            # one step takes it all back
    assert provider.style(ids["P2"]).scale != _custom().scale


def test_the_layer_menu_offers_it_only_with_models_to_apply_to(qgis_app, store_with_model,
                                                                make_dock):
    from groundwork_geophysics.section.layer_list import APPLY_ALL_TEXT

    st, p, src = store_with_model
    dock = make_dock(st)

    def action():
        menu = dock.layer_list.row_menu("d1")
        return next(a for a in menu.actions() if a.text() == APPLY_ALL_TEXT)

    assert not action().isEnabled()
    _three_lines(st, p, src)
    assert action().isEnabled()
