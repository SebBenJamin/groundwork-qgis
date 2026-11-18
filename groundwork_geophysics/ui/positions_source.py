"""Station positions for the placement widget, read from a text table or a point layer and
reprojected into the workbench store's CRS. Nothing is written into the user's files or
layers. Raises ValueError with a message for the user."""
from __future__ import annotations

import numpy as np
from qgis.core import (NULL, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
                       QgsCsException, QgsGeometry, QgsPointXY, QgsWkbTypes)

from ..core.placement import Positions
from ..core.roles import PositionColumns, looks_like_degrees
from ..readers.texttable import TextTable, select_rows


def to_store(crs: QgsCoordinateReferenceSystem, store_crs: str, project):
    """The transform from ``crs`` into the store's CRS, or None when none is needed."""
    dst = QgsCoordinateReferenceSystem(store_crs)
    if not crs.isValid() or crs == dst:
        return None
    return QgsCoordinateTransform(crs, dst, project)


def reprojection_error(crs: QgsCoordinateReferenceSystem, store_crs: str) -> ValueError:
    """The message when coordinates do not fit the CRS they are declared in."""
    name = crs.authid() or crs.description() or "their CRS"
    return ValueError(f"The coordinates cannot be reprojected from {name} to {store_crs}: "
                      "check their CRS")


def _transform_xy(xy: np.ndarray, crs: QgsCoordinateReferenceSystem, store_crs: str,
                  project) -> np.ndarray:
    tr = to_store(crs, store_crs, project)
    if tr is None:
        return xy
    try:
        out = [tr.transform(QgsPointXY(float(x), float(y))) for x, y in xy]
    except QgsCsException:
        raise reprojection_error(crs, store_crs) from None
    out = np.array([(p.x(), p.y()) for p in out], dtype=float).reshape(-1, 2)
    if not np.isfinite(out).all():
        raise reprojection_error(crs, store_crs)
    return out


def _check_degrees(xy: np.ndarray, crs: QgsCoordinateReferenceSystem) -> None:
    if not crs.isGeographic() and looks_like_degrees(xy):
        raise ValueError("The coordinates look like longitude/latitude in degrees: choose "
                         "their CRS (for example EPSG:4326).")


def _whole(values: np.ndarray) -> np.ndarray:
    if not np.all(np.isfinite(values)) or np.any(values != np.round(values)):
        raise ValueError("Station numbers must be whole numbers.")
    return values.astype(int)


def crs_of(text: str, store_crs: str) -> QgsCoordinateReferenceSystem:
    """The CRS a ``PositionColumns.crs`` names; "" is the store's CRS."""
    return QgsCoordinateReferenceSystem(text or store_crs)


def xy_to_store(xy: np.ndarray, crs_text: str, store_crs: str, project) -> np.ndarray:
    """Map coordinates (n, 2) in the CRS ``crs_text`` names ("" = the store's), reprojected
    into the store's CRS. ValueError when the CRS is unknown, the coordinates look like
    degrees in a projected CRS, or they cannot be reprojected."""
    crs = crs_of(crs_text, store_crs)
    if not crs.isValid():
        raise ValueError("Choose the CRS of the coordinates.")
    xy = np.asarray(xy, dtype=float).reshape(-1, 2)
    _check_degrees(xy, crs)
    return _transform_xy(xy, crs, store_crs, project)


def positions_from_table(table: TextTable, cols: PositionColumns, store_crs: str,
                         project) -> tuple[Positions, int]:
    """(positions in the store CRS, rows skipped). A row is skipped when it has no number in
    the easting, northing or (when chosen) number column; a missing elevation or in-line
    distance is NaN. A text number column gives each row's point name (``names``) and no
    numbers: the caller reads the numbers from the names."""
    problems = cols.problems(table)
    if problems:
        raise ValueError("; ".join(problems))
    names = cols.names_number(table)
    required = [cols.easting, cols.northing] + \
        ([cols.number] if cols.number is not None and not names else [])
    _, skipped, _ = select_rows(table, required)
    ok = np.isfinite(np.column_stack([table.numeric(c) for c in required])).all(axis=1)

    def column(c):
        return table.numeric(c)[ok] if c is not None else np.full(int(ok.sum()), np.nan)

    xy = np.column_stack([column(cols.easting), column(cols.northing)])
    crs = crs_of(cols.crs, store_crs)
    if not crs.isValid():
        raise ValueError("Choose the CRS of the coordinates.")
    _check_degrees(xy, crs)
    xy = _transform_xy(xy, crs, store_crs, project)
    inline = column(cols.inline) if cols.inline is not None else None
    xyz = np.column_stack([xy, column(cols.elevation)])
    if names:
        cells = [row[cols.number].strip() for row, keep in zip(table.cells, ok) if keep]
        return Positions(xyz, None, inline, cells), skipped
    numbers = _whole(column(cols.number)) if cols.number is not None else None
    return Positions(xyz, numbers, inline), skipped


