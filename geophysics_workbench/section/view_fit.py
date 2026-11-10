"""View fitting for the section canvas: show the whole section at the chosen vertical
exaggeration, and keep re-fitting (after generation, resize, exaggeration changes) until
the user navigates."""
from __future__ import annotations

import weakref
from typing import Callable

from qgis.PyQt.QtCore import QTimer

PAD = 0.06                      # fraction of the data extent added on each side by zoom_full
MAX_HEADROOM = 0.6              # of the plot height at most goes to the room above the data
AUTO_MIN, AUTO_MAX = 0.5, 50.0  # the range "Auto" chooses the vertical exaggeration from

Extent = tuple[float, float, float, float]


class ViewFitter:
    """Fits ``canvas`` to ``extent()`` (``(s0, s1, z0, z1)``, or ``None`` when nothing is
    open) at the exaggeration of ``ve_spin``, keeping ``headroom()`` pixels free above it
    (for the geology band and the context labels, a fixed pixel height however tall the
    plot is); ``on_fitted`` runs after every fit.

    Its timers are children of ``parent`` (the dock), and the dock forwards the canvas'
    active job count to ``jobs_changed``. The two callbacks are held weakly: a dock <-> fitter
    reference cycle would let the garbage collector clear the dock's attributes while Qt
    still delivers events to it."""

    def __init__(self, canvas, ve_spin, extent: Callable[[], Extent | None],
                 on_fitted: Callable[[], None], parent,
                 headroom: Callable[[], float] | None = None):
        self.canvas, self.ve_spin = canvas, ve_spin
        self._extent_ref = weakref.WeakMethod(extent)
        self._fitted_ref = weakref.WeakMethod(on_fitted)
        self._headroom_ref = None if headroom is None else weakref.WeakMethod(headroom)
        self.pending = False                    # re-fit the view until the user navigates
        self.fit_view = None                    # visible range set by the last zoom_full
        self.jobs = 0
        self._refit_timer = QTimer(parent)
        self._refit_timer.setSingleShot(True)
        self._refit_timer.timeout.connect(self._refit)
        self._restore_timer = QTimer(parent)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._restore_fit)

    def _extent(self) -> Extent | None:
        extent = self._extent_ref()
        return None if extent is None else extent()

    def _headroom(self) -> float:
        headroom = None if self._headroom_ref is None else self._headroom_ref()
        return 0.0 if headroom is None else max(0.0, float(headroom()))

    def _on_fitted(self) -> None:
        on_fitted = self._fitted_ref()
        if on_fitted is not None:
            on_fitted()

    def reset(self) -> None:
        """Nothing open: stop re-fitting."""
        self.pending = False
        self.fit_view = None

    def user_navigated(self) -> None:
        self.pending = False

    def schedule_refit(self) -> None:
        self._refit_timer.start(0)

    def is_busy(self) -> bool:
        return self.jobs > 0

    def zoom_full(self) -> None:
        extent = self._extent()
        if extent is None:
            return
        self.pending = True
        s0, s1, z0, z1 = extent
        ds, dz = (s1 - s0) * (1 + 2 * PAD), (z1 - z0) * (1 + 2 * PAD)
        sc = (s0 + s1) / 2
        auto = self.ve_spin.value() <= self.ve_spin.minimum()     # "Auto": fill the panel
        ve = self.ve_spin.value()
        need = self._headroom()
        canvas = self.canvas
        canvas.setLockAxisScales(False)
        for _ in range(2):                      # the plot area depends on the axis labels
            area = canvas.plotArea()
            w, h = area.width(), area.height()
            if w < 20 or h < 20:
                w, h = max(canvas.width() - 80.0, 200.0), max(canvas.height() - 40.0, 100.0)
            room = min(need, MAX_HEADROOM * h)  # pixels kept free above the padded data
            if auto:                            # the exaggeration that fills both ways
                ve = min(max((ds / w) / (dz / (h - room)), AUTO_MIN), AUTO_MAX)
            # elevation per pixel; distance per pixel = ve * epp
            epp = max(dz / (h - room), ds / (w * ve))
            dpp = ve * epp
            zc = (z0 + z1 + room * epp) / 2     # the padded data low, the room above it
            canvas.setVisiblePlotRange(sc - dpp * w / 2, sc + dpp * w / 2,
                                       zc - epp * h / 2, zc + epp * h / 2)
        canvas.setAxisScaleRatio(ve)
        canvas.setLockAxisScales(True)
        self.ve_spin.setToolTip(f"Vertical exaggeration: Auto, now {ve:.1f} × (fills the "
                                f"panel)" if auto else "Vertical exaggeration (Auto: fill "
                                "the panel)")
        self.fit_view = self._view()
        self._on_fitted()

    def _view(self) -> Extent:
        d, e = self.canvas.visibleDistanceRange(), self.canvas.visibleElevationRange()
        return d.lower(), d.upper(), e.lower(), e.upper()

    def ve_changed(self, value: float) -> None:
        if self.pending or value <= self.ve_spin.minimum():
            self.zoom_full()                    # untouched view, or Auto: fit again
        else:
            self.canvas.setAxisScaleRatio(value)
            self._on_fitted()

    def _refit(self) -> None:
        if self._extent() is not None:
            self.ve_changed(self.ve_spin.value())

    def jobs_changed(self, count: int) -> None:
        self.jobs = count
        if count == 0 and self.pending and self._extent() is not None:
            self._restore_timer.start(0)

    def _restore_fit(self) -> None:
        # The canvas zooms itself to its own full extent after its first generation
        # (cropped at the locked ratio): put our fit back. Only when the view moved, since
        # every zoom starts a follow-up job and an unconditional refit would loop.
        if not self.pending or self.fit_view is None or self._extent() is None:
            return
        view = self._view()
        tol = 1e-6 * max(1.0, *(abs(v) for v in view))
        if any(abs(a - b) > tol for a, b in zip(view, self.fit_view)):
            self.zoom_full()
