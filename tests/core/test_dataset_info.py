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


# -- reflection sections ----------------------------------------------------------------------
def _section(options=None, provenance=None):
    prov = {"n_traces": 1970, "n_samples": 1125, "step": 0.004, **(provenance or {})}
    return Dataset("s1", "p1", "", "refl_section", "/x/line.sgy", 0.0, "", "segy",
                   dict(options or {}), prov)


def test_depth_text_of_a_time_section_names_its_velocity():
    from groundwork_geophysics.core.dataset_info import depth_text
    assert depth_text(_section({"velocity": 1500.0})) == "depth from v = 1500 m/s"
    function = {"velocity_table": [[0.0, 1800.0], [1.0, 3400.0]], "velocity_kind": "average"}
    assert depth_text(_section(function)) == \
        "depth from a velocity function (1800–3400 m/s)"


def test_depth_text_of_a_depth_section_and_of_other_kinds():
    from groundwork_geophysics.core.dataset_info import depth_text
    assert depth_text(_section({"domain": "depth", "sample_step": 1.0})) == "depth section"
    assert depth_text(_dataset()) == ""
    assert depth_text(_section({})) == ""             # no velocity known: nothing invented


def test_depth_text_says_the_section_is_corrected_to_the_ground():
    from groundwork_geophysics.core.dataset_info import depth_text
    d = _section({"velocity": 3000.0, "zero": "datum_ground", "datum": 500.0,
                  "replacement_velocity": 3200.0})
    assert depth_text(d) == "depth from v = 3000 m/s, corrected to the ground with 3200 m/s"


def test_traces_text_counts_traces_and_samples():
    from groundwork_geophysics.core.dataset_info import traces_text
    from groundwork_geophysics.core.numbers import fmt_count
    assert traces_text(_section()) == f"{fmt_count(1970)} traces × {fmt_count(1125)} samples, 4 ms"
    assert traces_text(_section({"sample_step": 0.002})) == \
        f"{fmt_count(1970)} traces × {fmt_count(1125)} samples, 2 ms"
    from groundwork_geophysics.core.numbers import fmt_trim
    assert traces_text(_section({"domain": "depth", "sample_step": 0.5})).endswith(
        f"samples, {fmt_trim(0.5, 3)} m")
    assert traces_text(_dataset()) == ""


def test_the_plate_line_of_a_section_carries_its_depth():
    d = _section({"velocity": 1500.0})
    assert provenance_line("T1", d) == "T1 · Seismic reflection · section · depth from v = 1500 m/s"
    d = _section({"domain": "depth", "sample_step": 1.0})
    assert provenance_line("T1", d) == "T1 · Seismic reflection · section · depth section"
    d = with_info(_section({"velocity": 1500.0}), {"software": "ProMAX"})
    assert provenance_line("T1", d) == \
        "T1 · Seismic reflection · section: ProMAX · depth from v = 1500 m/s"
