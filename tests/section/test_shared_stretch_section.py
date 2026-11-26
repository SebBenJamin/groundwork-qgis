"""A profile sharing a stretch of line with another one: one marker and one tie strip for the
other profile on the section, one row in the ties panel."""
import numpy as np
import pytest


def test_a_shared_stretch_is_labelled_with_the_other_profile_and_its_extent():
    from groundwork_geophysics.core.ties import Tie
    from groundwork_geophysics.section.context_render import tie_label
    tie = Tie(150.0, "b", "R2", 40.0, 0.0, [], stretch=(164.6, 259.6))
    assert tie_label(tie) == "R2 · along 165–260 m"
    assert tie_label(Tie(150.0, "b", "R2", 40.0, 0.0, [])) == "R2"


@pytest.fixture
def along(tmp_path):
    """P1 straight along x (0 .. 300 m) and P2 running along it, crossing it every 5 m from
    x = 100 to 200 m, then away."""
    from groundwork_geophysics.core.model import profile_from_stations
    from groundwork_geophysics.store.gpkg_store import ProjectStore
    st = ProjectStore.create(tmp_path / "p.gpkg", "EPSG:25832")
    p1, s1 = profile_from_stations("P1", "EPSG:25832",
                                   np.array([[0.0, 0.0, 100.0], [300.0, 0.0, 100.0]]))
    x = 97.5 + 5.0 * np.arange(22)
    y = np.where(np.arange(22) % 2 == 0, -1.0, 1.0)
    xy = np.vstack([[97.5, -50.0], np.column_stack([x, y]), [202.5, 50.0]])
    p2, s2 = profile_from_stations("P2", "EPSG:25832",
                                   np.column_stack([xy, np.full(len(xy), 100.0)]))
    for p, s in ((p1, s1), (p2, s2)):
        st.save_profile(p)
        st.save_station_set(s)
    return st, p1, p2


def test_the_snapshot_holds_one_marker_and_one_tie_for_the_other_profile(qgis_app, along):
    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.section.data import SectionDataProvider
    st, p1, p2 = along
    prov = SectionDataProvider(st)
    prov.context_source = lambda profile: ContextItems()
    [tie] = prov.snapshot(p1.id).context.ties
    assert tie.other_name == "P2" and tie.stretch == pytest.approx((100.0, 200.0))
    assert tie.s == pytest.approx(150.0)
    [back] = prov.ties(p2.id)                       # and one on P2 for P1
    assert back.stretch is not None and back.other_name == "P1"


def test_the_ties_panel_lists_a_shared_stretch_once(qgis_app, along):
    from groundwork_geophysics.core.context import ContextItems
    from groundwork_geophysics.section.data import SectionDataProvider
    from groundwork_geophysics.ui.ties_panel import SHARED_TEXT, build_rows
    st, p1, p2 = along
    prov = SectionDataProvider(st)
    prov.context_source = lambda profile: ContextItems()
    [row] = build_rows(prov)
    assert row.stretch == pytest.approx((100.0, 200.0))
    assert SHARED_TEXT in row.title
