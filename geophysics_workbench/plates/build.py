"""Build a report plate (an ordinary QGIS print layout) from a ``PlateSpec`` and refresh it.

The plate is found by its plate id (else its name, "Plate 3 – Transect 3") or made from its
template. The template's ``wb_section_area`` is divided among the frames, top to bottom; each
frame gets its colour bar(s) beside it (landscape) or below it (portrait) and a provenance
line. Running it again refreshes only the plugin's own content: sections, colour bars,
legends' content, the field-notes list, title fields, provenance lines. Positions, sizes and
styling of existing items stay as the user left them, and items the user added are never
touched (frames are laid out again only when the plate's frame count changed)."""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import numpy as np
from qgis.core import (Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsExpressionContextUtils, QgsLayerTreeUtils,
                       QgsLayoutItemElevationProfile, QgsLayoutItemLabel, QgsLayoutItemLegend,
                       QgsLayoutItemMap, QgsLayoutPoint, QgsLayoutSize, QgsLayoutUtils,
                       QgsLineSymbol, QgsMapLayerStyle, QgsMarkerLineSymbolLayer,
                       QgsMarkerSymbol, QgsPlotRenderContext, QgsPrintLayout, QgsReadWriteContext,
                       QgsRectangle, QgsRuleBasedRenderer, QgsUnitTypes)
from qgis.PyQt.QtCore import QSizeF, Qt
from qgis.PyQt.QtXml import QDomDocument

from ..core.dataset_info import provenance_line
from ..core.plates import stack_fit
from .items import ColourBarItem, register_items
from .sources import (FRAME_PROPERTY, attach_frame_sources, detach_frame_items, read_plates,
                      register_frame_sources, write_plates)

TEMPLATE_DIR = Path(__file__).parent / "templates"
TEMPLATES = {name: TEMPLATE_DIR / f"{name}.qpt"
             for name in ("A4_landscape", "A4_portrait", "A3_landscape", "A3_portrait")}
PLATE_PROPERTY = "wb_plate_id"
COUNT_PROPERTY = "wb_frame_count"
MM = QgsUnitTypes.LayoutMillimeters
GAP = 4.0               # mm between stacked frames
PROVENANCE_MM = 8.0     # height of a frame's provenance line
BAR_COLUMN = 0.18       # landscape: colour-bar column, share of the area width
BAR_ROW = 0.12          # portrait: colour-bar row, share of a frame slot's height
BAR_MAX_MM = 20.0       # a new vertical colour bar's width (the bar is 30 % of it) ...
BAR_MAX_LEN_MM = 80.0   # ... and its greatest length (horizontal bars: their width)
TOP_PAD = 0.08          # share of the depth range added above the data (labels, band)
DETAILS = (("project", "Project"), ("client", "Client"), ("job", "Job no."),
           ("date", "Date"), ("author", "Drawn"), ("revision", "Revision"))
INTERP_LEGEND_LAYERS = ("interp_polygons_3d", "interp_lines_3d", "interp_points_3d")


def plate_name(plate) -> str:
    return f"Plate {plate.number} – {plate.title}"


def set_plate_details(project, /, **values) -> None:
    """Project-wide title block values (project, client, job, date, author, revision), kept
    as the project variables ``wb_*`` the title labels read."""
    for key, value in values.items():
        if key in dict(DETAILS):
            QgsExpressionContextUtils.setProjectVariable(project, f"wb_{key}", str(value))


def plate_details(project) -> dict:
    scope = QgsExpressionContextUtils.projectScope(project)
    return {key: str(scope.variable(f"wb_{key}") or "") for key, _ in DETAILS}


# -- the layout ------------------------------------------------------------------------------
def find_plate_layout(project, plate):
    manager = project.layoutManager()
    for layout in manager.printLayouts():
        if layout.customProperty(PLATE_PROPERTY) == plate.plate_id:
            return layout
    return manager.layoutByName(plate_name(plate))


def _new_layout(project, plate):
    layout = QgsPrintLayout(project)
    path = TEMPLATES.get(plate.template) or Path(plate.template)
    doc = QDomDocument()
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        text = ""
    if not text or not doc.setContent(text):
        layout.initializeDefaults()             # an unreadable template: an empty A4 page
    else:
        layout.loadFromTemplate(doc, QgsReadWriteContext())
    return layout


