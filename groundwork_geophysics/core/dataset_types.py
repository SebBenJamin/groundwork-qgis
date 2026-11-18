"""What kind of data each dataset is: its method and what it shows (no QGIS/Qt).

``Dataset.kind`` is a stored code; this table gives it the method label, the product, the
quantity with its unit, and whether its colour scale is logarithmic. Codes not in the table
(older or foreign stores) label as their raw code."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DatasetType:
    code: str
    method: str          # e.g. "ERT", "Seismic refraction"
    shows: str           # e.g. "model", "Vp model"
    quantity: str
    unit: str
    log: bool


TYPES: dict[str, DatasetType] = {t.code: t for t in (
    DatasetType("ert_model", "ERT", "model", "resistivity", "ohm.m", True),
    DatasetType("ert_measured", "ERT", "measured data", "resistivity", "ohm.m", True),
    DatasetType("ert_misfit", "ERT", "misfit", "misfit", "%", False),
    DatasetType("srt_model", "Seismic refraction", "Vp model", "p_velocity", "m/s", False),
)}

#: kinds of readings files (measured data, misfit): never a model, always ERT so far
READINGS_KINDS = ("ert_measured", "ert_misfit")
#: station-set and dataset method choices: (label, code)
METHODS: list[tuple[str, str]] = [("ERT", "ert"), ("Seismic refraction", "srt")]
_MODEL_KINDS = {"ert": "ert_model", "srt": "srt_model"}
_QUANTITY_LABELS = {"resistivity": "Resistivity", "p_velocity": "P-wave velocity",
                    "misfit": "Misfit"}


def type_label(kind: str) -> str:
    """"ERT model", "Seismic refraction Vp model"; the raw code for an unknown kind."""
    t = TYPES.get(kind)
    return f"{t.method} {t.shows}" if t else kind


def method_label(kind: str) -> str:
    """The method of a kind; for an unknown kind the first word of its code."""
    t = TYPES.get(kind)
    return t.method if t else kind.split(" ")[0]


def quantity_label(quantity: str) -> str:
    return _QUANTITY_LABELS.get(quantity, (quantity or "").capitalize())


def model_kind(method: str) -> str:
    """The model kind of a method code ("ert" -> "ert_model")."""
    try:
        return _MODEL_KINDS[method]
    except KeyError:
        raise ValueError(f"unknown method {method!r}") from None


def station_words(method: str) -> tuple[str, str]:
    """(singular, plural) of what a method's stations are called."""
    return ("geophone", "geophones") if method == "srt" else ("electrode", "electrodes")
