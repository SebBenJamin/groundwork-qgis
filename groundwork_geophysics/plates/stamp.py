"""The plate stamp: an engineering title block ruled into cells, made of ordinary layout items.

``stamp_texts`` composes the cells the plate fills (profile, method, survey details, title,
plate number); only what is known is printed, nothing is invented."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.dataset_info import dataset_info
from ..core.dataset_types import method_label, method_of, station_words

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
    return typed or method_label(d.kind)


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
    word = station_words(method_of([d.kind for d in datasets]))[0]
    first = " · ".join(x for x in (f"Acquired {shared('date')}" if shared("date") else "",
                                    f"{word} spacing {shared('spacing')}"
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
    frame with an existing profile. Method and survey details come from the models when the
    plate shows any (a misfit or measured data beside its model is not another survey)."""
    surveys = [d for d in datasets if d.kind.endswith("_model")] or datasets
    return {"profile": ", ".join(_distinct(profile_names)),
            "method": ", ".join(_distinct(_method(d) for d in surveys)),
            "survey": _survey(surveys, fits, crs_authid, crs_description),
            "title": plate.title,
            "plate": f"Plate {plate.number}"}


# -- the grid -----------------------------------------------------------------------------------
@dataclass(frozen=True)
class Cell:
    key: str
    text: tuple[float, float, float, float]     # where caption and value go (area fractions)
    caption: str = ""
    size: float = 8.0                           # value font size (pt)
    box: tuple[float, float, float, float] | None = None    # ruled box; None: in another's
    box_key: str = ""                           # the cell whose box holds this one
    bold: bool = False

    def __post_init__(self):
        if not self.box_key:
            object.__setattr__(self, "box_key", self.key)


def _cell(key, rect, caption="", size=8.0, **kw):
    return Cell(key, rect, caption, size, box=kw.pop("box", rect), **kw)


CELLS = (
    _cell("project", (0, 0, .70, .15), "PROJECT", box=(0, 0, .70, .30)),
    Cell("client", (0, .15, .70, .15), "CLIENT", 8.0, box=None, box_key="project"),
    _cell("logo", (.70, 0, .30, .30)),
    _cell("profile", (0, .30, .40, .15), "PROFILE"),
    _cell("method", (.40, .30, .60, .15), "METHOD"),
    _cell("survey", (0, .45, 1, .25), "SURVEY DETAILS", 7.0),
    _cell("date", (0, .70, .22, .15), "DATE"),
    _cell("author", (.22, .70, .20, .15), "DRAWN"),
    _cell("checked", (.42, .70, .20, .15), "CHECKED"),
    _cell("revision", (.62, .70, .12, .15), "REV."),
    _cell("job", (.74, .70, .26, .15), "JOB NO."),
    _cell("title", (0, .85, .72, .15), "", 9.0),
    _cell("plate", (.72, .85, .28, .15), "", 12.0, bold=True),
)
CAPTION_PT = 5.5
CAPTION_MM = 2.6
PAD_MM = 1.2
INNER_RULE_MM = 0.25
OUTER_RULE_MM = 0.5
BUILT_PROPERTY = "wb_stamp_built"


def item_rect(item) -> tuple[float, float, float, float]:
    """An item's position and size in layout millimetres."""
    layout = item.layout()
    pos = layout.convertToLayoutUnits(item.positionWithUnits())
    size = layout.convertToLayoutUnits(item.sizeWithUnits())
    return pos.x(), pos.y(), size.width(), size.height()


def _place(item, x, y, w, h) -> None:
    from qgis.core import QgsLayoutPoint, QgsLayoutSize, QgsUnitTypes
    mm = QgsUnitTypes.LayoutMillimeters
    item.attemptMove(QgsLayoutPoint(x, y, mm))
    item.attemptResize(QgsLayoutSize(w, h, mm))


