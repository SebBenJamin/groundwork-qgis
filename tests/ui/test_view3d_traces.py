"""Reflection sections in 3D: they only stand in their profile's section picture (no cells,
point cloud or contour lines are made of them), whatever look is stored."""
import shutil
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("segyio")

from groundwork_geophysics.core.context import ContextItems  # noqa: E402
from groundwork_geophysics.core.model import (Dataset, file_fingerprint,  # noqa: E402
                                              profile_from_polyline)
from groundwork_geophysics.section.data import SectionDataProvider  # noqa: E402
from groundwork_geophysics.store.gpkg_store import ProjectStore  # noqa: E402
from segy_files import write_segy  # noqa: E402

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CRS = "EPSG:25832"
#: 11 traces x 50 samples at 1 ms, signed; the first 10 samples of every trace muted (zero)
AMPLITUDES = np.sin(np.arange(11 * 50, dtype=np.float32) / 3.0).reshape(11, 50)
AMPLITUDES[:, :10] = 0.0


@pytest.fixture
def setup(qgis_app, tmp_path):
    """(store, profile, provider, project): a 60 m profile with an ERT model ("d", which
    gives the profile its heights) and a reflection section ("s") hung at 100 m."""
    from qgis.core import QgsProject
    st = ProjectStore.create(tmp_path / "p.gpkg", CRS)
    p = profile_from_polyline("P1", CRS, np.array([[0.0, 0.0], [60.0, 0.0]]))
    st.save_profile(p)
    src = tmp_path / "d.dat"
    shutil.copy(FIXTURES / "ert" / "f001_res.dat", src)
    mt, sha = file_fingerprint(src)
    st.save_dataset(Dataset("d", p.id, "", "ert_model", str(src), mt, sha, "r2_res_dat",
                            {"z_kind": "elevation"}, {}, name="Model d"))
    path = write_segy(tmp_path / "line.sgy", AMPLITUDES, dt_us=1000, fmt=5)
    mt, sha = file_fingerprint(path)
    st.save_dataset(Dataset("s", p.id, "", "refl_section", str(path), mt, sha, "segy",
                            {"position": "spacing", "spacing": 5.0, "velocity": 2000.0,
                             "zero": "datum", "datum": 100.0}, {}, name="Line s"))
    provider = SectionDataProvider(st)
    provider.context_source = lambda profile: ContextItems()
    return st, p, provider, QgsProject()


def _choose(prj, models, looks=None):
    from groundwork_geophysics.ui.view3d_layers import Choice, write_choice
    write_choice(prj, Choice(frozenset(models), frozenset(), looks or {}))


def _dataset(st, p, did):
    return next(d for d in st.datasets(p.id) if d.id == did)


@pytest.mark.parametrize("stored", [None, "section", "cloud", "picture"])
def test_a_section_always_stands_as_a_picture(setup, stored):
    from groundwork_geophysics.ui.view3d_layers import read_choice, representations
    st, p, _provider, prj = setup
    _choose(prj, ["s"], {"s": stored} if stored else {})
    choice = read_choice(prj)
    assert choice.look_for(_dataset(st, p, "s")) == "picture"
    assert representations(_dataset(st, p, "s")) == ("picture",)
    assert representations(_dataset(st, p, "d")) == ("section", "cloud", "picture")
    assert choice.look_for(_dataset(st, p, "d")) == "section"


def test_the_dialog_offers_only_the_section_picture_for_a_section(setup):
    from groundwork_geophysics.ui.view3d_dialog import View3dDialog
    from groundwork_geophysics.ui.view3d_layers import Choice
    st, _p, _provider, _prj = setup
    dlg = View3dDialog(st, Choice(frozenset({"s", "d"}), looks={"s": "cloud"}))
    combo = dlg._looks["s"]
    assert [combo.itemData(i) for i in range(combo.count())] == ["picture"]
    assert [combo.itemText(i) for i in range(combo.count())] == ["Section Picture"]
    assert dlg._looks["d"].count() == 3
    assert dlg.choice().looks["s"] == "picture"
    dlg.deleteLater()


@pytest.mark.parametrize("stored", ["section", "cloud"])
def test_sync_makes_only_the_picture_of_a_section(setup, stored):
    from groundwork_geophysics.ui.view3d_layers import cloud_folder, sync
    st, p, provider, prj = setup
    _choose(prj, ["s"], {"s": stored})
    out = sync(st, provider, prj, create=True)
    assert {"models", "clouds", "contours"}.isdisjoint(out)
    assert list(out["pictures"]) == [p.id] and out["pictures"][p.id].isValid()
    assert sorted(f.suffix for f in cloud_folder(st).iterdir()) == [".glb", ".json"]


def test_a_model_as_cells_and_a_section_in_the_picture_mix(setup):
    from groundwork_geophysics.ui.view3d_layers import sync
    st, p, provider, prj = setup
    _choose(prj, ["s", "d"])
    out = sync(st, provider, prj, create=True)
    assert out["models"].featureCount() > 0 and list(out["pictures"]) == [p.id]
    datasets = {f["dataset_id"] for f in out["models"].getFeatures()}
    assert datasets == {"d"}


@pytest.mark.background_reads                 # the real ``pending_3d``
def test_the_prepared_jobs_keep_the_traces(setup):
    from groundwork_geophysics.ui.view3d_prepare import pending_3d
    st, p, provider, prj = setup
    _choose(prj, ["s"], {"s": "cloud"})
    jobs = pending_3d(st, provider, prj)
    assert [j.kind for j in jobs] == ["picture"]
    (layer,) = jobs[0].layers
    assert layer.traces is not None and layer.mesh is None
    assert layer.traces is provider.layers(p.id)[1].traces or \
        np.shares_memory(layer.traces.section.amplitudes,
                         provider.layers(p.id)[1].traces.section.amplitudes)


def test_the_picture_of_a_section_leaves_its_muted_top_to_the_background(setup):
    from qgis.PyQt.QtGui import QColor

    from groundwork_geophysics.section.picture import section_pictures
    st, p, provider, _prj = setup
    layer = next(la for la in provider.layers(p.id) if la.dataset.id == "s")
    (pic,) = section_pictures([layer], None, base=QColor(255, 0, 255))
    rows = pic.alpha.shape[0]
    # time zero at 100 m, 1 m per sample (2000 m/s, 1 ms): the top ten samples are muted
    muted = pic.alpha[: int(rows * 8 / 49)]
    live = pic.alpha[int(rows * 15 / 49):]
    assert muted.max() == 0 and live.min() > 0
    c = pic.image.pixelColor(pic.image.width() // 2, 1)
    assert (c.red(), c.green(), c.blue()) == (255, 0, 255)


def test_the_box_around_what_3d_shows_counts_a_section(setup):
    from groundwork_geophysics.ui.view3d_layers import shown_box
    st, _p, provider, prj = setup
    _choose(prj, ["s"])
    box = shown_box(st, provider, prj)
    assert box is not None
    assert box[4] == pytest.approx(100.0 - 49.0) and box[5] == pytest.approx(100.0)
