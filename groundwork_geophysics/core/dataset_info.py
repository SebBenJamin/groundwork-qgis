"""What the user knows about a dataset (method, array, spacing, inversion, reference…), kept
in ``Dataset.provenance["info"]`` next to what the readers detected, and the one-line
provenance a plate prints. Only what is known is printed; nothing is invented."""
from __future__ import annotations

from dataclasses import replace

from .dataset_types import type_label

INFO_FIELDS = ("method", "array", "spacing", "date", "software", "reference", "note")


def dataset_info(d) -> dict[str, str]:
    info = (d.provenance or {}).get("info") or {}
    return {k: str(info[k]).strip() for k in INFO_FIELDS
            if isinstance(info, dict) and k in info and str(info[k]).strip()}


def with_info(d, info: dict):
    """``d`` with its info replaced by the known, non-empty ``info`` fields."""
    clean = {k: str(v).strip() for k, v in info.items()
             if k in INFO_FIELDS and v is not None and str(v).strip()}
    provenance = dict(d.provenance or {})
    provenance["info"] = clean
    return replace(d, provenance=provenance)


def provenance_line(profile_name: str, d) -> str:
    """e.g. "Transect 3 · ERT model: BERT inversion (Pohle et al. 2025) · dipole-dipole,
    1 m spacing · RMS 8.0 %"; parts with nothing known are left out."""
    info = dataset_info(d)
    head = type_label(d.kind)
    software = info.get("software", "")
    if software:
        head += f": {software}" + (f" ({info['reference']})" if info.get("reference") else "")
    elif info.get("reference"):
        head += f" ({info['reference']})"
    parts = [profile_name, head]
    layout = ", ".join(x for x in (info.get("array", ""),
                                   f"{info['spacing']} spacing" if info.get("spacing") else "")
                       if x)
    if layout:
        parts.append(layout)
    rms = (d.provenance or {}).get("rms_percent")
    if isinstance(rms, (int, float)) and not isinstance(rms, bool):
        parts.append(f"RMS {rms:.1f} %")
    return " · ".join(p for p in parts if p)
