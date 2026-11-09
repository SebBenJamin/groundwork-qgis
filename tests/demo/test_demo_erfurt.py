"""Erfurt real-data demo: converters (pure) and the build from the downloaded cache."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO / "scripts"))
CACHE = Path(__import__("os").environ.get("WB_ERFURT_CACHE", REPO / ".cache" / "erfurt"))

SUPPLEMENT_SAMPLE = [
    "6. Stratigraphic logs of sediment cores", ".",
    "Core EN-RK 1 (642451.13 E, 5654013.3 N) ", "Depth (cm)", "Strat. Unit",
    "Selected Properties", "0-75", "SU7", "loamy, humic, calcareous ", "75-230", "SU6",
    "sandy-gravelly, calcareous", "230-400", "SU1/SU3", "silty-clayey, slightly calcareous",
    "Suppl. Table 3: Simplified stratigraphic logs of all sediment cores retrieved in the "
    "study area. Coordinates are given in UTM zone 32N",
    "Core EN-RK 55 (642538.479 E, 5654119.482 N)", "Depth (cm)", "Strat. Unit",
    "Selected Properties", "0-285", "SU2-SU5",
    "loamy-silty to gravelly, calcareous, slightly humic, occupation feature (mass grave)",
    "285-347", "SU2", "sandy-gravelly, calcareous",
    "Core EN-RK 40 (E, N)", "Depth (cm)", "Strat. Unit", "Selected Properties",
    "0-60", "SU5.2", "silty, humic, calcareous"]


def test_parse_core_logs_from_supplement_paragraphs():
    import erfurt_data
    sites, logs = erfurt_data.parse_core_logs(SUPPLEMENT_SAMPLE)
    assert [(s.id, s.x, s.y) for s in sites] == [("EN-RK 1", 642451.13, 5654013.3),
                                                  ("EN-RK 55", 642538.479, 5654119.482)]
    assert logs["EN-RK 1"] == [(0.0, 0.75, "SU7", "loamy, humic, calcareous"),
                               (0.75, 2.3, "SU6", "sandy-gravelly, calcareous"),
                               (2.3, 4.0, "SU1/SU3", "silty-clayey, slightly calcareous")]
    assert logs["EN-RK 55"][0][2:] == (
        "SU2-SU5", "loamy-silty to gravelly, calcareous, slightly humic, occupation feature "
        "(mass grave)")                                       # the authors' words, unchanged
    assert logs["EN-RK 55"][-1][:2] == (2.85, 3.47)        # nothing from EN-RK 40 added
    assert logs["EN-RK 40"] == [(0.0, 0.6, "SU5.2", "silty, humic, calcareous")]


def test_survey_info_from_raw_data(tmp_path):
    import erfurt_data
    raw = tmp_path / "raw.txt"
    raw.write_text("#\tType\tC1(x)\tRho\tTime\n"
                   "0\tWA\t0\t295.8\t16.01.2023 9:58:01\n"
                   "1\tDD\t0.5\t343.1\t16.01.2023 10:20:41\n"
                   "2\tWA\t1\t305.6\t16.01.2023 10:21:00\n", encoding="utf-8")
    info = erfurt_data.survey_info(raw)
    assert info == {"array": "Wenner alpha, dipole-dipole", "date": "2023-01-16"}


def test_real_supplement_has_all_58_cores():
    import erfurt_data
    docx = CACHE / "pone.0337410.s001.docx"
    if not docx.exists():
        pytest.skip("supplement missing: see scripts/fetch_demo_erfurt.py")
    sites, logs = erfurt_data.parse_core_logs(erfurt_data.docx_paragraphs(docx))
    # EN-RK 40 and 46 are listed without coordinates: logs, but no site
    assert {s.id for s in sites} == {f"EN-RK {i}" for i in range(1, 59)} - {"EN-RK 40",
                                                                             "EN-RK 46"}
    assert len(logs) == 58
    assert all(642300 < s.x < 642800 and 5653900 < s.y < 5654400 for s in sites)
    for rows in logs.values():
        assert rows and rows[0][0] == 0.0
        assert all(top < bottom for top, bottom, _u, _p in rows)


def test_build_workbench_seven_transects_with_info(tmp_path, qgis_app):
    if not (CACHE / "ERT02").exists():
        pytest.skip("Erfurt cache missing")
    import build_demo_erfurt

    from geophysics_workbench.core.dataset_info import dataset_info, provenance_line
    from geophysics_workbench.section.data import SectionDataProvider
    from geophysics_workbench.store.gpkg_store import ProjectStore
    build_demo_erfurt.build_data(cache=CACHE, out=tmp_path)
    st = ProjectStore.open(build_demo_erfurt.build_workbench(out=tmp_path, cache=CACHE))
    assert sorted(p.name for p in st.profiles()) == [
        "ERT02", "ERT03", "ERT04", "ERT06", "ERT07", "ERT11", "ERT12"]
    prov = SectionDataProvider(st)
    for p in st.profiles():
        kinds = sorted(d.kind for d in st.datasets(p.id))
        assert kinds == ["ert_measured", "ert_model"], p.name
        assert all(la.error is None for la in prov.layers(p.id)), p.name
    ert06 = next(p for p in st.profiles() if p.name == "ERT06")
    model = next(d for d in st.datasets(ert06.id) if d.kind == "ert_model")
    info = dataset_info(model)
    assert info["array"] == "Wenner alpha, dipole-dipole" and info["spacing"] == "0.5 m"
    assert info["software"] == "BERT 2.2.9" and info["date"] == "2023-01-16"
    assert "Silbermann et al. 2025" in provenance_line("ERT06", model)
