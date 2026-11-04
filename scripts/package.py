"""Build the release zips in dist/:

    python-qgis.bat scripts/package.py

dist/geophysics_workbench-<version>.zip       the plugin, top folder geophysics_workbench/
                                              (what Plugins > Install from ZIP expects)
dist/geophysics_workbench-demo-<version>.zip  the contents of demo/: unzip anywhere and open
                                              demo_project.qgz
dist/geophysics_workbench-demo-guelpe-<version>.zip  the real-data demo (demo_guelpe/); open guelpe_project.qgz

The version comes from geophysics_workbench/metadata.txt. Byte caches, editor or SQLite
side files and GDAL .aux.xml statistics are left out; so are tests, spikes and the demo
(they live outside the plugin folder).
"""
from __future__ import annotations

import fnmatch
import sys
import zipfile
from configparser import ConfigParser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PLUGIN = REPO / "geophysics_workbench"
DEMO = REPO / "demo"
DEMO_GUELPE = REPO / "demo_guelpe"
DIST = REPO / "dist"
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".git"}
EXCLUDE_FILES = ("*.pyc", "*.pyo", "*~", "*.bak", "*.qgs~", "*.qgz~", "*-wal", "*-shm",
                 "*-journal", "*.aux.xml", ".DS_Store", "Thumbs.db")
MAX_PLUGIN_BYTES = 1_000_000


def version() -> str:
    cp = ConfigParser()
    cp.read(PLUGIN / "metadata.txt", encoding="utf-8")
    return cp["general"]["version"]


def files_under(root: Path) -> list[Path]:
    out = []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts):
            continue
        if path.is_file() and not any(fnmatch.fnmatch(path.name, pat) for pat in EXCLUDE_FILES):
            out.append(path)
    return out


def write_zip(target: Path, entries: list[tuple[Path, str]]) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".zip.part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src, arcname in entries:
            zf.write(src, arcname)
    tmp.replace(target)
    return target


def build(dist: Path = DIST) -> tuple[Path, Path]:
    ver = version()
    plugin_entries = [(p, f"{PLUGIN.name}/{p.relative_to(PLUGIN).as_posix()}")
                      for p in files_under(PLUGIN)]
    if not (PLUGIN / "LICENSE").exists():
        plugin_entries.append((REPO / "LICENSE", f"{PLUGIN.name}/LICENSE"))
    plugin_zip = write_zip(dist / f"{PLUGIN.name}-{ver}.zip", plugin_entries)
    demo_zip = _demo_zip(DEMO, f"{PLUGIN.name}-demo-{ver}", "demo_project.qgz", dist)
    guelpe_zip = _demo_zip(DEMO_GUELPE, f"{PLUGIN.name}-demo-guelpe-{ver}", "guelpe_project.qgz",
                           dist)
    size = plugin_zip.stat().st_size
    if size >= MAX_PLUGIN_BYTES:
        raise RuntimeError(f"{plugin_zip.name} is {size} bytes (limit {MAX_PLUGIN_BYTES})")
    return plugin_zip, demo_zip, guelpe_zip


def _demo_zip(src: Path, name: str, project: str, dist: Path) -> Path:
    """``dist/<name>.zip`` of the files under ``src``; ``project`` must be among them."""
    entries = [(p, p.relative_to(src).as_posix()) for p in files_under(src)]
    if not any(arc == project for _, arc in entries):
        raise RuntimeError(f"{src.name}/{project} is missing; run its build script first")
    return write_zip(dist / f"{name}.zip", entries)


def main() -> int:
    try:
        zips = build()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for z in zips:
        with zipfile.ZipFile(z) as zf:
            n = len(zf.namelist())
        print(f"{z.relative_to(REPO)}  {z.stat().st_size:,} bytes, {n} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