def _rect(item) -> tuple[float, float, float, float]:
    layout = item.layout()
    pos = layout.convertToLayoutUnits(item.positionWithUnits())
    size = layout.convertToLayoutUnits(item.sizeWithUnits())
    return pos.x(), pos.y(), size.width(), size.height()


def _place(item, x, y, w, h) -> None:
    item.attemptMove(QgsLayoutPoint(x, y, MM))
    item.attemptResize(QgsLayoutSize(w, h, MM))


def _remove(layout, item_id: str) -> None:
    item = layout.itemById(item_id)
    if item is not None:
        layout.removeLayoutItem(item)


def _portrait(layout) -> bool:
    page = layout.pageCollection().page(0)
    if page is None:
        return False
    size = page.pageSize()
    return size.height() > size.width()


def _slots(area, count: int, portrait: bool, bars: list[int]) -> list[dict]:
    """Per frame: rects (x, y, w, h) of the frame, its provenance line and its bars."""
    x, y, w, h = area
    slot_h = (h - GAP * (count - 1)) / max(count, 1)
    out = []
    for i in range(count):
        sy = y + i * (slot_h + GAP)
        k = max(bars[i], 1)
        if portrait:
            bar_h = slot_h * BAR_ROW
            frame_h = slot_h - bar_h - PROVENANCE_MM
            frame = (x, sy, w, frame_h)
            bar_rects = [(x + j * w / k, sy + frame_h, min(w / k, BAR_MAX_LEN_MM), bar_h)
                         for j in range(k)]
            prov = (x, sy + frame_h + bar_h, w, PROVENANCE_MM)
        else:
            bar_w = w * BAR_COLUMN
            frame_w = w - bar_w - GAP
            frame_h = slot_h - PROVENANCE_MM
            frame = (x, sy, frame_w, frame_h)
            bar_rects = [(x + frame_w + GAP, sy + j * frame_h / k, min(bar_w, BAR_MAX_MM),
                          min(frame_h / k, BAR_MAX_LEN_MM)) for j in range(k)]
            prov = (x, sy + frame_h, frame_w, PROVENANCE_MM)
        out.append({"frame": frame, "bars": bar_rects, "provenance": prov})
    return out


# -- frames and fit to page ------------------------------------------------------------------
def snapshot_extent(snap, length: float) -> tuple[float, float, float, float]:
    """(s0, s1, z0, z1) of a frame's data, like the panel's "Zoom full"."""
    from ..section.context_render import context_z_values
    s, z = [0.0, float(length)], []
    for layer in snap.layers:
        if layer.mesh is not None:
            s0, s1, z0, z1 = layer.mesh.bounds()
            s += [s0, s1]
            z += [z0, z1]
    if snap.topo is not None and len(snap.topo[0]):
        s += [float(np.nanmin(snap.topo[0])), float(np.nanmax(snap.topo[0]))]
        z += [float(np.nanmin(snap.topo[1])), float(np.nanmax(snap.topo[1]))]
    if snap.station_heights is not None and len(snap.station_heights):
        z += [float(v) for v in snap.station_heights if np.isfinite(v)]
    if snap.context is not None:
        z += context_z_values(snap.context, snap.topo)
    z = [v for v in z if np.isfinite(v)] or [-10.0, 0.0]
    z0, z1 = min(z), max(z)
    if z1 - z0 < 1.0:
        z0, z1 = z0 - 0.5, z1 + 0.5
    return min(s), max(s), z0, z1 + (z1 - z0) * TOP_PAD


def _interior_mm(item) -> tuple[float, float]:
    """Width and height (mm) of the frame's plot area inside its axes and labels."""
    layout = item.layout()
    rc = QgsLayoutUtils.createRenderContextForLayout(layout, None)
    px = rc.scaleFactor()
    plot = item.plot()
    plot.setSize(QSizeF(item.rect().width() * px, item.rect().height() * px))
    area = plot.interiorPlotArea(rc, QgsPlotRenderContext())
    return max(area.width() / px, 1.0), max(area.height() / px, 1.0)


def _optimise_intervals(item) -> None:
    layout = item.layout()
    rc = QgsLayoutUtils.createRenderContextForLayout(layout, None)
    px = rc.scaleFactor()
    plot = item.plot()
    plot.setSize(QSizeF(item.rect().width() * px, item.rect().height() * px))
    plot.calculateOptimisedIntervals(rc, QgsPlotRenderContext())


