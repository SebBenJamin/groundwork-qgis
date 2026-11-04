"""Lithology colours for borehole logs and the geology band (no QGIS/Qt)."""
from __future__ import annotations

import colorsys
import hashlib

ROCK = (170, 90, 80)

# first match wins, so more specific terms come before the ones they contain
# ("sandstein" before "sand")
_TABLE: list[tuple[tuple[str, ...], tuple[int, int, int]]] = [
    (("torf", "peat"), (90, 60, 30)),
    (("mutterboden", "topsoil"), (110, 80, 50)),
    (("kies", "gravel"), (230, 160, 60)),
    (("sandstein", "sandstone"), ROCK),
    (("sand",), (240, 220, 120)),
    (("schluff", "silt"), (200, 170, 120)),
    (("lehm", "loam", "geschiebemergel"), (170, 130, 90)),
    (("ton", "clay"), (120, 140, 170)),
    (("mergel", "marl"), (170, 180, 150)),
    (("fels", "rock", "bedrock", "kalk"), ROCK),
]


def lithology_colour(name: str) -> tuple[int, int, int]:
    """RGB for a lithology description: a case-insensitive substring match against the table,
    else a pastel that depends only on the lower-cased name (so it is stable between runs)."""
    low = name.lower()
    for words, rgb in _TABLE:
        if any(w in low for w in words):
            return rgb
    return label_colour(name)


def label_colour(name: str) -> tuple[int, int, int]:
    """A pastel that depends only on the lower-cased text: different texts get different
    colours (unlike ``lithology_colour``, which gives every "…sand…" the same yellow), and
    the same text the same colour in every run and on every profile."""
    low = name.lower()
    h = hashlib.md5(low.encode("utf-8")).digest()
    r, g, b = colorsys.hls_to_rgb(h[0] / 255.0, 0.78, 0.45 + 0.2 * h[1] / 255.0)
    return int(round(r * 255)), int(round(g * 255)), int(round(b * 255))
