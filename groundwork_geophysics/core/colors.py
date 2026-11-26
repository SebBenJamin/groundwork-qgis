"""Colour scales for section rendering (no QGIS/Qt; matplotlib.colormaps only)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from matplotlib import colormaps

COLORMAPS: list[str] = ["Spectral_r", "turbo", "jet", "viridis", "RdYlBu_r", "gray", "gray_r"]


@dataclass
class ColorScale:
    cmap: str = "Spectral_r"
    vmin: float = 1.0
    vmax: float = 1000.0
    log: bool = True
    #: a QGIS colour ramp the user chose (its XML, to edit it again) and its colours as a
    #: 256-entry table (r, g, b, a) made on the main thread; empty / None: ``cmap`` draws
    ramp: str = ""
    lut: tuple | None = None

    def __post_init__(self):
        if self.lut is not None:
            self.lut = tuple(tuple(int(c) for c in row) for row in self.lut)
        if self.cmap not in COLORMAPS:
            raise ValueError(f"Unknown colormap {self.cmap!r}; choose one of {COLORMAPS}")
        if not self.vmax > self.vmin:
            raise ValueError(f"vmax ({self.vmax}) must be greater than vmin ({self.vmin})")
        if self.log and not self.vmin > 0:
            raise ValueError(f"vmin must be > 0 on a log scale, got {self.vmin}")

    def rgba(self, values) -> np.ndarray:
        """Map values to an (n, 4) uint8 array. Out-of-range values clip to the end
        colours; nan (and non-positive values on a log scale) get alpha 0."""
        v = np.asarray(values, dtype=float).ravel()
        valid = np.isfinite(v)
        if self.log:
            valid &= v > 0
        with np.errstate(invalid="ignore", divide="ignore"):
            if self.log:
                t = (np.log10(v) - np.log10(self.vmin)) / (np.log10(self.vmax) - np.log10(self.vmin))
            else:
                t = (v - self.vmin) / (self.vmax - self.vmin)
        t = np.clip(np.where(valid, t, 0.0), 0.0, 1.0)
        if self.lut:
            table = np.asarray(self.lut, dtype=np.uint8).reshape(-1, 4)
            out = table[np.rint(t * (len(table) - 1)).astype(int)].copy()
        else:
            out = np.rint(colormaps[self.cmap](t) * 255).astype(np.uint8)
        out[~valid, :] = 0
        return out

    @classmethod
    def auto(cls, values, log: bool = True, percentiles=(2, 98), cmap: str = "Spectral_r") -> "ColorScale":
        v = np.asarray(values, dtype=float).ravel()
        v = v[np.isfinite(v)]
        if log:
            v = v[v > 0]
        if v.size == 0:
            raise ValueError("No usable values to derive a colour scale from")
        lo, hi = (float(p) for p in np.percentile(v, percentiles))
        if lo == hi:
            if log:
                lo, hi = lo / 1.1, hi * 1.1
            elif lo == 0:
                lo, hi = -1.0, 1.0
            else:
                lo, hi = lo - 0.1 * abs(lo), hi + 0.1 * abs(hi)
        return cls(cmap, lo, hi, log)

    def to_dict(self) -> dict:
        return {"cmap": self.cmap, "vmin": float(self.vmin), "vmax": float(self.vmax), "log": bool(self.log)}

    @classmethod
    def from_dict(cls, d: dict) -> "ColorScale":
        return cls(str(d["cmap"]), float(d["vmin"]), float(d["vmax"]), bool(d["log"]))
