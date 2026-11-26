"""Render the pictures of the reflection sections how-to from the Vaud demo.

    python-qgis.bat scripts/render_reflection_pictures.py [out_dir]

Unpacks demo_vaud/ as committed (git HEAD) into a temporary folder (the demo folder is never
written, and local edits to it never show), opens it offscreen and writes to ``out_dir``
(default docs/images/howto):

- ``reflection-section.jpg``: the section panel on VD-P760057, the whole line;
- ``reflection-add-data.png``: Add Data with the stack of VD-P760057 chosen, its parts
  numbered in a gutter as in render_doc_images.py (``ADD_DATA_PARTS``);
- ``reflection-display.png``: the section's Display… dialog, numbered (``DISPLAY_PARTS``);
- ``reflection-horizon.jpg``: 3 km of VD-P760057 from the ground to -575 m, in Edit, with one
  reflector drawn as a line.

segyio is looked for in .testlibs/ as the tests do (scripts/test.ps1 says how to put it
there). The background map loads from the internet; it does not show in these pictures.
Data: Federal Office of Topography swisstopo.
"""
import io
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / ".testlibs"))

LINE = "VD-P760057"
STACK = f"data/{LINE}_stack.sgy"
PANEL = (1400, 560)
JPEG_QUALITY = 88           # the panel pictures: seismic grey compresses poorly as PNG
#: the horizon picture: from s, to s, top of the view, exaggeration
ZOOM = (3900.0, 6900.0, 650.0, 1.0)
#: the reflector drawn as a line: a strong, nearly flat positive reflector at about this
#: height (read off the section's mean trace), picked on its strongest amplitude within
#: HORIZON_WINDOW of that height from HORIZON_START to HORIZON_END, a point every HORIZON_STEP
HORIZON_START = (4000.0, -416.0)
HORIZON_END = 6800.0
HORIZON_STEP = 200.0
HORIZON_WINDOW = 14.0       # m up and down (about one and a half samples near 0.5 s)
DIALOG_WIDTH = 760
DISPLAY_WIDTH = 520
#: Add Data's parts in marker order: rows of the SEG-Y box by their key, or dialog parts by
#: attribute name
ADD_DATA_PARTS = (("box", "samples"), ("box", "velocity"), ("box", "zero"),
                  ("box", "position"), ("dialog", "placement"), ("dialog", "status_block"))
DISPLAY_PARTS = ("ramp_button", "clip_check", "amplitudes_group", "show_muted_check")


