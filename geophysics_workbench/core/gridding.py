"""Gridded display of section models: smooth fields, contour lines, coverage fade (no QGIS)."""
from __future__ import annotations

import numpy as np


def default_threshold(coverage) -> float:
    """Default coverage threshold: the 10th percentile of the finite values (0.0 if none)."""
    c = np.asarray(coverage, float)
    c = c[np.isfinite(c)]
    return float(np.percentile(c, 10)) if c.size else 0.0
