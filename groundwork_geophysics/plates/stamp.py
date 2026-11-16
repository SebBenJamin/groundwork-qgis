"""The plate stamp: an engineering title block ruled into cells, made of ordinary layout items.

``stamp_texts`` composes the cells the plate fills (profile, method, survey details, title,
plate number); only what is known is printed, nothing is invented."""
from __future__ import annotations

from ..core.dataset_info import KIND_LABELS, dataset_info

#: the logo picture's source: @wb_logo made absolute (relative to the project folder), or ''
#: when it is unset or the file is missing, so the cell stays empty instead of a broken image
LOGO_EXPRESSION = (
    "with_variable('p', coalesce(@wb_logo, ''), "
    "with_variable('a', if(@p = '', '', "
    r"if(regexp_match(@p, '^([A-Za-z]:[\\\\/]|[\\\\/])') > 0, @p, @project_folder || '/' || @p)), "
    "if(@a <> '' and file_exists(@a), @a, '')))")


def _shared(values: list[str]) -> str:
    """The value when every entry has the same non-empty one, else ""."""
    return values[0] if values and values[0] and all(v == values[0] for v in values) else ""


def _distinct(values) -> list[str]:
    out = []
    for v in values:
        if v and v not in out:
            out.append(v)
    return out


def _method(d) -> str:
    info = dataset_info(d)
    typed = " · ".join(x for x in (info.get("method", ""), info.get("array", "")) if x)
    return typed or KIND_LABELS.get(d.kind, d.kind).split(" ")[0]


def _rms(d) -> str:
    rms = (d.provenance or {}).get("rms_percent")
    if isinstance(rms, (int, float)) and not isinstance(rms, bool):
        return f"RMS {rms:.1f} %"
    return ""


def _survey(datasets: list, fits: list, crs_authid: str, crs_description: str) -> str:
    from ..core.numbers import fmt_trim
    infos = [dataset_info(d) for d in datasets]

    def shared(key):
        return _shared([i.get(key, "") for i in infos])

    lines = []
    first = " · ".join(x for x in (f"Acquired {shared('date')}" if shared("date") else "",
                                    f"electrode spacing {shared('spacing')}"
                                    if shared("spacing") else "") if x)
    if first:
        lines.append(first[0].upper() + first[1:])
    software, reference = shared("software"), shared("reference")
    if software:
        head = f"Inversion: {software}" + (f" ({reference})" if reference else "")
    else:
        head = f"Reference: {reference}" if reference else ""
    second = " · ".join(x for x in (head, _shared([_rms(d) for d in datasets])) if x)
    if second:
        lines.append(second)
    if fits:
        crs = crs_authid + (f" ({crs_description})" if crs_description else "")
        if all(f == fits[0] for f in fits):
            scale, ve = fits[0]
            lines.append(f"Scale 1:{scale} · VE {fmt_trim(ve, 2)}× · {crs}")
        else:
            lines.append(f"Scale and VE per section · {crs}")
    return "\n".join(lines)


def stamp_texts(plate, profile_names: list[str], datasets: list, fits: list[tuple[int, float]],
                crs_authid: str, crs_description: str) -> dict[str, str]:
    """The texts of the plate-filled cells. ``profile_names``: the plate's existing profiles in
    plate order; ``datasets``: the visible models of all frames; ``fits``: (scale, VE) per
    frame with an existing profile."""
    return {"profile": ", ".join(_distinct(profile_names)),
            "method": ", ".join(_distinct(_method(d) for d in datasets)),
            "survey": _survey(datasets, fits, crs_authid, crs_description),
            "title": plate.title,
            "plate": f"Plate {plate.number}"}
