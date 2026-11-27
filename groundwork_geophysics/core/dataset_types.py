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
    DatasetType("refl_section", "Seismic reflection", "section", "amplitude", "", False),
    DatasetType("gpr_section", "GPR", "radargram", "amplitude", "", False),
)}

#: kinds of readings files (measured data, misfit): never a model, always ERT so far
READINGS_KINDS = ("ert_measured", "ert_misfit")
#: kinds read as a trace section (traces x samples), not as a cell model
TRACE_KINDS = ("refl_section", "gpr_section")
#: trace kinds that are radargrams: times in nanoseconds, hung with a time zero
RADAR_KINDS = ("gpr_section",)
#: station-set and dataset method choices: (label, code)
METHODS: list[tuple[str, str]] = [("ERT", "ert"), ("Seismic refraction", "srt"),
                                  ("Seismic reflection", "refl"), ("GPR", "gpr")]
_MODEL_KINDS = {"ert": "ert_model", "srt": "srt_model", "refl": "refl_section",
                "gpr": "gpr_section"}
_QUANTITY_LABELS = {"resistivity": "Resistivity", "p_velocity": "P-wave velocity",
                    "misfit": "Misfit", "amplitude": "Amplitude"}


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


def method_of(kinds, station_methods=()) -> str:
    """A profile's method code: its first station set's, else "srt" when every dataset is a
    refraction one, "refl" when every dataset is a reflection one, "gpr" when every dataset is
    a radargram, else "ert" (mixed or no data keep the ERT words)."""
    for m in station_methods:
        if m:
            return m
    kinds = list(kinds)
    for code in ("srt", "refl", "gpr"):
        if kinds and all(k.startswith(code + "_") for k in kinds):
            return code
    return "ert"


def is_trace_kind(kind: str) -> bool:
    """True for a kind read as a trace section (a seismic reflection section, a radargram)."""
    return kind in TRACE_KINDS


def is_radar_kind(kind: str) -> bool:
    """True for a radargram (ground-penetrating radar): times in ns, hung with a time zero."""
    return kind in RADAR_KINDS


def station_words(method: str) -> tuple[str, str]:
    """(singular, plural) of what a method's stations are called."""
    return ("geophone", "geophones") if method in ("srt", "refl") else ("electrode", "electrodes")
