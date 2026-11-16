"""The stamp's plate-filled texts: profile, method, survey details, title and plate number."""
from groundwork_geophysics.core.dataset_info import with_info
from groundwork_geophysics.core.model import Dataset
from groundwork_geophysics.core.plates import PlateSpec
from groundwork_geophysics.plates.stamp import stamp_texts


def _dataset(kind="ert_model", provenance=None):
    return Dataset("d1", "p1", "s1", kind, "/x/model.vtk", 0.0, "", "vtk_legacy", {},
                   dict(provenance or {}))


def _plate(number="3", title="Transect"):
    return PlateSpec("pl1", number, title, "A3_landscape", [])


def test_single_profile_full_info():
    d = with_info(_dataset(provenance={"rms_percent": 2.14}),
                  {"method": "ERT", "array": "dipole-dipole", "date": "2024-06-12",
                   "spacing": "1 m", "software": "ResIPy, robust", "reference": "Pohle 2025"})
    t = stamp_texts(_plate("1", "Transect 3 – ERT model"), ["Transect 3"], [d],
                    [(750, 10.0)], "EPSG:25833", "ETRS89 / UTM zone 33N")
    assert t == {"profile": "Transect 3", "method": "ERT · dipole-dipole",
                 "survey": "Acquired 2024-06-12 · electrode spacing 1 m\n"
                           "Inversion: ResIPy, robust (Pohle 2025) · RMS 2.1 %\n"
                           "Scale 1:750 · VE 10× · EPSG:25833 (ETRS89 / UTM zone 33N)",
                 "title": "Transect 3 – ERT model", "plate": "Plate 1"}


def test_no_info_falls_back_to_kind():
    t = stamp_texts(_plate(), ["T1"], [_dataset("ert_model")], [(500, 1.0)], "EPSG:25833", "")
    assert t["method"] == "ERT"
    assert t["survey"] == "Scale 1:500 · VE 1× · EPSG:25833"


def test_survey_partial_info():
    d = with_info(_dataset(), {"spacing": "2 m", "software": "BERT"})
    survey = stamp_texts(_plate(), ["T1"], [d], [(500, 2.0)], "EPSG:25833", "")["survey"]
    assert survey.splitlines()[:2] == ["Electrode spacing 2 m", "Inversion: BERT"]
    assert "Acquired" not in survey and "()" not in survey and "· ·" not in survey


def test_reference_without_software():
    d = with_info(_dataset(provenance={"rms_percent": 5.0}), {"reference": "Hein 2026"})
    survey = stamp_texts(_plate(), ["T1"], [d], [(500, 2.0)], "EPSG:25833", "")["survey"]
    assert survey.splitlines()[0] == "Reference: Hein 2026 · RMS 5.0 %"


def test_two_profiles_differing_scale():
    a = with_info(_dataset(), {"method": "ERT", "date": "2024-06-12"})
    b = with_info(_dataset(), {"method": "ERT", "date": "2023-06-01"})
    t = stamp_texts(_plate(), ["T1", "T2"], [a, b], [(500, 5.0), (750, 5.0)], "EPSG:25833", "")
    assert t["profile"] == "T1, T2" and t["method"] == "ERT"
    assert "Acquired" not in t["survey"]
    assert t["survey"].splitlines()[-1] == "Scale and VE per section · EPSG:25833"


def test_missing_profile_ignored():
    t = stamp_texts(_plate(), [], [], [], "EPSG:25833", "")
    assert t["profile"] == "" and t["method"] == "" and t["survey"] == ""


def test_misfit_without_info_does_not_hide_the_models():
    model = with_info(_dataset(provenance={"rms_percent": 3.0}),
                      {"method": "ERT", "array": "dipole-dipole", "date": "2024-06-12"})
    misfit = _dataset("ert_misfit")
    t = stamp_texts(_plate(), ["T1"], [model, misfit], [(500, 2.0)], "EPSG:25833", "")
    assert t["method"] == "ERT · dipole-dipole"
    assert t["survey"].splitlines()[:2] == ["Acquired 2024-06-12", "RMS 3.0 %"]


def test_two_models_one_without_info_shows_only_what_both_share():
    a = with_info(_dataset(), {"date": "2024-06-12"})
    t = stamp_texts(_plate(), ["T1", "T2"], [a, _dataset()], [(500, 2.0), (500, 2.0)],
                    "EPSG:25833", "")
    assert "Acquired" not in t["survey"]
