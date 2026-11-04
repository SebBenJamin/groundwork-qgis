"""Readings layers on the section: misfit by default, points, value switch, readout."""
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "readers"))


@pytest.fixture
def misfit_store(store_with_model, tmp_path):
    from test_bert_data import DATA

    from geophysics_workbench.core.model import Dataset, file_fingerprint
    st, p, _ = store_with_model
    data = tmp_path / "line.data"
    data.write_text(DATA.replace("\n0 10.0\n1 10.1\n2 10.2\n3 10.3\n4 10.4\n5 10.5",
                                 "\n0 100\n10 100.4\n20 100.8\n30 101.2\n40 101.6\n50 102"))
    (tmp_path / "resp.vector").write_text("\n".join(str(v) for v in (110, 121, 108, 143, 140)))
    mt, sha = file_fingerprint(data)
    s = st.station_sets(p.id)[0]
    st.save_dataset(Dataset("dm", p.id, s.id, "ert_misfit", str(data), mt, sha, "bert_data",
                            {"response": "resp.vector"}, {}, quantity="misfit", unit="%",
                            name="T misfit"))
    return st, p


def _readings_layer(prov, p):
    return next(la for la in prov.layers(p.id) if la.dataset.id == "dm")


def test_misfit_layer_defaults_to_points_and_centred_scale(qgis_app, misfit_store):
    from geophysics_workbench.section.data import SectionDataProvider
    st, p = misfit_store
    prov = SectionDataProvider(st)
    layer = _readings_layer(prov, p)
    assert layer.error is None, layer.error
    assert layer.mesh.readings is not None and layer.style.mode == "points"
    sc = layer.style.scale
    assert sc.cmap == "RdYlBu_r" and not sc.log and sc.vmin == pytest.approx(-sc.vmax)
    assert layer.mesh.quantity == "misfit"


def test_shown_value_switch_rebuilds_values(qgis_app, misfit_store):
    from geophysics_workbench.section.data import SectionDataProvider
    st, p = misfit_store
    prov = SectionDataProvider(st)
    _readings_layer(prov, p)
    prov.set_style("dm", replace(prov.style("dm"), shown="measured", scale=None))
    layer = _readings_layer(prov, p)
    assert layer.mesh.quantity == "resistivity" and layer.style.scale.log
    assert np.allclose(np.sort(layer.mesh.point_values), [100, 110, 120, 130, 140])


def test_identify_reports_the_reading(qgis_app, misfit_store):
    from geophysics_workbench.section.data import SectionDataProvider, identify_layers
    from geophysics_workbench.section.readout import format_readout
    st, p = misfit_store
    prov = SectionDataProvider(st)
    layer = _readings_layer(prov, p)
    s, z = layer.mesh.vertices[0]
    [hit] = [h for h in identify_layers([layer], s, z) if h["dataset_id"] == "dm"]
    assert hit["reading"]["measured"] in (100, 110, 120, 130, 140)
    assert hit["value"] == pytest.approx(hit["reading"]["misfit"])
    text = format_readout(s, z, hits=[hit])
    assert "A " in text and "meas" in text and "calc" in text


def test_points_mode_draws_markers(qgis_app, misfit_store):
    from geophysics_workbench.section.display_render import build_drawing
    from geophysics_workbench.section.data import SectionDataProvider
    st, p = misfit_store
    prov = SectionDataProvider(st)
    layer = _readings_layer(prov, p)
    drawing = build_drawing(layer, None)
    assert drawing.markers and not drawing.groups and drawing.field is None
    assert sum(len(pts) for _c, pts in drawing.markers) == len(layer.mesh.point_values)