def committed_vaud(target: Path) -> Path:
    """Unpack demo_vaud/ as committed (git HEAD) into ``target`` and return its folder."""
    from render_readme_images import GIT
    data = subprocess.run([GIT, "archive", "--format=tar", "HEAD", "demo_vaud"], cwd=REPO,
                          capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        archive.extractall(target, filter="data")
    return target / "demo_vaud"


def follow_reflector(layer) -> list[tuple[float, float]]:
    """(distance, elevation) on the strongest positive amplitude within HORIZON_WINDOW of the
    height of HORIZON_START, every HORIZON_STEP to HORIZON_END: a reflector as an interpreter
    picks it."""
    import numpy as np
    placed = layer.traces
    x, amp = placed.section.x, placed.section.amplitudes
    s0, z0 = HORIZON_START
    picks, next_s = [], s0
    for i in np.flatnonzero((x >= s0) & (x <= HORIZON_END)):
        if x[i] < next_s:
            continue
        zs = placed.z_top[i] - placed.depths
        near = np.flatnonzero(np.abs(zs - z0) <= HORIZON_WINDOW)
        if near.size:
            picks.append((round(float(x[i]), 2), round(float(zs[near[np.argmax(amp[i, near])]]), 2)))
            next_s += HORIZON_STEP
    if len(picks) < 2:
        raise RuntimeError("no reflector found near HORIZON_START")
    return picks


def tops(dialog, widgets) -> list[int]:
    """The top of each widget in the dialog's coordinates; a hidden one stops the script."""
    from qgis.PyQt.QtCore import QPoint
    out = []
    for name, widget in widgets:
        if not widget.isVisibleTo(dialog):
            raise RuntimeError(f"the part {name!r} is hidden: it cannot be marked")
        out.append(widget.mapTo(dialog, QPoint(0, 0)).y())
    return out


def add_data_picture(app, plugin, demo: Path, out: Path) -> None:
    import render_doc_images as rd
    from render_readme_images import save
    from vaud_data import OPTIONS

    from groundwork_geophysics.ui.add_data_dialog import AddDataDialog

    os.chdir(demo)                              # the File field shows a path inside the demo
    dialog = AddDataDialog(plugin.iface, plugin.store, None, plugin.provider)
    dialog.show()
    try:
        dialog.set_file(STACK)
        box = dialog.segy_box
        if not box.isVisible():
            raise RuntimeError(f"Add Data shows no SEG-Y box: {dialog.summary_label.text()}")
        box.set_options(OPTIONS)
        dialog.placement.select_source("file")
        dialog.name_edit.setText(LINE)
        dialog._refresh()
        app.processEvents()
        if not dialog.add_button.isEnabled():
            raise RuntimeError(f"Add is not possible: {dialog.summary_label.text()}")
        rd.full_height(dialog, app, DIALOG_WIDTH)
        parts = [(key, box._rows[key][0] if where == "box" else getattr(dialog, key))
                 for where, key in ADD_DATA_PARTS]
        marks = tops(dialog, parts)
        rd.check_no_private_path(dialog, [str(demo.parent), str(Path.home())])
        save(rd.annotate(dialog.grab().toImage(), marks), out)
    finally:
        os.chdir(REPO)
        dialog.reject()
        dialog.deleteLater()


def display_picture(app, dock, out: Path) -> None:
    import render_doc_images as rd
    from render_readme_images import save

    from groundwork_geophysics.section.scale_dialog import DisplayDialog
    (layer,) = dock.layer_list._layers.values()
    dialog = DisplayDialog(dock.layer_list, layer)
    dialog.show()
    try:
        rd.full_height(dialog, app, DISPLAY_WIDTH)
        marks = tops(dialog, [(n, getattr(dialog, n)) for n in DISPLAY_PARTS])
        rd.check_no_private_path(dialog, [str(Path.home())])
        save(rd.annotate(dialog.grab().toImage(), marks), out)
    finally:
        dialog.reject()


def render(demo: Path, out_dir: Path) -> None:
    from qgis.core import QgsApplication, QgsProject
    from render_demo_section import FakeIface, wait_idle, zoom_to
    from render_readme_images import save

    from groundwork_geophysics.plugin import WorkbenchPlugin

    app = QgsApplication.instance()
    project = QgsProject.instance()
    if not project.read(str(demo / "vaud_project.qgz")):
        raise RuntimeError("could not read the Vaud project")
    iface = FakeIface()
    plugin = WorkbenchPlugin(iface)
    plugin.initGui()
    if plugin.store is None:
        raise RuntimeError("the Vaud project has no Groundwork store")
    try:
        dock = plugin.dock
        plugin.show_section_panel()
        dock.setFloating(True)
        dock.resize(*PANEL)
        app.processEvents()
        by_name = {p.name: p.id for p in plugin.store.profiles()}
        dock.open_profile(by_name[LINE])
        wait_idle(app, dock)
        if dock.errors.text():
            raise RuntimeError(f"layer errors: {dock.errors.text()}")
        save(dock, out_dir / "reflection-section.jpg", JPEG_QUALITY)

        add_data_picture(app, plugin, demo, out_dir / "reflection-add-data.png")
        display_picture(app, dock, out_dir / "reflection-display.png")

        ctl = dock.interp

        def form(feature, _types, _names):
            feature.type, feature.name, feature.confidence = "reflector", "R1", "probable"
            return feature
        ctl.form_factory = form
        (layer,) = dock.layer_list._layers.values()
        ctl._finished("line", follow_reflector(layer))
        wait_idle(app, dock)
        ctl.start("edit")
        s0, s1, top, ve = ZOOM
        dock.ve_spin.setValue(ve)
        wait_idle(app, dock)
        zoom_to(dock, ve, s0, s1, top)
        wait_idle(app, dock)
        save(dock, out_dir / "reflection-horizon.jpg", JPEG_QUALITY)
    finally:
        # no plugin.unload() / project.clear(): the live background map can hang them; the
        # process ends with os._exit right after this
        project.setDirty(False)


def main() -> int:
    from qgis.core import QgsApplication, QgsSettings
    from qgis.PyQt.QtCore import QLocale
    from qgis.PyQt.QtGui import QFont
    from render_demo_section import UI_FONT

    from groundwork_geophysics import libs
    from groundwork_geophysics.ui.add_data_dialog import SEGY_SETTINGS_KEY

    out_dir = (Path(sys.argv[1]) if len(sys.argv) > 1
               else REPO / "docs" / "images" / "howto").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], True)
    app.initQgis()
    app.setFont(QFont(UI_FONT, 9))
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedKingdom))
    if not libs.available("segyio"):
        print("error: segyio is missing; install it into .testlibs/ (see scripts/test.ps1)",
              file=sys.stderr)
        return 1
    settings = QgsSettings()
    remembered = settings.value(SEGY_SETTINGS_KEY, None)
    tmp = Path(tempfile.mkdtemp(prefix="wb_refl_"))
    try:
        settings.remove(SEGY_SETTINGS_KEY)  # the developer's last SEG-Y settings must not show
        render(committed_vaud(tmp), out_dir)
        return 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        if remembered is not None:
            settings.setValue(SEGY_SETTINGS_KEY, remembered)
            settings.sync()
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
