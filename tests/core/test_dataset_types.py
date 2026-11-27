import pytest

from groundwork_geophysics.core import roles
from groundwork_geophysics.core.dataset_types import (TYPES, method_label, model_kind,
                                                      quantity_label, station_words,
                                                      type_label)


def test_known_and_unknown_labels():
    assert type_label("ert_model") == "ERT model"
    assert type_label("srt_model") == "Seismic refraction Vp model"
    assert type_label("seismic_x") == "seismic_x"
    assert method_label("srt_model") == "Seismic refraction"
    assert method_label("ert_misfit") == "ERT"
    assert method_label("odd_kind") == "odd_kind"


def test_quantity_labels():
    assert quantity_label("p_velocity") == "P-wave velocity"
    assert quantity_label("resistivity") == "Resistivity"
    assert quantity_label("chargeability") == "Chargeability"
    assert quantity_label("") == ""


def test_model_kind_and_words():
    assert model_kind("srt") == "srt_model"
    assert model_kind("ert") == "ert_model"
    with pytest.raises(ValueError):
        model_kind("xyz")                   # "gpr" became a method (radargrams)
    assert station_words("srt") == ("geophone", "geophones")
    assert station_words("") == ("electrode", "electrodes")


def test_srt_type_is_linear_velocity():
    t = TYPES["srt_model"]
    assert t.unit == "m/s" and t.log is False and t.quantity == "p_velocity"


def test_velocity_quantity_offered():
    assert ("P-wave velocity (m/s)", "p_velocity", "m/s") in roles.QUANTITIES
    assert roles.QUANTITIES[-1] == ("Other", "", "")


def test_method_of_a_profile():
    from groundwork_geophysics.core.dataset_types import method_of
    assert method_of(["srt_model"]) == "srt"
    assert method_of(["srt_model", "ert_model"]) == "ert"        # mixed: ERT words stay
    assert method_of([]) == "ert"
    assert method_of(["ert_model"], ["srt"]) == "srt"            # its station set decides


def test_reflection_section_type():
    from groundwork_geophysics.core.dataset_types import METHODS, is_trace_kind, method_of
    assert type_label("refl_section") == "Seismic reflection section"
    assert model_kind("refl") == "refl_section" and ("Seismic reflection", "refl") in METHODS
    assert method_of(["refl_section"]) == "refl" and method_of(["refl_section", "ert_model"]) == "ert"
    assert is_trace_kind("refl_section") and not is_trace_kind("srt_model")
    assert station_words("refl") == ("geophone", "geophones")
    assert quantity_label("amplitude") == "Amplitude"
    t = TYPES["refl_section"]
    assert (t.quantity, t.unit, t.log) == ("amplitude", "", False)


def test_reversed_grey_is_offered():
    from groundwork_geophysics.core.colors import COLORMAPS, ColorScale
    assert "gray_r" in COLORMAPS and ColorScale("gray_r", 0.0, 1.0, False).rgba([0.0])[0, 0] == 255


def test_radargram_type():
    from groundwork_geophysics.core.dataset_types import (METHODS, is_radar_kind, is_trace_kind,
                                                          method_of)
    t = TYPES["gpr_section"]
    assert (t.method, t.shows, t.quantity, t.unit, t.log) == ("GPR", "radargram", "amplitude", "",
                                                              False)
    assert type_label("gpr_section") == "GPR radargram"
    assert ("GPR", "gpr") in METHODS and model_kind("gpr") == "gpr_section"
    assert is_trace_kind("gpr_section") and is_radar_kind("gpr_section")
    assert not is_radar_kind("refl_section") and not is_radar_kind("ert_model")
    assert method_of(["gpr_section"]) == "gpr" and method_of(["gpr_section", "refl_section"]) == "ert"
    with pytest.raises(ValueError):
        model_kind("magnetics")
