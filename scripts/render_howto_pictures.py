"""Render the how-to pictures that need the Gülpe demo's real section.

    python-qgis.bat scripts/render_howto_pictures.py [out_dir]

Opens a temporary copy of demo_guelpe/ offscreen with its committed Groundwork file (as
render_readme_images.py does: the demo folder is never written, and local edits to it never
show), opens Transect 3 and writes to ``out_dir`` (default docs/images/howto):

- ``display-modes.png``: the section as cells, and as smooth field + contours faded where
  the coverage is low (section-panel.md, first-steps.md);
- ``display.png``: the Display… dialog in that second state, its parts numbered as in
  render_doc_images.py (section-panel.md);
- ``interpretation.png``: the section panel in Edit with a polygon named A drawn around the
  high-resistivity body (interpretation.md, first-steps.md);
- ``borehole-viewer.png``: the borehole viewer with the transect's cores (boreholes.md,
  first-steps.md);
- ``borehole-viewer-curves.png``: the same with every curve ticked (release note 0.16.0);
- ``import-las.png``: Import LAS… with three small example files, one of them without a
  borehole yet (boreholes.md).

The geology strips come from a live WFS and need the internet; without it they are missing.
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QPA_FONTDIR", r"C:\Windows\Fonts")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

import numpy as np  # noqa: E402
from qgis.core import QgsApplication, QgsProject  # noqa: E402
from qgis.PyQt.QtCore import QLocale  # noqa: E402
from qgis.PyQt.QtCore import QRect, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402

import render_readme_images as rr  # noqa: E402
from render_demo_section import UI_FONT, FakeIface, wait_idle, zoom_to  # noqa: E402

VIEW = (85.0, 175.0, 27.0, 3.6)          # from s, to s, top of the view, exaggeration
CANVAS = (1150, 330)                     # the section canvas alone, for display-modes
CAPTION_H = 26
#: the body drawn as feature A: (distance, elevation) along Transect 3
BODY = [(117, 24.4), (125, 24.9), (133, 24.9), (141, 24.0), (142, 22.2), (135, 21.0),
        (126, 21.3), (118, 22.6)]
VIEWER = (1100, 620)
VIEWER_CURVES = (1560, 620)              # every core and its curve tracks, in even spacing
CURVES_SHOWN = ("toc", "sand", "silt", "clay")
DISPLAY_WIDTH = 520
FADE_PERCENTILE = 30                     # of the model's coverage: the fade shows clearly
#: Import LAS…: the example files (tests/fixtures/las) under the names shown, and the
#: boreholes offered; the last file names no well, so it waits for a borehole
LAS_FILES = (("bh1_feet.las", "jw11_gamma.las"), ("wrapped_metres.las", "B7_logs.las"),
             ("no_name.las", "run3.las"))
LAS_BOREHOLES = ("B7", "JW11", "JW12")
LAS_SIZE = (860, 230)


def look(app, dock, **changes) -> None:
    """Draw the open profile's model with ``changes`` (LayerStyle fields) and zoom to VIEW."""
    (dataset_id,) = [d for d, row in dock.layer_list._rows.items() if row.check.isChecked()]
    dock.layer_list.set_display(dataset_id, **changes)
    wait_idle(app, dock)
    s0, s1, top, ve = VIEW
    dock.ve_spin.setValue(ve)
    wait_idle(app, dock)
    zoom_to(dock, ve, s0, s1, top)
    wait_idle(app, dock)


