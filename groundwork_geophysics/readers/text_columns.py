"""Free-text model reader: any text table, read with the columns the user assigned (no QGIS/Qt).

The table layout (``texttable.TableOptions``) and the column roles (``core.roles.ModelColumns``)
arrive as plain dicts, as stored with the dataset; an empty ``table`` dict means the guessed
layout. Rows without a number in every assigned column are skipped and counted. Never
detected: the user picks this reader when no fixed format fits.

Vertical meanings: "elevation" and "local" heights are used as they are; "depth" values must
be all >= 0 or all <= 0 and their magnitude is used. A file with map coordinates (easting,
northing) needs ``xy_to_distance(easting, northing) -> (chainage, offset[, beyond])`` to place
it on a profile line; ``beyond`` marks rows that lie past the line's ends (placed along its
first/last segment extended, counted as ``n_beyond``).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..core.roles import ModelColumns
from .base import (FILL_VALUE, Reader, ReaderResult, _no_position, chosen_z_kind, fill_mask,
                   mesh_from_points)
from .texttable import TableOptions, guess_options, read_numbers, read_table, select_rows


def _options(path: Path, table: dict, columns: dict) -> tuple[TableOptions, ModelColumns]:
    """The stored settings as objects; ValueError naming the file when they no longer load."""
    try:
        opts = TableOptions.from_dict(table) if table else guess_options(path)
        cols = ModelColumns.from_dict(columns)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{path.name}: the stored table settings cannot be used ({exc}); "
                         "add the file again") from None
    return opts, cols


def _rows(path: Path, table: dict, columns: dict, max_rows: int | None = None
          ) -> tuple[ModelColumns, np.ndarray, int, int | None]:
    """``(columns, usable rows of the used columns, skipped count, first skipped line)`` of
    the first ``max_rows`` data rows (all when None). ValueError when an assigned column is
    missing, unusable, or no row is usable."""
    opts, cols = _options(path, table, columns)
    required = cols.used()[:-1] if cols.coverage is not None else cols.used()
    # the whole file of a big model: numbers alone (no text per cell); a file with anything
    # else, or with a row to skip (its line is reported), is read as text
    tab = read_numbers(path, opts) if max_rows is None else None
    if tab is not None and not (all(0 <= i < tab.n_columns for i in cols.used()) and
                                np.isfinite(tab.values[:, required]).all()):
        tab = None
    if tab is None:
        tab = read_table(path, opts, max_rows=max_rows)
    for i in cols.used():
        if not 0 <= i < tab.n_columns:
            raise ValueError(f"{path.name}: column {i + 1} is not in the file any more")
    problems = cols.problems(tab)
    if problems:
        raise ValueError(f"{path.name}: " + "; ".join(problems))
    try:
        arr, skipped, first = select_rows(tab, required)
    except ValueError as exc:
        raise ValueError(f"{path.name}: {exc}") from None
    if cols.coverage is not None:            # optional: never drops a row, keeps -inf
        kept = np.isfinite(np.column_stack([tab.numeric(c) for c in required])).all(axis=1)
        arr = np.column_stack([arr, tab.raw(cols.coverage)[kept]])
    return cols, arr, skipped, first


def map_points(path, table: dict, columns: dict, max_rows: int | None = None) -> np.ndarray:
    """Easting and northing (n, 2) of the usable rows (of the first ``max_rows``), in the
    file's CRS."""
    cols, arr, _skipped, _first = _rows(Path(path), table, columns, max_rows)
    if cols.position != "map":
        raise ValueError(f"{Path(path).name}: the file has no map coordinates")
    return arr[_on_map(arr), :2]


def _on_map(arr: np.ndarray) -> np.ndarray:
    """True for rows of a map file whose easting and northing (columns 0, 1) are a position:
    not the -9999 fill, which exports write for cells past the surveyed line."""
    return ~(_no_position(arr[:, 0]) | _no_position(arr[:, 1]))


def _depth_magnitude(z: np.ndarray, name: str) -> np.ndarray:
    """|depth|, when the depths are all >= 0 or all <= 0 (-9999 fills are left alone)."""
    real = np.abs(z - FILL_VALUE) > 1e-6
    if np.any(z[real] > 0) and np.any(z[real] < 0):
        raise ValueError(f"{name}: the depth column has both positive and negative values; "
                         "if it is a height, choose Elevation or Local height")
    return np.where(real, np.abs(z), z)


class TextColumnsReader(Reader):
    name = "text_columns"
    label = "Text table (assign columns)"

    def sniff(self, path: Path) -> bool:
        return False

    def read(self, path: Path, table: dict, columns: dict, z_kind: str | None = None,
             xy_to_distance=None, max_rows: int | None = None) -> ReaderResult:
        """``max_rows``: read only the first data rows (a preview); never stored."""
        path = Path(path)
        cols, arr, skipped, first = _rows(path, table, columns, max_rows)
        k = 2 if cols.position == "map" else 1           # vertical, value, [coverage]
        z, v = arr[:, k], arr[:, k + 1]
        coverage = arr[:, k + 2] if cols.coverage is not None else None
        provenance = {"reader": self.name, "source_name": path.name, "n_rows": int(len(arr)),
                      "n_skipped": skipped, "first_skipped_line": first,
                      "position": cols.position}
        if cols.position == "map":
            if xy_to_distance is None:
                raise ValueError(f"{path.name}: a file with map coordinates needs a profile "
                                 "line to place it on")
            # a -9999 easting or northing is no position: such rows are left unplaced
            # (counted with the masked cells), never projected onto the line
            on_map = _on_map(arr)
            if not on_map.any():
                raise ValueError(f"{path.name}: no row has a map position (all eastings or "
                                 "northings are empty or -9999)")
            placed = xy_to_distance(arr[on_map, 0], arr[on_map, 1])
            x = np.full(len(arr), np.nan)
            x[on_map] = np.asarray(placed[0], dtype=float)
            offset = np.asarray(placed[1], dtype=float)
            beyond = np.asarray(placed[2], dtype=bool) if len(placed) > 2 else None
            provenance["n_unplaced"] = int((~on_map).sum())
            provenance["max_offset"] = float(np.abs(offset).max())
            provenance["n_beyond"] = 0 if beyond is None else int(beyond.sum())
        else:
            x = arr[:, 0]
        kind = chosen_z_kind({"z_kind": z_kind}, cols.vertical_kind)   # checked by problems()
        if kind == "depth":
            z = _depth_magnitude(z, path.name)
        if cols.log10:
            v = np.where(fill_mask(v), v, 10.0 ** v)
        mesh, n_masked, reconstruction = mesh_from_points(x, z, v, path.name, kind,
                                                          cols.quantity, cols.unit,
                                                          coverage=coverage)
        provenance["n_masked"] = n_masked
        provenance["reconstruction"] = reconstruction
        return ReaderResult(mesh, kind, provenance)