def _outline(symbol, width: float):
    """``symbol`` with no fill and its stroke ``width`` mm wide (its colour kept)."""
    from qgis.core import QgsUnitTypes
    from qgis.PyQt.QtCore import Qt
    symbol = symbol.clone()
    for layer in symbol.symbolLayers():
        if hasattr(layer, "setBrushStyle"):
            layer.setBrushStyle(Qt.BrushStyle.NoBrush)
        if hasattr(layer, "setStrokeWidth"):
            layer.setStrokeWidth(width)
            layer.setStrokeWidthUnit(QgsUnitTypes.RenderMillimeters)
    return symbol


def _label(layout, item_id: str, size: float, bold: bool = False, family: str = ""):
    from qgis.core import QgsLayoutItemLabel

    from .build import WRITTEN
    item = QgsLayoutItemLabel(layout)
    item.setId(item_id)
    item.setText("")
    item.setCustomProperty(WRITTEN, "")
    item.setMarginX(0.0)
    item.setMarginY(0.0)
    fmt = item.textFormat()
    if family:
        font = fmt.font()
        font.setFamily(family)
        fmt.setFont(font)
    fmt.setSize(size)
    if bold:
        fmt.setForcedBold(True)
    item.setTextFormat(fmt)
    layout.addLayoutItem(item)
    return item


def build_stamp(layout, area_item) -> None:
    """Build the stamp's items into ``area_item`` once (a layout that has it keeps it as the
    user left it: cells moved, restyled or deleted are not rebuilt)."""
    from qgis.core import (QgsLayoutItem, QgsLayoutItemPicture, QgsLayoutItemShape,
                           QgsLayoutObject, QgsProperty)
    if layout.customProperty(BUILT_PROPERTY) in (True, "true", "1", 1):
        return
    ax, ay, aw, ah = item_rect(area_item)

    def mm(rect):
        fx, fy, fw, fh = rect
        return ax + fx * aw, ay + fy * ah, fw * aw, fh * ah

    from qgis.core import QgsLayoutItemLabel
    notes = layout.itemById("wb_field_notes")         # the template's own text font
    family = notes.textFormat().font().family() if isinstance(notes, QgsLayoutItemLabel) else ""
    has_symbol = hasattr(area_item, "symbol") and area_item.symbol() is not None
    if has_symbol:
        area_item.setSymbol(_outline(area_item.symbol(), OUTER_RULE_MM))
    for cell in CELLS:
        if cell.box is not None:
            box = QgsLayoutItemShape(layout)
            box.setShapeType(QgsLayoutItemShape.Shape.Rectangle)
            box.setId(f"wb_stamp_{cell.key}_box")
            if has_symbol:
                box.setSymbol(_outline(area_item.symbol(), INNER_RULE_MM))
            layout.addLayoutItem(box)
            _place(box, *mm(cell.box))
        x, y, w, h = mm(cell.text)
        x, y, w, h = x + PAD_MM, y + PAD_MM, max(w - 2 * PAD_MM, 1.0), max(h - 2 * PAD_MM, 1.0)
        if cell.key == "logo":
            pic = QgsLayoutItemPicture(layout)
            pic.setId("wb_stamp_logo")
            pic.setResizeMode(QgsLayoutItemPicture.ResizeMode.Zoom)
            pic.setPictureAnchor(QgsLayoutItem.ReferencePoint.Middle)
            pic.dataDefinedProperties().setProperty(
                QgsLayoutObject.DataDefinedProperty.PictureSource,
                QgsProperty.fromExpression(LOGO_EXPRESSION))
            layout.addLayoutItem(pic)
            _place(pic, x, y, w, h)
            pic.refreshDataDefinedProperty(QgsLayoutObject.DataDefinedProperty.PictureSource)
            continue
        if cell.caption:
            cap = _label(layout, f"wb_stamp_{cell.key}_caption", CAPTION_PT, family=family)
            cap.setText(cell.caption)
            _place(cap, x, y, w, min(CAPTION_MM, h))
            y, h = y + CAPTION_MM, max(h - CAPTION_MM, 1.0)
        _place(_label(layout, f"wb_stamp_{cell.key}", cell.size, cell.bold, family), x, y, w, h)
    layout.setCustomProperty(BUILT_PROPERTY, True)
