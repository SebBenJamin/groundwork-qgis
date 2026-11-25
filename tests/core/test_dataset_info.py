from groundwork_geophysics.core.dataset_info import (INFO_FIELDS, dataset_info, provenance_line,
                                                    with_info)
from groundwork_geophysics.core.model import Dataset


def _dataset(kind="ert_model", provenance=None):
    return Dataset("d1", "p1", "s1", kind, "/x/model.vtk", 0.0, "", "vtk_legacy", {},
                   dict(provenance or {}))


def test_provenance_line_only_known_parts():
    d = _dataset(provenance={"rms_percent": 8.0})
    assert provenance_line("Transect 3", d) == "Transect 3 · ERT model · RMS 8.0 %"
    d = with_info(d, {"software": "BERT inversion", "reference": "Pohle et al. 2025",
                      "array": "dipole-dipole", "spacing": "1 m"})
    assert provenance_line("Transect 3", d) == ("Transect 3 · ERT model: BERT inversion "
                                                "(Pohle et al. 2025) · dipole-dipole, 1 m "
                                                "spacing · RMS 8.0 %")


def test_line_for_other_kinds_and_nothing_known():
    assert provenance_line("T1", _dataset("ert_misfit")) == "T1 · ERT misfit"
    assert provenance_line("T1", _dataset("ert_measured")) == "T1 · ERT measured data"
    assert provenance_line("T1", _dataset("seismic_x")) == "T1 · seismic_x"


def test_with_info_keeps_detected_values_and_only_known_fields():
    d = with_info(_dataset(provenance={"rms_percent": 8.0}),
                  {"method": " ERT ", "bogus": "x", "note": ""})
    assert dataset_info(d) == {"method": "ERT"}
    assert d.provenance["rms_percent"] == 8.0
    assert set(INFO_FIELDS) == {"method", "array", "spacing", "date", "software", "reference",
                                "note"}


AVERAGED = {"block": [4, 5], "cell_file": [0.25, 0.1], "cell": [1.0, 0.5],
            "n_points_file": 623241}


def test_the_plate_line_says_the_cells_were_averaged():
    d = _dataset(provenance={**AVERAGED, "rms_percent": 8.0})
    assert provenance_line("T3", d) == "T3 · ERT model · averaged to 1 × 0.5 m cells · RMS 8.0 %"
    assert "averaged" not in provenance_line("T3", _dataset(provenance={"rms_percent": 8.0}))
