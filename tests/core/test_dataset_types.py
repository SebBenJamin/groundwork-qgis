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
        model_kind("gpr")
    assert station_words("srt") == ("geophone", "geophones")
    assert station_words("") == ("electrode", "electrodes")


def test_srt_type_is_linear_velocity():
    t = TYPES["srt_model"]
    assert t.unit == "m/s" and t.log is False and t.quantity == "p_velocity"


def test_velocity_quantity_offered():
    assert ("P-wave velocity (m/s)", "p_velocity", "m/s") in roles.QUANTITIES
    assert roles.QUANTITIES[-1] == ("Other", "", "")