def fit_frame(item, scale: int, ve: float, s0: float, s1: float, z0: float, z1: float) -> None:
    """Set the plot range so the plot area shows 1:``scale`` horizontally and ``ve`` times
    that vertically, centred on the data (axis labels change the plot area: settle twice)."""
    plot = item.plot()
    for _ in range(3):
        w_mm, h_mm = _interior_mm(item)
        span_s = w_mm * scale / 1000.0
        span_z = h_mm * scale / (1000.0 * ve)
        sc, zc = (s0 + s1) / 2.0, (z0 + z1) / 2.0
        plot.setXMinimum(sc - span_s / 2.0)
        plot.setXMaximum(sc + span_s / 2.0)
        plot.setYMinimum(zc - span_z / 2.0)
        plot.setYMaximum(zc + span_z / 2.0)
        _optimise_intervals(item)


def frame_scale_and_ve(item) -> tuple[int, float]:
    """The scale denominator and VE a frame item shows (from its plot range and area)."""
    plot = item.plot()
    w_mm, h_mm = _interior_mm(item)
    scale = (plot.xMaximum() - plot.xMinimum()) * 1000.0 / w_mm
    zscale = (plot.yMaximum() - plot.yMinimum()) * 1000.0 / h_mm
    return round(scale), round(scale / zscale, 2) if zscale else 0.0


def _new_frame(layout, item_id: str):
    item = QgsLayoutItemElevationProfile(layout)
    item.setId(item_id)
    # no item frame: QGIS 4.2 draws it at the wrong size in exports; the plot's own chart
    # border frames the section
    item.setDistanceUnit(Qgis.DistanceUnit.Meters)
    for axis in (item.plot().xAxis(), item.plot().yAxis()):
        axis.setLabelSuffix(" m")
        axis.setLabelSuffixPlacement(Qgis.PlotAxisSuffixPlacement.LastLabel)
    layout.addLayoutItem(item)
    return item


def _label(layout, item_id: str, size: float = 7.0):
    item = layout.itemById(item_id)
    if item is not None:
        return item, False
    item = QgsLayoutItemLabel(layout)
    item.setId(item_id)
    fmt = item.textFormat()
    fmt.setSize(size)
    item.setTextFormat(fmt)
    layout.addLayoutItem(item)
    return item, True


