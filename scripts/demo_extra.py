"""Additions to the demo builder (scripts/build_demo.py stays under ~400 lines).

- ``make_p4``: a fourth line, P4, for the release note's "create a profile from a CSV"
  walkthrough. Only its station file is written (``data/stations/P4_electrodes.csv``); it
  is not in the demo store, so the user's new profile duplicates nothing.
- ``set_author`` / ``strip_save_user``: keep personal data out of ``demo_project.qgz``.
  QGIS writes the OS account and full name of whoever saves a project into the
  ``saveUser`` / ``saveUserFull`` attributes and, for new projects, the metadata author.
"""
from __future__ import annotations

import math
import re
import zipfile
from configparser import ConfigParser
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
METADATA = ROOT / "geophysics_workbench" / "metadata.txt"
P4_SHIFT = -140.0          # m along P1's direction: P3 lies 70 m on one side, P4 70 m on the other
P4_LENGTH = 235.0
_SAVE_USER = re.compile(rb'(saveUser(?:Full)?)="[^"]*"')


# ---------------------------------------------------------------- P4
def make_p4(p1, p3):
    """P4: parallel to P3, mirrored to the other side of the powerline, crossing P1 and P2.
    ``p1``/``p3`` are build_demo ``Profile`` objects; the result is one too."""
    u = (math.cos(p1.azimuth), math.sin(p1.azimuth))
    v = (math.cos(p3.azimuth), math.sin(p3.azimuth))
    cx = p3.x0 + v[0] * p3.length / 2 + P4_SHIFT * u[0]
    cy = p3.y0 + v[1] * p3.length / 2 + P4_SHIFT * u[1]
    return replace(p3, name="P4", x0=cx - v[0] * P4_LENGTH / 2, y0=cy - v[1] * P4_LENGTH / 2,
                   length=P4_LENGTH, lens_s=None)


# ---------------------------------------------------------------- personal data
def plugin_author(path: Path = METADATA) -> str:
    cp = ConfigParser()
    cp.read(path, encoding="utf-8")
    return cp["general"]["author"]


def set_author(project, author: str | None = None) -> None:
    """Project metadata author = the plugin author (not the account that runs the build)."""
    md = project.metadata()
    md.setAuthor(author or plugin_author())
    project.setMetadata(md)


def strip_save_user(qgz: Path) -> None:
    """Blank the ``saveUser`` / ``saveUserFull`` attributes of the .qgs inside ``qgz``."""
    qgz = Path(qgz)
    with zipfile.ZipFile(qgz) as zf:
        entries = [(info, zf.read(info.filename)) for info in zf.infolist()]
    tmp = qgz.with_suffix(".qgz.part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for info, data in entries:
            if info.filename.lower().endswith(".qgs"):
                data = _SAVE_USER.sub(rb'\1=""', data)
            zf.writestr(info, data)
    tmp.replace(qgz)
