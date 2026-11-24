"""How the smooth display grids a model, besides linear interpolation on the mesh: nearest
neighbour, inverse distance, spline (scipy's RBF) and ordinary kriging, on scattered points
(the cell centres). Pure numpy/scipy.

Every method works in a vertically stretched space: z times the anisotropy (horizontal range
divided by vertical range), so layered ground, whose values change faster with depth than
along the line, is interpolated along its layers. ``interpolate`` raises ValueError when a
method cannot be used on the data (too few points, a variogram that cannot be fitted); the
caller then keeps the linear grid."""
from __future__ import annotations

import math
from dataclasses import asdict, astuple, dataclass

import numpy as np

METHODS = ("linear", "nearest", "idw", "spline", "kriging")
METHOD_NAMES = {"linear": "Linear (mesh)", "nearest": "Nearest neighbour",
                "idw": "Inverse distance", "spline": "Spline", "kriging": "Ordinary kriging"}
KERNELS = ("thin_plate_spline", "cubic", "quintic", "multiquadric", "gaussian")
VARIOGRAMS = ("spherical", "exponential", "gaussian")
DEFAULT_NEIGHBOURS = {"nearest": 1, "idw": 12, "spline": 24, "kriging": 16}
MAX_NEIGHBOURS = 64
MAX_ANISOTROPY = 20.0
#: kernels of scipy's RBFInterpolator that need a shape parameter
_SHAPED = ("multiquadric", "gaussian")
#: targets solved at once by kriging: bounds the memory of the batched systems
_BATCH = 2000
#: cells sampled for a variogram: every pair is compared, so this bounds the memory
#: (1 200 cells: 720 000 pairs, about 40 MB for a moment)
VARIOGRAM_SAMPLE = 1200
_LAG_BINS = 15
_MIN_PAIRS = 10


