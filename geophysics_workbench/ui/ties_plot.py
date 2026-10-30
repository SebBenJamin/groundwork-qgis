"""Plot of the two model columns of one profile tie against elevation."""
from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.ticker import FuncFormatter

from ..core.ties import TieColumn
from ..section.readout import format_value, unit_label

COLORS = ("#1f77b4", "#d95f02")


def step_line(col: TieColumn) -> tuple[np.ndarray, np.ndarray]:
    """(value, elevation) of ``col`` as a step line, interval by interval, top to bottom."""
    x = np.repeat(col.values, 2)
    y = np.column_stack([col.z_top, col.z_bottom]).ravel()
    return x, y


class TiesPlot(FigureCanvasQTAgg):
    """Both columns' values against elevation, the shared depth range shaded; a log value
    axis for resistivity. Uses ``Figure`` directly, never pyplot."""

    def __init__(self, parent=None):
        figure = Figure(figsize=(4, 4), layout="constrained")
        super().__init__(figure)
        self.setParent(parent)
        self.ax = figure.add_subplot()
        self.show_row(None)

    def show_row(self, row) -> None:
        """Draw ``row`` (a ``ties_panel.TieRow``) or an empty hint for ``None``."""
        ax = self.ax
        ax.clear()
        ax.set_xscale("linear")
        if row is None:
            ax.set_axis_off()
            ax.text(0.5, 0.5, "Select a tie", ha="center", va="center", transform=ax.transAxes)
            self.draw_idle()
            return
        ax.set_axis_on()
        cols = [(row.a_name, row.col_a), (row.b_name, row.col_b)]
        cols = [(name, c) for name, c in cols if c is not None and c.values.size]
        for (name, c), color in zip(cols, COLORS):
            x, y = step_line(c)
            ax.plot(x, y, color=color, lw=1.6, label=f"{name}: {c.dataset_name}")
        quantity = cols[0][1].quantity if cols else ""
        unit = unit_label(cols[0][1].unit) if cols else ""
        if quantity == "resistivity":
            ax.set_xscale("log")
            plain = FuncFormatter(lambda v, _pos: format_value(v).removesuffix(".0"))
            ax.xaxis.set_major_formatter(plain)
            ax.xaxis.set_minor_formatter(plain)
        if row.mismatch is not None and row.mismatch.z_range is not None:
            ax.axhspan(*row.mismatch.z_range, color="0.5", alpha=0.15, lw=0)
        label = quantity.capitalize()
        ax.set_xlabel(f"{label} ({unit})" if unit else label)
        ax.set_ylabel("Elevation (m)")
        ax.set_title(row.title)
        if cols:
            ax.legend(fontsize="small", loc="best")
        ax.grid(True, alpha=0.3)
        self.draw_idle()