# -- text ------------------------------------------------------------------------------------
def _metres(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


def field_notes_text(store, plate, names: dict) -> str:
    """The shown notes of the plate's profiles (frames showing notes), in chainage order."""
    pids = []
    for f in plate.frames:
        if f.look.field_notes and f.profile_id in names and f.profile_id not in pids:
            pids.append(f.profile_id)
    lines = []
    for pid in pids:
        notes = sorted((n for n in store.field_notes(pid) if n.shown),
                       key=lambda n: (n.s_from, n.s_to if n.s_to is not None else n.s_from))
        for n in notes:
            where = f"{_metres(n.s_from)} m" if n.s_to is None else \
                f"{_metres(min(n.s_from, n.s_to))}–{_metres(max(n.s_from, n.s_to))} m"
            if n.stations:
                where += f" (electrodes {n.stations})"
            text = " ".join(n.text.split())
            head = f"{names[pid]} · " if len(pids) > 1 else ""
            lines.append(f"{head}{where} · {text}")
    return "\n".join(["Field notes"] + (lines or ["(none)"]))


def provenance_text(profile, datasets: list, scale: int, ve: float) -> str:
    heads = [provenance_line(profile.name, d) for d in datasets] or [profile.name]
    (x0, y0), (x1, y1) = profile.chainage.xy[0], profile.chainage.xy[-1]
    where = (f"1:{scale} · VE {ve:g}× · start E {x0:.0f} N {y0:.0f} · "
             f"end E {x1:.0f} N {y1:.0f}")
    return "\n".join([" / ".join(heads), where])


# -- legends, mini-map, title ------------------------------------------------------------------
def _update_interp_legend(layout, store, project, plate, versions: dict) -> None:
    from ..ui.interp_layers import interp_layers
    legend = layout.itemById("wb_legend_interp")
    if not isinstance(legend, QgsLayoutItemLegend):
        return
    legend.setSyncMode(Qgis.LegendSyncMode.Manual)
    legend.setLegendFilterByMapEnabled(False)
    minimap = layout.itemById("wb_minimap")
    if legend.linkedMap() is None and isinstance(minimap, QgsLayoutItemMap):
        legend.setLinkedMap(minimap)            # QGIS applies expression filters via a map
    root = legend.model().rootGroup()
    root.removeAllChildren()
    layers = interp_layers(store, project)
    pairs = sorted({(pid, v) for pid, v in versions.items() if v})
    expr = " OR ".join(f"(\"profile_id\" = '{pid}' AND \"version_id\" = '{v}')"
                       for pid, v in pairs) or "FALSE"
    for name in INTERP_LEGEND_LAYERS:
        layer = layers.get(name)
        if layer is None:
            continue
        node = root.addLayer(layer)
        QgsLayerTreeUtils.setLegendFilterByExpression(node, expr)
    legend.updateLegend()


def _highlight_style(layer, profile_ids: list[str]) -> str:
    """The workbench profiles layer styled for the mini-map: the plate's profiles strong
    (start dot, end triangle), the others faint."""
    ids = ", ".join(f"'{p}'" for p in profile_ids) or "''"
    strong = QgsLineSymbol.createSimple({"color": "200,30,30", "width": "0.9"})
    for placement, shape in ((Qgis.MarkerLinePlacement.FirstVertex, "circle"),
                             (Qgis.MarkerLinePlacement.LastVertex, "filled_arrowhead")):
        marker = QgsMarkerLineSymbolLayer()
        marker.setPlacements(placement)
        marker.setSubSymbol(QgsMarkerSymbol.createSimple(
            {"name": shape, "color": "200,30,30", "outline_style": "no", "size": "2.2"}))
        strong.appendSymbolLayer(marker)
    faint = QgsLineSymbol.createSimple({"color": "120,120,120", "width": "0.35"})
    faint.setOpacity(0.6)
    root = QgsRuleBasedRenderer.Rule(None)
    root.appendChild(QgsRuleBasedRenderer.Rule(strong, 0, 0, f"\"id\" IN ({ids})", "This plate"))
    root.appendChild(QgsRuleBasedRenderer.Rule(faint, 0, 0, "ELSE", "Other profiles"))
    clone = layer.clone()
    clone.setRenderer(QgsRuleBasedRenderer(root))
    style = QgsMapLayerStyle()
    style.readFromLayer(clone)
    return style.xmlData()


def _update_minimap(layout, store, project, profiles: list) -> None:
    from ..ui.project_actions import store_layers
    m = layout.itemById("wb_minimap")
    if not isinstance(m, QgsLayoutItemMap):
        return
    for item_id in ("wb_north", "wb_map_scalebar"):
        item = layout.itemById(item_id)
        if item is not None and hasattr(item, "setLinkedMap") and item.linkedMap() is None:
            item.setLinkedMap(m)
    layer = store_layers(store, project).get("profiles")
    if layer is not None and profiles:
        overrides = dict(m.layerStyleOverrides())
        overrides[layer.id()] = _highlight_style(layer, [p.id for p in profiles])
        m.setKeepLayerStyles(True)
        m.setLayerStyleOverrides(overrides)
    if not profiles:
        return
    xy = np.vstack([p.chainage.xy for p in profiles])
    rect = QgsRectangle(float(xy[:, 0].min()), float(xy[:, 1].min()),
                        float(xy[:, 0].max()), float(xy[:, 1].max()))
    pad = max(rect.width(), rect.height(), 100.0) * 0.15
    rect.grow(pad)
    src, dst = QgsCoordinateReferenceSystem(store.crs_authid), m.crs()
    if src.isValid() and dst.isValid() and src != dst:
        try:
            rect = QgsCoordinateTransform(src, dst, project).transformBoundingBox(rect)
        except Exception:                       # QgsCsException: keep the store extent
            pass
    m.zoomToExtent(rect)
    bar = layout.itemById("wb_map_scalebar")
    invalid = bar is not None and hasattr(bar, "unitsPerSegment") and \
        not (bar.unitsPerSegment() > 0)                 # nan: sized before the map had an extent
    if invalid:
        bar.setSegmentSizeMode(Qgis.ScaleBarSegmentSizeMode.FitWidth)
        bar.setMinimumBarWidth(15.0)
        bar.setMaximumBarWidth(min(45.0, max(m.rect().width() * 0.5, 16.0)))
        bar.applyDefaultSize(Qgis.DistanceUnit.Meters)
        bar.update()


def _update_title(layout, plate, crs_authid: str) -> None:
    for key, caption in DETAILS:
        label = layout.itemById(f"wb_title_{key}")
        if isinstance(label, QgsLayoutItemLabel) and f"@wb_{key}" not in label.text():
            label.setText(f"{caption}: [% @wb_{key} %]")
    label = layout.itemById("wb_title_plate")
    if isinstance(label, QgsLayoutItemLabel):
        label.setText(plate_name(plate))
    label = layout.itemById("wb_crs")
    if isinstance(label, QgsLayoutItemLabel):
        crs = QgsCoordinateReferenceSystem(crs_authid)
        label.setText(f"Coordinate system: {crs.authid()} {crs.description()}".strip())


# -- the builder -------------------------------------------------------------------------------
def _concrete_scales(frame, snap) -> None:
    """A model shown with the panel's automatic scale gets that scale written into the
    plate, so restyling the panel later never changes a delivered plate."""
    by_id = {la.dataset.id: la for la in snap.layers}
    for m in frame.look.models:
        la = by_id.get(m.dataset_id)
        if m.scale is None and la is not None and la.style.scale is not None:
            m.scale = asdict(la.style.scale)


def create_or_update_plate(project, store, provider, plate) -> QgsPrintLayout:
    register_items()
    profiles = {p.id: p for p in store.profiles()}
    plates = [p for p in read_plates(project) if p.plate_id != plate.plate_id]
    detach_frame_items(project)                     # before their sources are replaced

    layout = find_plate_layout(project, plate)
    if layout is None:
        layout = _new_layout(project, plate)
        layout.setName(plate_name(plate))
        project.layoutManager().addLayout(layout)
    elif layout.name() != plate_name(plate):
        layout.setName(plate_name(plate))
    layout.setCustomProperty(PLATE_PROPERTY, plate.plate_id)

    # data per frame: snapshot (scales made concrete), extent, the models with a colour bar
    snaps, extents, shown = {}, {}, []
    for f in plate.frames:
        profile = profiles.get(f.profile_id)
        models = []
        if profile is not None:
            snap = provider.snapshot(f.profile_id, look=f.look)
            _concrete_scales(f, snap)
            snaps[f.frame_id] = snap
            extents[f.frame_id] = snapshot_extent(snap, profile.chainage.length)
            have = {d.id: d for d in store.datasets(f.profile_id)}
            models = [have[m.dataset_id] for m in f.look.models
                      if m.visible and m.dataset_id in have]
        shown.append(models)
    write_plates(project, plates + [plate])

    count = len(plate.frames)
    relayout = layout.customProperty(COUNT_PROPERTY) not in (count, str(count))
    area_item = layout.itemById("wb_section_area")
    page = layout.pageCollection().page(0)
    if area_item is not None:
        area = _rect(area_item)
    else:                                           # a user's template without an area
        size = page.pageSize() if page is not None else QSizeF(297, 210)
        area = (10.0, 10.0, size.width() - 20.0, size.height() * 0.6)
    slots = _slots(area, count, _portrait(layout), [len(m) for m in shown])

    frame_items = []
    for n, (f, models, slot) in enumerate(zip(plate.frames, shown, slots), start=1):
        item = layout.itemById(f"wb_frame_{n}")
        fresh = not isinstance(item, QgsLayoutItemElevationProfile)
        if fresh:
            if item is not None:
                layout.removeLayoutItem(item)
            item = _new_frame(layout, f"wb_frame_{n}")
        if fresh or relayout:
            _place(item, *slot["frame"])
        item.setCustomProperty(FRAME_PROPERTY, f.frame_id)
        frame_items.append(item)
        _update_bars(layout, n, f, models, slot, relayout)
        profile = profiles.get(f.profile_id)
        placeholder = f"wb_placeholder_{n}"
        if profile is None:
            label, new = _label(layout, placeholder, 10.0)
            if new or relayout:
                _place(label, *_inset(slot["frame"]))
            label.setText(f"Profile not found: {f.profile_id} – it is no longer in the "
                          f"workbench. Remove this frame or choose another profile.")
        else:
            _remove(layout, placeholder)
        prov, new = _label(layout, f"wb_provenance_{n}", 6.5)
        if new or relayout:
            _place(prov, *slot["provenance"])
        if profile is None:
            prov.setText(f"Profile {f.profile_id} not found")
    for n in range(count + 1, _highest(layout, "wb_frame_") + 1):     # frames removed
        for item_id in [f"wb_frame_{n}", f"wb_provenance_{n}", f"wb_placeholder_{n}"] + \
                [i.id() for i in layout.items() if hasattr(i, "id") and
                 i.id().startswith(f"wb_colourbar_{n}_")]:
            _remove(layout, item_id)
    layout.setCustomProperty(COUNT_PROPERTY, count)

    # fit to page: frames of one profile share scale, VE and range
    sizes = [_interior_mm(item) for item in frame_items]
    fits = stack_fit(plate.frames, extents, sizes)
    for n, (f, item, fit, models) in enumerate(zip(plate.frames, frame_items, fits, shown),
                                               start=1):
        profile = profiles.get(f.profile_id)
        if profile is None:
            continue
        scale, ve, s0, s1 = fit
        ext = extents[f.frame_id]
        group = [extents[g.frame_id] for g in plate.frames
                 if g.profile_id == f.profile_id and g.frame_id in extents]
        z0, z1 = min(e[2] for e in group), max(e[3] for e in group)
        fit_frame(item, scale, ve, s0 if s0 != s1 else ext[0], s1 if s0 != s1 else ext[1],
                  z0, z1)
        layout.itemById(f"wb_provenance_{n}").setText(
            provenance_text(profile, models, scale, ve))

    # content of the template's own items
    names = {pid: p.name for pid, p in profiles.items()}
    on_plate = [profiles[f.profile_id] for f in plate.frames if f.profile_id in profiles]
    on_plate = list({p.id: p for p in on_plate}.values())
    versions = {}
    for f in plate.frames:
        if f.profile_id in profiles:
            versions[f.profile_id] = f.look.interp_version or provider._latest_version()
    _update_interp_legend(layout, store, project, plate, versions)
    bl = layout.itemById("wb_legend_boreholes")
    if bl is not None and hasattr(bl, "frame_ids"):
        bl.frame_ids = [f.frame_id for f in plate.frames if f.look.boreholes]
        bl.refresh()
    notes = layout.itemById("wb_field_notes")
    if isinstance(notes, QgsLayoutItemLabel):
        notes.setText(field_notes_text(store, plate, names))
    _update_minimap(layout, store, project, on_plate)
    _update_title(layout, plate, store.crs_authid)

    sources = register_frame_sources(provider, read_plates(project))
    attach_frame_sources(project, store, sources)
    layout.refresh()
    return layout


def _inset(rect, margin=6.0):
    x, y, w, h = rect
    return x + margin, y + h / 2 - 8, max(w - 2 * margin, 10.0), 16.0


def _highest(layout, prefix: str) -> int:
    best = 0
    for item in layout.items():
        item_id = item.id() if hasattr(item, "id") else ""
        if item_id.startswith(prefix) and item_id[len(prefix):].isdigit():
            best = max(best, int(item_id[len(prefix):]))
    return best


def _update_bars(layout, n: int, frame, models: list, slot: dict, relayout: bool) -> None:
    from ..section.readout import unit_label
    portrait = slot["bars"] and slot["bars"][0][2] > slot["bars"][0][3]
    for k, d in enumerate(models, start=1):
        item_id = f"wb_colourbar_{n}_{k}"
        bar = layout.itemById(item_id)
        fresh = not isinstance(bar, ColourBarItem)
        if fresh:
            if bar is not None:
                layout.removeLayoutItem(bar)
            bar = ColourBarItem(layout)
            bar.setId(item_id)
            bar.settings.setOrientation(Qt.Orientation.Horizontal if portrait
                                        else Qt.Orientation.Vertical)
            layout.addLayoutItem(bar)
        if fresh or bar.dataset_id != d.id:
            bar.title = (d.quantity or "").capitalize()
            bar.unit = unit_label(d.unit)
        if fresh or relayout:
            _place(bar, *slot["bars"][k - 1])
        bar.frame_id, bar.dataset_id = frame.frame_id, d.id
        bar.refresh()
    k = len(models) + 1
    while layout.itemById(f"wb_colourbar_{n}_{k}") is not None:
        _remove(layout, f"wb_colourbar_{n}_{k}")
        k += 1


__all__ = ["TEMPLATES", "create_or_update_plate", "frame_scale_and_ve", "plate_details",
           "plate_name", "set_plate_details"]
