"""Lithology fill patterns shipped with the plugin (FGDC-STD-013-2006, public domain / CC0).

While the plugin is loaded, this folder is one of QGIS's SVG search paths, so the patterns
show up in every SVG fill picker (QGIS's own style editor, the Borehole style window). They
are offered, never assigned: no word or code is matched to a pattern. The path is added as a
QGIS *default* path for this session only; the user's SVG path settings are never written."""
from __future__ import annotations

from pathlib import Path

from qgis.core import QgsApplication, QgsSettings

PATTERN_DIR = Path(__file__).resolve().parent
_USER_KEY = "svg/searchPathsForSVG"
_previous: list[str] | None = None


def _norm(path: str) -> str:
    return str(path).replace("\\", "/").rstrip("/")


def _defaults() -> list[str]:
    """QGIS's current default SVG paths (``svgPaths()`` minus the user's own settings)."""
    user = {_norm(p) for p in (QgsSettings().value(_USER_KEY, []) or [])}
    return [p for p in QgsApplication.svgPaths() if _norm(p) not in user]


def register_svg_path() -> None:
    global _previous
    ours = _norm(PATTERN_DIR)
    current = _defaults()
    if any(_norm(p) == ours for p in current):
        return
    _previous = current
    QgsApplication.setDefaultSvgPaths(current + [str(PATTERN_DIR)])


def unregister_svg_path() -> None:
    global _previous
    if _previous is None:
        return
    QgsApplication.setDefaultSvgPaths(_previous)
    _previous = None
