"""Misfit summary of a readings layer: histogram of the misfit per reading and the numbers.

A small non-modal window, closed until the user asks for it from the layer's right-click
menu ("Misfit summary…"); it follows the layer it was last opened for.
"""
from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QDialog, QLabel, QVBoxLayout

from ..section.data import layer_name


class MisfitPlot(FigureCanvasQTAgg):
    """Histogram of misfit % (calculated - measured) / measured; never pyplot."""

    def __init__(self, parent=None):
        figure = Figure(figsize=(4, 2.6), layout="constrained")
        super().__init__(figure)
        self.setParent(parent)
        self.ax = figure.add_subplot()
        self.counts = np.zeros(0)

    def show_misfit(self, misfit: np.ndarray) -> None:
        ax = self.ax
        ax.clear()
        m = misfit[np.isfinite(misfit)]
        if not m.size:
            self.counts = np.zeros(0)
            ax.set_axis_off()
            ax.text(0.5, 0.5, "No misfit", ha="center", va="center", transform=ax.transAxes)
            self.draw_idle()
            return
        ax.set_axis_on()
        lim = float(np.percentile(np.abs(m), 99)) or 1.0
        self.counts, _edges, _patches = ax.hist(np.clip(m, -lim, lim), bins=40,
                                                range=(-lim, lim))
        ax.axvline(0.0, linewidth=0.8, color=ax.xaxis.label.get_color())
        ax.set_xlabel("misfit (calculated − measured) / measured [%]")
        ax.set_ylabel("readings")
        self.draw_idle()


class MisfitSummary(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Misfit summary")
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setModal(False)
        self.numbers = QLabel()
        self.numbers.setWordWrap(True)
        self.numbers.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.plot = MisfitPlot(self)
        lay = QVBoxLayout(self)
        lay.addWidget(self.numbers)
        lay.addWidget(self.plot, 1)
        self.resize(460, 380)

    def show_layer(self, layer) -> None:
        if layer.mesh is None or layer.mesh.readings is None:
            return                              # a model or a trace section: no readings
        r = layer.mesh.readings
        mis = r.misfit_percent()
        n_ok = int(np.isfinite(mis).sum())
        lines = [f"<b>{layer_name(layer.dataset)}</b>",
                 f"{len(r)} readings, {n_ok} with a misfit"]
        rms = r.rms_percent()
        if rms is not None:
            lines.append(f"RMS misfit: {rms:.1f} %")
        chi2 = r.chi2()
        if chi2 is not None:
            lines.append(f"χ²: {chi2:.2f} (with the file's data errors, plain least squares; "
                         f"the inversion's own χ² may weight robustly)")
        if r.stated_rms:
            lines.append(f"RMS stated by the file: {r.stated_rms:.1f} %")
        opts = layer.dataset.reader_options or {}
        lines.append(f"Source: {layer.dataset.source_path}")
        if opts.get("response"):
            lines.append(f"Response: {opts['response']}")
        self.numbers.setText("<br>".join(lines))
        self.plot.show_misfit(mis)
