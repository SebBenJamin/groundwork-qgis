"""Build the release zips in dist/:

    python-qgis.bat scripts/package.py [--guelpe <fresh Gülpe demo folder>] [--erfurt <fresh Erfurt demo folder>]
    [--calhoun <fresh Calhoun demo folder>]

dist/groundwork_geophysics-<version>.zip       the plugin, top folder groundwork_geophysics/
                                              (what Plugins > Install from ZIP expects)
dist/groundwork_geophysics-demo-<version>.zip  the contents of demo/: unzip anywhere and open
                                              demo_project.qgz
dist/groundwork_geophysics-demo-guelpe-<version>.zip  the real-data demo (demo_guelpe/); open guelpe_project.qgz
dist/groundwork_geophysics-demo-erfurt-<version>.zip  the real-data demo (demo_erfurt/); open erfurt_project.qgz
dist/groundwork_geophysics-demo-calhoun-<version>.zip  the refraction demo (demo_calhoun/); open calhoun_project.qgz

The version comes from groundwork_geophysics/metadata.txt. Byte caches, editor or SQLite
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
PLUGIN = REPO / "groundwork_geophysics"
DEMO = REPO / "demo"
DEMO_GUELPE = REPO / "demo_guelpe"
DEMO_ERFURT = REPO / "demo_erfurt"
DEMO_CALHOUN = REPO / "demo_calhoun"
DIST = REPO / "dist"
EXCLUDE_DIRS = {"__pycache__", ".pytest_cache", ".git"}
#: folders by pattern: the 3D view's point clouds and section pictures beside a store, made
#: again from the models wherever a 3D view needs them (git-ignored too)
EXCLUDE_DIR_PATTERNS = ("*_groundwork_3d",)
EXCLUDE_FILES = ("*.qto3settings", "*.pyc", "*.pyo", "*~", "*.bak", "*.qgs~", "*.qgz~", "*-wal", "*-shm",
                 "*-journal", "*.aux.xml", ".DS_Store", "Thumbs.db")
#: a guard against data or build output leaking into the plugin zip (code and the FGDC
#: patterns were 0.996 MB after Add Data's several files, close to the old 1 MB guard)
MAX_PLUGIN_BYTES = 1_500_000


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
        if any(fnmatch.fnmatch(folder, pat)
               for folder in rel.parts[:-1] for pat in EXCLUDE_DIR_PATTERNS):
            continue
        if path.is_file() and not any(fnmatch.fnmatch(path.name, pat) for pat in EXCLUDE_FILES):
            out.append(path)
    return out


def _find_git() -> str | None:
    """git on PATH, else Git for Windows' usual place (QGIS's Python has a short PATH)."""
    import os
    import shutil
    found = shutil.which("git")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("LOCALAPPDATA", "") + r"\Programs"):
        exe = Path(base) / "Git" / "cmd" / "git.exe"
        if exe.is_file():
            return str(exe)
    return None


GIT = _find_git()


def entry_bytes(path: Path, repo: Path = REPO) -> bytes:
    """The committed content of ``path`` when git tracks it and it has local changes (for
    example drawings made while testing the demo in QGIS), otherwise the file on disk."""
    import subprocess
    if GIT is None:
        return path.read_bytes()
    rel = path.resolve().relative_to(repo.resolve()).as_posix()
    try:
        changed = subprocess.run([GIT, "-C", str(repo), "diff", "--quiet", "HEAD", "--", rel],
                                 capture_output=True).returncode == 1
        if changed:
            return subprocess.run([GIT, "-C", str(repo), "show", f"HEAD:{rel}"],
                                  capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pass                                    # no git: ship what is on disk
    return path.read_bytes()


def write_zip(target: Path, entries: list[tuple[Path, str]]) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(".zip.part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for src, arcname in entries:
            zf.writestr(zipfile.ZipInfo.from_file(src, arcname), entry_bytes(src),
                        compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    tmp.replace(target)
    return target


def build(dist: Path = DIST, guelpe_src: Path = DEMO_GUELPE,
          erfurt_src: Path = DEMO_ERFURT,
          calhoun_src: Path = DEMO_CALHOUN) -> tuple[Path, ...]:
    """The five zips. ``guelpe_src`` / ``erfurt_src`` / ``calhoun_src``: the real-data demo
    folders to ship, by default the committed demo_guelpe/, demo_erfurt/ and demo_calhoun/; a freshly built folder
    (``build_demo_guelpe.py --out``, ``build_demo_erfurt.py --out``) ships a clean demo without
    touching the committed one."""
    ver = version()
    plugin_entries = [(p, f"{PLUGIN.name}/{p.relative_to(PLUGIN).as_posix()}")
                      for p in files_under(PLUGIN)]
    if not (PLUGIN / "LICENSE").exists():
        plugin_entries.append((REPO / "LICENSE", f"{PLUGIN.name}/LICENSE"))
    plugin_zip = write_zip(dist / f"{PLUGIN.name}-{ver}.zip", plugin_entries)
    demo_zip = _demo_zip(DEMO, f"{PLUGIN.name}-demo-{ver}", "demo_project.qgz", dist)
    guelpe_zip = _demo_zip(Path(guelpe_src), f"{PLUGIN.name}-demo-guelpe-{ver}", "guelpe_project.qgz",
                           dist)
    erfurt_zip = _demo_zip(Path(erfurt_src), f"{PLUGIN.name}-demo-erfurt-{ver}", "erfurt_project.qgz",
                           dist)
    size = plugin_zip.stat().st_size
    if size >= MAX_PLUGIN_BYTES:
        raise RuntimeError(f"{plugin_zip.name} is {size} bytes (limit {MAX_PLUGIN_BYTES})")
    calhoun_zip = _demo_zip(Path(calhoun_src), f"{PLUGIN.name}-demo-calhoun-{ver}",
                            "calhoun_project.qgz", dist)
    return plugin_zip, demo_zip, guelpe_zip, erfurt_zip, calhoun_zip


def _demo_zip(src: Path, name: str, project: str, dist: Path) -> Path:
    """``dist/<name>.zip`` of the files under ``src``; ``project`` must be among them."""
    entries = [(p, p.relative_to(src).as_posix()) for p in files_under(src)]
    if not any(arc == project for _, arc in entries):
        raise RuntimeError(f"{src.name}/{project} is missing; run its build script first")
    return write_zip(dist / f"{name}.zip", entries)


def main() -> int:
    if GIT is None:
        print("warning: git not found; files with local changes ship as they are on disk",
              file=sys.stderr)
    guelpe = DEMO_GUELPE
    if "--guelpe" in sys.argv:
        guelpe = Path(sys.argv[sys.argv.index("--guelpe") + 1]).resolve()
    erfurt = DEMO_ERFURT
    if "--erfurt" in sys.argv:
        erfurt = Path(sys.argv[sys.argv.index("--erfurt") + 1]).resolve()
    calhoun = DEMO_CALHOUN
    if "--calhoun" in sys.argv:
        calhoun = Path(sys.argv[sys.argv.index("--calhoun") + 1]).resolve()
    try:
        zips = build(guelpe_src=guelpe, erfurt_src=erfurt, calhoun_src=calhoun)
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