def _value(feature, field: str | None) -> float:
    if not field:
        return float("nan")
    v = feature[field]
    try:
        return float(v)
    except (TypeError, ValueError):     # NULL or text
        return float("nan")


def positions_from_layer(layer, number_field: str | None, inline_field: str | None,
                         elevation_field: str | None, selected_only: bool, store_crs: str,
                         project) -> Positions:
    """Positions from a point layer's (selected) features, in the store CRS. Without an
    elevation field the points' own Z is used when they have one. A text number field gives
    each feature's point name (``names``, "" for NULL) and no numbers."""
    if layer is None:
        raise ValueError("Choose a point layer.")
    index = layer.fields().indexOf(number_field) if number_field else -1
    names_field = index >= 0 and not layer.fields().at(index).isNumeric()
    names: list[str] = []
    # selectedFeatures() comes in no fixed order: read them in the layer's own (feature id)
    # order, so "the later point" of two with the same number is always the same one
    feats = sorted(layer.selectedFeatures(), key=lambda f: f.id()) if selected_only \
        else list(layer.getFeatures())
    if selected_only and not feats:
        raise ValueError(f"Select the points in layer “{layer.name()}”, or use all of its "
                         "features.")
    xy, z, numbers, inline = [], [], [], []
    for f in feats:
        geom = QgsGeometry(f.geometry())
        if geom.isNull() or geom.type() != QgsWkbTypes.GeometryType.PointGeometry:
            continue
        point = geom.constGet()
        if geom.isMultipart():
            if geom.constGet().numGeometries() != 1:
                raise ValueError(f"Feature {f.id()} of layer “{layer.name()}” has several "
                                 "points; use single points.")
            point = point.geometryN(0)
        xy.append((point.x(), point.y()))
        height = _value(f, elevation_field)
        if not elevation_field and point.is3D():
            height = point.z()
        z.append(height)
        if names_field:
            v = f[number_field]
            names.append("" if v is None or v == NULL else str(v).strip())
        else:
            numbers.append(_value(f, number_field))
        inline.append(_value(f, inline_field))
    if len(xy) < 2:
        raise ValueError(f"Layer “{layer.name()}” needs at least two points.")
    xy = np.array(xy, dtype=float)
    _check_degrees(xy, layer.crs())
    xy = _transform_xy(xy, layer.crs(), store_crs, project)
    return Positions(np.column_stack([xy, np.array(z, dtype=float)]),
                     _whole(np.array(numbers)) if number_field and not names_field else None,
                     np.array(inline, dtype=float) if inline_field else None,
                     names if names_field else None)


def selected_line(layer, store_crs: str, project) -> np.ndarray:
    """The vertices of the one selected feature of a line layer, in the store CRS."""
    if layer is None or layer.selectedFeatureCount() != 1:
        raise ValueError("Select exactly one line feature in the active line layer")
    geom = QgsGeometry(layer.selectedFeatures()[0].geometry())
    tr = to_store(layer.crs(), store_crs, project)
    if tr is not None:
        try:
            geom.transform(tr)
        except QgsCsException:
            raise reprojection_error(layer.crs(), store_crs) from None
    if geom.isMultipart():
        parts = geom.asMultiPolyline()
        if len(parts) != 1:
            raise ValueError("The selected feature has several parts; select a single line")
        line = parts[0]
    else:
        line = geom.asPolyline()
    xy = np.array([(p.x(), p.y()) for p in line], dtype=float)
    if len(xy) < 2:
        raise ValueError("The selected line needs at least 2 vertices")
    if not np.isfinite(xy).all():               # a failed transform can also give NaN
        raise reprojection_error(layer.crs(), store_crs)
    return xy
