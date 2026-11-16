"""Make a demo's plate layouts again from their plate definitions (after a template change).

    python-qgis.bat scripts/refresh_demo_plates.py demo_guelpe

Works on a temporary copy of the demo folder: opens the project with the plugin, removes
each plate's layout and creates it again, then puts only the new ``<Layouts>`` block into the
committed project file. Nothing else in the project changes, the demo's Groundwork file is
never written, and the copy uses the committed Groundwork file, so local test edits (notes,
drawings) never reach the plates' texts.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from qgis.core import QgsApplication, QgsProject  # noqa: E402

#: QGIS's Python launcher sets its own PATH, so git may not be found by name
GIT = shutil.which("git") or r"C:\Program Files\Git\cmd\git.exe"
LAYOUTS = re.compile(r"<Layouts>.*?</Layouts>|<Layouts/>", re.S)


def _qgs_text(qgz: Path) -> tuple[str, str]:
    with zipfile.ZipFile(qgz) as z:
        name = next(n for n in z.namelist() if n.endswith(".qgs"))
        return name, z.read(name).decode("utf-8")


def _replace_layouts(qgz: Path, layouts: str) -> None:
    name, text = _qgs_text(qgz)
    if len(LAYOUTS.findall(text)) != 1:
        raise RuntimeError(f"{qgz.name}: expected one <Layouts> block")
    new_text = LAYOUTS.sub(lambda _m: layouts, text)
    tmp = qgz.with_suffix(".tmp")
    with zipfile.ZipFile(qgz) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            data = new_text.encode("utf-8") if info.filename == name else src.read(info.filename)
            dst.writestr(info, data)
    tmp.replace(qgz)


def refresh(folder: Path) -> None:
    from render_demo_section import FakeIface

    from groundwork_geophysics.plates.build import create_or_update_plate, find_plate_layout
    from groundwork_geophysics.plates.sources import read_plates
    from groundwork_geophysics.plugin import WorkbenchPlugin
    [qgz] = sorted(folder.glob("*_project.qgz"))
    tmp = Path(tempfile.mkdtemp(prefix="wb_plates_"))
    try:
        copy = tmp / folder.name
        shutil.copytree(folder, copy, ignore=shutil.ignore_patterns("*.gpkg-wal", "*.gpkg-shm"))
        for store in copy.glob("*_groundwork.gpkg"):    # the committed file, not local edits
            store.write_bytes(subprocess.run(
                [GIT, "show", f"HEAD:{folder.name}/{store.name}"], cwd=REPO,
                capture_output=True, check=True).stdout)
        plugin = WorkbenchPlugin(FakeIface())
        plugin.initGui()                     # item types first, or QGIS drops plate items
        project = QgsProject.instance()
        if not project.read(str(copy / qgz.name)):
            raise RuntimeError(f"could not read {qgz.name}")
        plates = read_plates(project)
        for plate in plates:
            layout = find_plate_layout(project, plate)
            if layout is not None:
                project.layoutManager().removeLayout(layout)
            create_or_update_plate(project, plugin.store, plugin.provider, plate)
            print(f"{folder.name}: plate {plate.number} – {plate.title}")
        out = copy / "refreshed.qgs"         # beside the project: paths stay relative
        if not project.write(str(out)):
            raise RuntimeError("could not write the refreshed project")
        layouts = LAYOUTS.findall(out.read_text(encoding="utf-8"))
        if len(layouts) != 1:
            raise RuntimeError(f"expected one <Layouts> block, found {len(layouts)}")
        block = layouts[0]
        for prefix in (copy.as_posix() + "/", str(copy) + "\\"):   # the mini-map's layer refs
            block = block.replace(prefix, "./")                    # as the committed file has
        layouts = [block]
        for marker in (str(tmp), tmp.as_posix(), tmp.name):
            at = layouts[0].find(marker)
            if at >= 0:
                raise RuntimeError("the refreshed layouts point into the temp copy: "
                                   f"…{layouts[0][max(at - 200, 0):at + 80]}…")
        project.setDirty(False)
        _replace_layouts(folder / qgz.name, layouts[0])
        print(f"wrote {folder / qgz.name}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    app = QgsApplication([], True)
    app.initQgis()
    try:
        if len(sys.argv) != 2:                  # one demo per run: a second one in the same
            raise SystemExit(__doc__)           # process crashes QGIS on its way out
        refresh(REPO / sys.argv[1])
        return 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)                 # no teardown: live web requests can hang it