def _pos(v, default, cast=float, low=0.0, high=math.inf, inclusive=False):
    """``v`` as ``cast`` when finite and in range, else ``default``."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return default
    if not math.isfinite(v) or v > high or v < low or (v == low and not inclusive):
        return default
    return cast(v)


@dataclass(frozen=True)
class Interpolation:
    """The method and its settings; None means Auto (``neighbours``: the method's default;
    range, sill, nugget: fitted; ``anisotropy``: the model's cell aspect)."""
    method: str = "linear"
    power: float = 2.0
    neighbours: int | None = None
    kernel: str = "thin_plate_spline"
    smoothing: float = 0.0
    variogram: str = "spherical"
    range_m: float | None = None
    sill: float | None = None
    nugget: float | None = None
    anisotropy: float | None = None

    @property
    def is_linear(self) -> bool:
        return self.method == "linear"

    def k(self) -> int:
        return self.neighbours or DEFAULT_NEIGHBOURS.get(self.method, 12)

    def to_dict(self) -> dict:
        return asdict(self)

    def key(self) -> tuple:
        return astuple(self)

    @classmethod
    def from_dict(cls, d) -> "Interpolation":
        """Settings read back from a project; anything unusable is the default."""
        if not isinstance(d, dict):
            return cls()

        def choice(key, options, default):
            return d.get(key) if d.get(key) in options else default

        return cls(choice("method", METHODS, "linear"),
                   _pos(d.get("power"), 2.0, high=10.0),
                   _pos(d.get("neighbours"), None, int, low=1, high=MAX_NEIGHBOURS,
                        inclusive=True),
                   choice("kernel", KERNELS, "thin_plate_spline"),
                   _pos(d.get("smoothing"), 0.0, inclusive=True),
                   choice("variogram", VARIOGRAMS, "spherical"),
                   _pos(d.get("range_m"), None),
                   _pos(d.get("sill"), None, inclusive=True),
                   _pos(d.get("nugget"), None, inclusive=True),
                   _pos(d.get("anisotropy"), None, high=1e3))


# -- variogram -------------------------------------------------------------------------------
@dataclass(frozen=True)
class Variogram:
    """Semivariance against (stretched) distance: ``nugget`` + ``sill`` x the model's shape,
    reaching about 95 % of the sill at ``range_m``; 0 at distance 0."""
    model: str
    range_m: float
    sill: float
    nugget: float

    def __call__(self, h) -> np.ndarray:
        h = np.asarray(h, dtype=float)
        return np.where(h > 0, self.nugget + self.sill * _shape(self.model, h, self.range_m),
                        0.0)


def _shape(model: str, h, r) -> np.ndarray:
    x = np.asarray(h, dtype=float) / r
    if model == "spherical":
        return np.where(x < 1.0, 1.5 * x - 0.5 * x ** 3, 1.0)
    if model == "exponential":
        return 1.0 - np.exp(-3.0 * x)
    return 1.0 - np.exp(-3.0 * x ** 2)


def _finite(points, values) -> tuple[np.ndarray, np.ndarray]:
    p = np.asarray(points, dtype=float).reshape(-1, 2)
    v = np.asarray(values, dtype=float).ravel()
    ok = np.isfinite(v) & np.isfinite(p).all(axis=1)
    return p[ok], v[ok]


def _sample(p, v, max_points: int, seed: int):
    if len(v) <= max_points:
        return p, v
    pick = np.random.default_rng(seed).choice(len(v), max_points, replace=False)
    return p[pick], v[pick]


def _experimental(p, v, direction: str | None = None):
    """(lag, semivariance, pair count) per distance bin with enough pairs; ``direction``
    "h" or "v" keeps the pairs within 22.5° of horizontal or vertical."""
    i, j = np.triu_indices(len(v), 1)
    dx, dz = np.abs(p[i, 0] - p[j, 0]), np.abs(p[i, 1] - p[j, 1])
    d = np.hypot(dx, dz)
    half = 0.4142                                   # tan 22.5°
    if direction == "h":
        keep = dz <= half * dx
    elif direction == "v":
        keep = dx <= half * dz
    else:
        keep = d > 0
    keep &= d > 0
    d, sq = d[keep], ((v[i] - v[j]) ** 2)[keep]
    if not len(d):
        return np.empty(0), np.empty(0), np.empty(0)
    edges = np.linspace(0.0, d.max() / 2, _LAG_BINS + 1)
    which = np.digitize(d, edges) - 1
    inside = (which >= 0) & (which < _LAG_BINS)
    count = np.bincount(which[inside], minlength=_LAG_BINS)
    lag = np.bincount(which[inside], weights=d[inside], minlength=_LAG_BINS)
    gam = np.bincount(which[inside], weights=sq[inside], minlength=_LAG_BINS)
    good = count >= _MIN_PAIRS
    return lag[good] / count[good], 0.5 * gam[good] / count[good], count[good]


def fit_variogram(points, values, model: str = "spherical", anisotropy: float = 1.0,
                  max_points: int = VARIOGRAM_SAMPLE, seed: int = 0) -> Variogram:
    """The ``model`` variogram fitted (weighted least squares) to the experimental variogram
    of a random sample of the points; ValueError when it cannot be fitted."""
    from scipy.optimize import curve_fit
    p, v = _finite(points, values)
    if len(v) < 4:
        raise ValueError("too few cells with a value to fit a variogram")
    p = p * np.array([1.0, anisotropy])
    p, v = _sample(p, v, max_points, seed)
    var = float(np.var(v))
    if not var > 1e-12 * max(1.0, float(np.mean(v ** 2))):
        raise ValueError("the values do not vary, so no variogram can be fitted")
    h, g, n = _experimental(p, v)
    if len(h) < 3:
        raise ValueError("too few cell pairs to fit a variogram")
    hmax = float(h.max())

    def f(x, r, s, nug):
        return nug + s * _shape(model, x, r)

    try:
        (r, s, nug), _cov = curve_fit(f, h, g, p0=[hmax / 2, var, 0.0],
                                      bounds=([1e-6 * hmax, 0.0, 0.0],
                                              [10.0 * hmax, 10.0 * var, 10.0 * var]),
                                      sigma=1.0 / np.sqrt(n), maxfev=5000)
    except (RuntimeError, ValueError) as exc:
        raise ValueError(f"the variogram could not be fitted ({exc})") from exc
    if not (s + nug > 0 and math.isfinite(r)):
        raise ValueError("the fitted variogram is flat")
    return Variogram(model, float(r), float(s), float(nug))


def _crossing(h, g, level: float) -> float | None:
    """The first lag at which ``g`` reaches ``level`` (linear between bins), or None."""
    above = np.flatnonzero(g >= level)
    if not len(above):
        return None
    k = int(above[0])
    if k == 0:
        return float(h[0]) * level / max(float(g[0]), 1e-300)
    return float(np.interp(level, [g[k - 1], g[k]], [h[k - 1], h[k]]))


def estimate_anisotropy(points, values, model: str = "spherical",
                        max_points: int = VARIOGRAM_SAMPLE,
                        seed: int = 0) -> float:
    """Horizontal over vertical correlation length, from the directional variograms: the
    lags at which each reaches half the variance (a horizontal one that never does counts
    as its longest lag). Between 1 and ``MAX_ANISOTROPY``; 1 when it cannot tell."""
    p, v = _finite(points, values)
    if len(v) < 4:
        return 1.0
    p, v = _sample(p, v, max_points, seed)
    level = 0.5 * float(np.var(v))
    if not level > 0:
        return 1.0
    hh, gh, _nh = _experimental(p, v, "h")
    hv, gv, _nv = _experimental(p, v, "v")
    if len(hh) < 2 or len(hv) < 2:
        return 1.0
    across = _crossing(hv, gv, level)
    if across is None or across <= 0:
        return 1.0
    along = _crossing(hh, gh, level)
    along = float(hh.max()) if along is None else along
    return float(np.clip(along / across, 1.0, MAX_ANISOTROPY))


# -- interpolation -----------------------------------------------------------------------------
def _neighbours(tree, targets, k: int):
    d, idx = tree.query(targets, k=k)
    if k == 1:
        d, idx = d[:, None], idx[:, None]
    return d, idx


def _idw(P, v, T, k: int, power: float) -> np.ndarray:
    from scipy.spatial import cKDTree
    d, idx = _neighbours(cKDTree(P), T, k)
    scale = max(float(np.ptp(P)) if len(P) else 1.0, 1e-9)
    exact = d <= 1e-12 * scale
    w = np.where(exact, 0.0, 1.0 / np.maximum(d, 1e-12 * scale) ** power)
    out = (w * v[idx]).sum(axis=1) / np.maximum(w.sum(axis=1), 1e-300)
    hit = exact.any(axis=1)                         # on a point: its value (their mean)
    if hit.any():
        out[hit] = (np.where(exact[hit], v[idx[hit]], 0.0).sum(axis=1)
                    / exact[hit].sum(axis=1))
    return out


def _merge_duplicates(P, v):
    scale = max(float(np.ptp(P)), 1e-9)
    _u, first, inverse = np.unique(np.round(P / (1e-9 * scale)), axis=0, return_index=True,
                                   return_inverse=True)
    inverse = inverse.ravel()
    total = np.bincount(inverse, weights=v)
    count = np.bincount(inverse)
    return P[first], total / count


def _spline(P, v, T, interp: Interpolation) -> np.ndarray:
    from scipy.interpolate import RBFInterpolator
    from scipy.spatial import cKDTree
    P, v = _merge_duplicates(P, v)
    k = min(interp.k(), len(v))
    epsilon = 1.0
    if interp.kernel in _SHAPED:
        d, _i = cKDTree(P).query(P, k=2)
        spacing = float(np.median(d[:, 1])) if len(P) > 1 else 1.0
        epsilon = 1.0 / max(spacing, 1e-9)
    try:
        rbf = RBFInterpolator(P, v, neighbors=k if k < len(v) else None,
                              smoothing=interp.smoothing, kernel=interp.kernel,
                              epsilon=epsilon)
        return rbf(T)
    except (np.linalg.LinAlgError, ValueError) as exc:
        raise ValueError(f"the spline could not be solved ({exc})") from exc


def _kriging(P, v, T, interp: Interpolation, vario: Variogram) -> np.ndarray:
    from scipy.spatial import cKDTree
    k = min(interp.k(), len(v))
    d, idx = _neighbours(cKDTree(P), T, k)
    jitter = 1e-10 * max(vario.sill + vario.nugget, 1e-12)
    out = np.empty(len(T))
    for b0 in range(0, len(T), _BATCH):
        sl = slice(b0, b0 + _BATCH)
        nb = P[idx[sl]]                                         # (b, k, 2)
        D = np.linalg.norm(nb[:, :, None, :] - nb[:, None, :, :], axis=-1)
        b = len(nb)
        A = np.ones((b, k + 1, k + 1))
        A[:, :k, :k] = vario(D) + jitter * np.eye(k)
        A[:, k, k] = 0.0
        rhs = np.ones((b, k + 1))
        rhs[:, :k] = vario(d[sl])
        try:
            w = np.linalg.solve(A, rhs[..., None])[..., 0]
        except np.linalg.LinAlgError:                           # one system was singular
            w = np.stack([np.linalg.lstsq(a, r, rcond=None)[0] for a, r in zip(A, rhs)])
        out[sl] = (w[:, :k] * v[idx[sl]]).sum(axis=1)
    return out


def interpolate(points, values, targets, interp: Interpolation,
                anisotropy: float = 1.0) -> tuple[np.ndarray, dict]:
    """``values`` at ``points`` (n, 2: chainage, elevation) interpolated to ``targets``
    (m, 2) by ``interp``'s method, with z stretched by ``anisotropy``. Returns the values and
    what was fitted (kriging: range, sill, nugget, anisotropy)."""
    p, v = _finite(points, values)
    t = np.asarray(targets, dtype=float).reshape(-1, 2)
    if not len(v):
        raise ValueError("no cell has a value")
    if not len(t):
        return np.empty(0), {}
    a = anisotropy if anisotropy and math.isfinite(anisotropy) and anisotropy > 0 else 1.0
    stretch = np.array([1.0, a])
    P, T = p * stretch, t * stretch
    method = interp.method
    if method == "nearest":
        from scipy.spatial import cKDTree
        _d, idx = cKDTree(P).query(T, k=1)
        return v[idx], {}
    if method == "idw":
        return _idw(P, v, T, min(interp.k(), len(v)), interp.power), {}
    if method == "spline":
        return _spline(P, v, T, interp), {}
    if method == "kriging":
        given = (interp.range_m, interp.sill, interp.nugget)
        if None in given:
            fit = fit_variogram(P, v, interp.variogram)
            given = tuple(f if g is None else g for g, f in
                          zip(given, (fit.range_m, fit.sill, fit.nugget)))
        vario = Variogram(interp.variogram, *given)
        if not vario.range_m > 0 or not vario.sill + vario.nugget > 0:
            raise ValueError("the variogram needs a range above 0 and a sill or nugget")
        info = {"range": vario.range_m, "sill": vario.sill, "nugget": vario.nugget,
                "anisotropy": a}
        return _kriging(P, v, T, interp, vario), info
    raise ValueError(f"unknown interpolation method: {method}")