def captioned(images: list[tuple[str, QImage]]) -> QImage:
    """The images one below the other, each with its caption above it."""
    width = max(img.width() for _t, img in images)
    height = sum(img.height() + CAPTION_H for _t, img in images)
    out = QImage(width, height, QImage.Format.Format_ARGB32)
    out.fill(QColor("white"))
    painter = QPainter(out)
    font = QFont(UI_FONT, 10)
    font.setBold(True)
    painter.setFont(font)
    y = 0
    for text, img in images:
        painter.drawText(QRect(8, y, width - 16, CAPTION_H),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        painter.drawImage(0, y + CAPTION_H, img)
        y += CAPTION_H + img.height()
    painter.end()
    return out


def render(demo: Path, out_dir: Path) -> None:
    import render_doc_images as rd

    from groundwork_geophysics.plugin import WorkbenchPlugin
    from groundwork_geophysics.section.scale_dialog import DisplayDialog

    app = QgsApplication.instance()
    iface = FakeIface()
    plugin = WorkbenchPlugin(iface)
    plugin.initGui()
    project = QgsProject.instance()
    try:
        if not project.read(str(demo / "guelpe_project.qgz")):
            raise RuntimeError("could not read the Gülpe project")
        iface.mainWindow().resize(*rr.WINDOW)
        dock = plugin.dock
        plugin.show_section_panel()
        by_name = {p.name: p for p in plugin.store.profiles()}
        dock.open_profile(by_name[rr.PROFILE].id)
        wait_idle(app, dock)
        rr.spin(app, 8.0)                       # the live geology strips
        plugin.provider.notify_changed()
        wait_idle(app, dock)
        for row in dock.layer_list._rows.values():     # the model alone, without the misfit
            if rr.HIDE in row.check.full_text().lower():
                row.check.setChecked(False)
        wait_idle(app, dock)
        dock.setFloating(True)
        dock.resize(*rr.SECTION_ALONE)
        app.processEvents()
        dock.canvas.setFixedSize(*CANVAS)
        wait_idle(app, dock)

        look(app, dock, mode="cells", fade_coverage=False)
        cells = dock.canvas.grab().toImage()
        (dataset_id,) = [d for d, row in dock.layer_list._rows.items() if row.check.isChecked()]
        coverage = dock.layer_list._layers[dataset_id].mesh.coverage
        threshold = round(float(np.nanpercentile(coverage, FADE_PERCENTILE)), 1)
        look(app, dock, mode="smooth+contours", fade_coverage=True,
             coverage_threshold=threshold)
        smooth = dock.canvas.grab().toImage()
        rr.save(captioned([("Cells (as inverted)", cells),
                           ("Smooth field + contours, faded where coverage is low", smooth)]),
                out_dir / "display-modes.png")

        dialog = DisplayDialog(dock.layer_list, dock.layer_list._layers[dataset_id])
        dialog.show()
        try:
            rd.full_height(dialog, app, DISPLAY_WIDTH)
            points = rd.marker_points(dialog, ("colour_ramp", "display_group",
                                               "contours_group", "coverage_group"))
            rd.check_no_private_path(dialog, [str(demo.parent), str(Path.home())])
            rr.save(rd.annotate(dialog.grab().toImage(), [p.y() for p in points]),
                    out_dir / "display.png")
        finally:
            dialog.reject()

        dock.canvas.setMinimumSize(0, 0)
        dock.canvas.setMaximumSize(16777215, 16777215)
        look(app, dock, mode="cells", fade_coverage=False)
        ctl = dock.interp

        def form(feature, _types, _names):
            feature.type, feature.name, feature.confidence = "resistive body", "A", "probable"
            return feature
        ctl.form_factory = form
        ctl._finished("polygon", BODY)
        wait_idle(app, dock)
        ctl.start("edit")
        look(app, dock)
        rr.save(dock, out_dir / "interpretation.png")

        plugin.open_borehole_viewer()
        viewer = plugin.borehole_viewer
        if viewer is None:
            raise RuntimeError("the borehole viewer did not open")
        viewer.resize(*VIEWER)
        rr.spin(app, 3.0)
        rr.save(viewer, out_dir / "borehole-viewer.png")
        # the cores' lab values as curves, in even spacing (tracks need the room)
        viewer.mode_combo.setCurrentIndex(viewer.mode_combo.findData("even"))
        viewer.resize(*VIEWER_CURVES)
        for key in list(viewer._curve_checks):          # ticking one makes the boxes anew
            if viewer.curve_check(key).text().split()[0].lower() in CURVES_SHOWN:
                viewer.curve_check(key).setChecked(True)
                app.processEvents()
        viewer.canvas.fit_view()
        viewer.canvas.update()
        rr.spin(app, 2.0)
        rr.save(viewer, out_dir / "borehole-viewer-curves.png")

        from groundwork_geophysics.ui.las_import_dialog import LasImportDialog
        las_dir = demo.parent / "las"
        las_dir.mkdir()
        for source, shown in LAS_FILES:
            shutil.copy(REPO / "tests" / "fixtures" / "las" / source, las_dir / shown)
        las = LasImportDialog([las_dir / shown for _s, shown in LAS_FILES], LAS_BOREHOLES)
        las.show()
        try:
            las.resize(*LAS_SIZE)
            rr.spin(app, 0.5)
            rd.check_no_private_path(las, [str(demo.parent), str(Path.home())])
            rr.save(las, out_dir / "import-las.png")
        finally:
            las.reject()
    finally:
        # no plugin.unload() / project.clear(): with live web requests still open they can
        # hang; the process ends with os._exit right after this
        project.setDirty(False)


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs" / "images" / "howto"
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QgsApplication([], True)
    app.initQgis()
    app.setFont(QFont(UI_FONT, 9))
    QLocale.setDefault(QLocale(QLocale.Language.English, QLocale.Country.UnitedKingdom))
    tmp = Path(tempfile.mkdtemp(prefix="wb_howto_"))
    try:
        demo = tmp / "demo_guelpe"
        shutil.copytree(REPO / "demo_guelpe", demo,
                        ignore=shutil.ignore_patterns("*.gpkg-wal", "*.gpkg-shm"))
        rr.committed_store(demo / rr.STORE)
        import subprocess                       # the project as committed, too
        (demo / "guelpe_project.qgz").write_bytes(subprocess.run(
            [rr.GIT, "show", "HEAD:demo_guelpe/guelpe_project.qgz"], cwd=REPO,
            capture_output=True, check=True).stdout)
        render(demo, out_dir)
        return 0
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    rc = main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(rc)
